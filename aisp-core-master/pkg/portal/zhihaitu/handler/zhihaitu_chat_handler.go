package handler

import (
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/cafe/rest"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/censor/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	zhihaitu_graph "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf/zhihaitu_api_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf/zhihaitu_chat_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	model2 "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"golang.org/x/exp/slices"
)

const openApiAuthorizationConfigKey = "zhihaitu.openApiAuthorization"

var openApiAuthorization = config.GetString(openApiAuthorizationConfigKey, "")

type SubmitMsgHandler struct {
	rest.BaseHandler
	chatService         *service.ChatServiceImpl
	userRegulateService rpc.UserRegulateService
}

func NewSubmitMsgHandler() rest.Handler {
	return &SubmitMsgHandler{
		chatService:         service.DefaultChatService,
		userRegulateService: impl.DefaultUserRegulateService,
	}
}

const (
	generateTypeNormal     = "NORMAL"
	generateTypeRegenerate = "REGENERATE"
)

const (
	passAudit   = "PASS_AUDIT"
	noPassAudit = "NO_PASS_AUDIT"
)

func buildHistoryDialogue(messages []*model.ChatMessage) []*message.DialogueWrapper {
	var historyDialogue []*message.DialogueWrapper

	var dialogue *message.DialogueWrapper
	for index, chatMessage := range messages {
		if index == len(messages)-1 {
			break
		}

		var role = chatMessage.GetRole()
		if role == "" {
			continue
		}
		if role == model2.RoleTypeUser.ToConvert() {
			dialogue = &message.DialogueWrapper{}
			dialogue.Query = chatMessage.ToDialogRecord()
		} else if role == model2.RoleTypeAI.ToConvert() {
			if dialogue != nil {
				dialogue.Answer = chatMessage.ToDialogRecord()
				historyDialogue = append(historyDialogue, dialogue)
			}
		}
	}

	return historyDialogue
}

func buildReqContext(req model.BmbChatReq, account *model.TableOpenapiAccount) (*entities.RequestContext, string, string) {
	latestMessage := req.ChatMessage[len(req.ChatMessage)-1]

	var questionMessageId string
	if generateTypeRegenerate == req.GenerateType {
		questionMessageId = latestMessage.Id
	} else {
		questionMessageId = uuid.New().String()
		latestMessage.Id = questionMessageId
	}

	question := latestMessage.Content.Pairs

	answerMessageId := uuid.New().String()

	historyDialogue := buildHistoryDialogue(req.ChatMessage)
	bizRequestContext := entities.NewRequestContextForZhihaitu(
		&proto.ChatRequest{
			Info: &proto.RequestInfo{
				SessionId: req.ConversationId,
				Message: &proto.ChatMessage{
					MessageId:   questionMessageId,
					TimestampMs: util.TimeUnixMilli(),
					Type:        proto.ChatMessageType_TEXT,
					Text:        question,
				},
				MemberId: account.MemberID,
			},
			RespMessageId: answerMessageId,
		},
		latestMessage.ParentMsgId,
		historyDialogue,
		graph_constant.ApiZhihaituChat, "", zhihaitu_chat_conf.LogicBizConfigMap)

	if slices.Contains(constant.WxbExemptSecurityReviewUser, account.Mobile) {
		bizRequestContext.SetIsExemptSecurity(true)
	}
	return bizRequestContext, questionMessageId, answerMessageId
}

func (k *SubmitMsgHandler) Post(ctx *rest.Context) (rest.Response, error) {
	req := model.BmbChatReq{}
	err := ctx.JSONArgs(&req)
	if err != nil {
		return nil, err
	}

	account := ctx.Value(constant.ZhihaituMemberIdKey).(*model.TableOpenapiAccount)

	canSubmit, _ := k.userRegulateService.CanSubmit(ctx, account.MemberID)
	if !canSubmit {
		return model.NewResponseByStatus(ctx, model.ResponseStatusNotAuthingError), nil
	}

	latestMessage := req.ChatMessage[len(req.ChatMessage)-1]
	err = k.chatService.CreateConversionIfNotExist(ctx, req.ConversationId, account, latestMessage.Content.Pairs)
	if err != nil {
		return nil, err
	}

	bizRequestContext, questionMessageId, answerMessageId := buildReqContext(req, account)

	_, response, _, err := graph.RunGraph(ctx, bizRequestContext, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
		ip := ctx.Request.Header.Get("X-Real-Ip")
		if ip == "" {
			ip = ctx.Request.Header.Get("X-Forwarded-For")
		}
		if ip != "" {
			ip = util.GetFirstIp(ip)
		}
		requestContext.DataMap().SetString(ctx, macro.ZagKeyIp, ip)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyUserAgent, ctx.Request.Header.Get("User-Agent"))
		requestContext.DataMap().SetObjMap(ctx, macro.ZagKeyQuery, bizRequestContext.GetCurrentDialogue().Query)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryText, latestMessage.Content.Pairs)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyRespMessageId, answerMessageId)
		requestContext.DataMap().SetString(ctx, macro.ZagKeySessionId, req.ConversationId)
		requestContext.DataMap().SetInt64(ctx, macro.ZagKeyMemberId, account.MemberID)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryMessageId, questionMessageId)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryParentMessageId, latestMessage.ParentMsgId)

		return nil
	})
	if err != nil {
		return nil, err
	}

	chatResponse := response.(*proto.ChatResponse)
	if chatResponse.RespType == proto.ChatRespType_REFUSE {
		return model.NewSuccessResponseByData(ctx, model.SafeAuditResp{
			MsgId:      questionMessageId,
			State:      noPassAudit,
			ChildMsgId: answerMessageId,
		}), nil
	} else {
		return model.NewSuccessResponseByData(ctx, model.SafeAuditResp{
			MsgId:      questionMessageId,
			State:      passAudit,
			ChildMsgId: answerMessageId,
		}), nil
	}
}

type GetMsgsByConvIdHandler struct {
	rest.BaseHandler
	chatService *service.ChatServiceImpl
}

func NewGetMsgsByConvIdHandler() rest.Handler {
	return &GetMsgsByConvIdHandler{
		chatService: service.DefaultChatService,
	}
}

type GetMsgByConvIdRequest struct {
	ConvId string
}

func (k *GetMsgsByConvIdHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := ctx.Value(constant.ZhihaituMemberIdKey).(*model.TableOpenapiAccount)
	var request GetMsgByConvIdRequest
	err := ctx.JSONArgs(&request)
	if err != nil {
		return nil, err
	}

	messages, err := k.chatService.GetMsgsByConvID(ctx, request.ConvId, account.ID)
	if err != nil {
		log.Error(ctx, fmt.Sprintf("GetMsgsByConvIdHandler error. accountId=%d", account.ID))
		return nil, err
	}

	convMessages := lo.Map(messages, func(item *model.TableBmbConvMessage, _ int) *model.ConvMessage {
		var role string
		if item.Role == constant.ChatRoleAi {
			role = "AI"
		} else if item.Role == constant.ChatRoleUser {
			role = "USER"
		}

		return &model.ConvMessage{
			Content:       item.Content,
			CostTimeMilli: item.CostTimeMillis,
			FeedbackMsg:   item.FeedbackMsg,
			MsgID:         item.MsgID,
			MsgType:       item.MsgType,
			ParentMsgID:   item.ParentMsgID,
			Rating:        model.CreateRatingEnum(item.Rating).String(),
			Role:          role,
			State:         item.State,
		}
	})

	if len(convMessages) != 0 {
		// 前端是根据msgId和parentMsgId来构建前后关系，如果结果有多条，第一条的parentMsgId不要为 ""，不然会导致不再构建后续关系
		// 如果第一个parentMsgId为""，就移到最后一个
		if convMessages[0].ParentMsgID == "" {
			convMessages = append(convMessages, convMessages[0])
			convMessages = convMessages[1:]
		}
	}

	return model.NewSuccessResponseByData(ctx, model.GetMsgsByConvIDResp{
		MsgInfos: convMessages,
	}), nil
}

type SimChatHandler struct {
	rest.BaseHandler
	fromWangAn bool //是否为网安请求
}

func NewSimChatHandler(fromWangAn bool) rest.Handler {
	return &SimChatHandler{
		fromWangAn: fromWangAn,
	}
}

const openApiModelName = "cpm-20b-conv-0722"
const mbznHeader = "MBZN"

func buildOpenApiHistoryDialogue(messages []*model.OpenApiChatMessage) []*message.DialogueWrapper {
	var historyDialogue []*message.DialogueWrapper

	var dialogue *message.DialogueWrapper
	for index, chatMessage := range messages {
		if index == len(messages)-1 {
			break
		}

		var role = chatMessage.Role

		if role == model2.RoleTypeUser.ToConvert() {
			dialogue = &message.DialogueWrapper{}
			dialogue.Query = chatMessage.ToDialogRecord()
		} else if role == model2.RoleTypeAI.ToConvert() {
			if dialogue != nil {
				dialogue.Answer = chatMessage.ToDialogRecord()
				historyDialogue = append(historyDialogue, dialogue)
			}
		}
	}

	return historyDialogue
}

func (k *SimChatHandler) buildGraphContext(ctx *rest.Context, req model.OpenApiConvReq) (bizRequestContext *entities.RequestContext, answerMessageId string) {
	sourceDomain := ctx.Request.Header.Get("Source-Domain")

	var memberId int64
	if k.fromWangAn {
		if mbznHeader == sourceDomain {
			memberId = 40
		} else {
			memberId = 30
		}
	} else {
		if mbznHeader == sourceDomain {
			memberId = 20
		} else {
			memberId = 10
		}
	}

	questionMessageId := uuid.New().String()
	answerMessageId = uuid.New().String()
	conversionId := uuid.New().String()

	bizRequestContext = entities.NewRequestContextForZhihaitu(
		&proto.ChatRequest{
			Info: &proto.RequestInfo{
				SessionId: conversionId,
				Message: &proto.ChatMessage{
					MessageId:   questionMessageId,
					TimestampMs: util.TimeUnixMilli(),
					Type:        proto.ChatMessageType_TEXT,
					Text:        req.Dialogue[len(req.Dialogue)-1].Content,
				},
				MemberId: memberId,
			},
			RespMessageId: answerMessageId,
		},
		"",
		buildOpenApiHistoryDialogue(req.Dialogue), graph_constant.ApiZhihaituChat, zhihaitu_graph.ApiBizTypePostfix, zhihaitu_api_conf.LogicBizConfigMap)

	return bizRequestContext, answerMessageId
}

func (k *SimChatHandler) Post(ctx *rest.Context) (rest.Response, error) {
	req := model.OpenApiConvReq{}
	err := ctx.JSONArgs(&req)
	if err != nil {
		return nil, err
	}

	authorization := ctx.Request.Header.Get("Authorization")
	if authorization != openApiAuthorization {
		return model.OpenApiConvResp{Status: "failed", Reason: "Authorization 鉴权失败"}, nil
	}

	if req.Model != openApiModelName {
		return model.OpenApiConvResp{Status: "failed", Reason: "model参数校验失败"}, nil
	}

	if len(req.Dialogue) == 0 {
		return model.OpenApiConvResp{Status: "failed", Reason: "参数校验失败"}, nil
	}

	bizRequestContext, answerMessageId := k.buildGraphContext(ctx, req)
	_, response, _, err := graph.RunGraph(ctx, bizRequestContext, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
		ip := ctx.Request.Header.Get("x-envoy-external-address")
		if ip == "" {
			ip = ctx.Request.Header.Get("X-Forwarded-For")
		}
		if ip != "" {
			ip = util.GetFirstIp(ip)
		}

		apiSource := ""
		if k.fromWangAn {
			apiSource = "api_wangan"
		} else {
			apiSource = "api_wangxin"
		}
		requestContext.DataMap().SetString(ctx, macro.ZagKeyIp, ip)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyUserAgent, ctx.Request.Header.Get("User-Agent"))
		requestContext.DataMap().SetString(ctx, macro.ZagKeyZhihaituApiSource, apiSource)
		requestContext.DataMap().SetObjMap(ctx, macro.ZagKeyQuery, bizRequestContext.GetCurrentDialogue().Query)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryText, req.Dialogue[len(req.Dialogue)-1].Content)
		requestContext.DataMap().SetString(ctx, macro.ZagKeyRespMessageId, answerMessageId)

		return nil
	})

	chatResponse := response.(*proto.ChatResponse)
	if chatResponse == nil {
		return model.OpenApiConvResp{Status: "failed", Reason: "内部服务异常", Content: "服务繁忙，请稍后重试"}, nil
	} else {
		return model.OpenApiConvResp{
			Status:  "success",
			Reason:  "success",
			Content: chatResponse.Message.Text,
		}, nil
	}
}
