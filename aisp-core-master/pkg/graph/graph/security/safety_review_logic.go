package security

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/spf13/cast"
)

const historyMaxLength = 10

// SecurityReviewLogic
// @logicAuthor: wanghao11
// @logicInfo: 安全审核逻辑
// @logicOutput: 0 | 安全review结果，bool
type SecurityReviewLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]

	FetchFunc     func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*model.ReviewResult, error)
	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error
}

func NewSecurityReviewLogic(name string, config map[string]string) *SecurityReviewLogic {
	l := &SecurityReviewLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	l.MappingFunc = l.fetchA
	l.BizNodeType = "fetch"

	l.FetchFunc = l.fetch
	l.ItemMergeFunc = l.itemMerge

	return l
}

func (u *SecurityReviewLogic) getSecurityConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.SecurityConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "SecurityReviewLogic getConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), u.GetName()))
		return conf.SecurityConfig{}
	}

	securityConfig := conf.SecurityConfig{}
	err := json.Unmarshal([]byte(configStr), &securityConfig)
	if err != nil {
		log.Errorf(ctx, "SecurityReviewLogic getConfig error => config unmarshal error, config: %s, err: %+v", configStr, err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), u.GetName()))
		return conf.SecurityConfig{}
	}
	return securityConfig
}

func (u *SecurityReviewLogic) fetchA(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	var resMap map[data_frame.UniqueId]*model.ReviewResult
	var err error

	err = safe_group.SafeGoWait(u.OriginName(), func() error {
		resMap, err = u.FetchFunc(ctx, requestCtx, user, itemList)
		return err
	})

	if err != nil {
		log.Errorf(ctx, "CommonContext: %+v, BizNodeType: %+v, BizNodeType: %+v, err: %+v", requestCtx.GetCommonContext(), u.GetBizNodeType(), u.OriginName(), err)
		return itemList, nil
	}

	for _, item := range itemList {
		uniqueKey := *item.GetCommonItem().GetUniqueId()
		log.Infof(ctx, "%s get uniqueKey:%s", u.GetName(), util.GetJSONIgnoreError(uniqueKey))
		if res, ok := resMap[uniqueKey]; ok {
			_ = u.ItemMergeFunc(ctx, item, res)
		}
	}

	return itemList, nil
}

func (u *SecurityReviewLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*model.ReviewResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.SecurityReviewLogic.fetch")
	defer span.Finish()

	securityConfig := u.getSecurityConfig(ctx, requestCtx)
	sourceId := rpc.RiskCheckSourceId(securityConfig.SourceId)
	chatMappingType := entities.ChatMappingType(securityConfig.ChatMappingType)
	scene := securityConfig.Scene
	storeSource := securityConfig.StoreSource
	extraStoreSource := securityConfig.ExtraStoreSource
	setRedLineAnswer := securityConfig.SetRedLineAnswer

	if scene == "" {
		scene = requestCtx.GetBizContext().GetBizType()
		securityConfig.Scene = scene
	}

	startTime := time.Now().UnixMilli()

	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	span.LogFields(log.Message("SecurityReviewLogic fetch start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*model.ReviewResult)
	log.Infof(ctx, "security review, sourceId:%v scene:%v  items: %s", sourceId, scene, util.GetJSONIgnoreError(items))

	reviewResult := &model.ReviewResult{
		IsAvailable: true,
		RequestInfo: "豁免安全",
	}

	// 不豁免安全，正常执行安全接口调用
	if !requestCtx.GetBizContext().GetIsExemptSecurity() {
		reviewResult = CheckItem(ctx, requestCtx, items, sourceId, scene, chatMappingType, storeSource, extraStoreSource, setRedLineAnswer, false, "")
	}

	log.StatsdCheckItem(ctx, "SecurityReviewLogic.fetch.all", reviewResult.IsAvailable)
	log.StatsdCheckItem(ctx, "SecurityReviewLogic.fetch."+cast.ToString(sourceId), reviewResult.IsAvailable)

	requestCtx.DataMap().SetBool(logCtx, u.GetOutputName(0), reviewResult.IsAvailable)

	for _, item := range items {
		uniqueKey := *data_frame.NewUniqueId(item.GetCommonItem().Id())
		log.Infof(ctx, "security review %s set uniqueKey:%s, value:%s", u.GetName(), util.GetJSONIgnoreError(uniqueKey), util.GetJSONIgnoreError(reviewResult))
		resMap[uniqueKey] = reviewResult
	}

	span.LogFields(log.Message("SecurityReviewLogic fetch done."), log.Json("resp", resMap))

	u.saveLogicTracing(logCtx, securityConfig, reviewResult, startTime, requestCtx)

	return resMap, nil
}

func (u *SecurityReviewLogic) saveLogicTracing(logCtx context.Context, securityConfig conf.SecurityConfig, reviewResult *model.ReviewResult, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
) {
	logicTracing := &proto.LogicTracing{
		LogicName:   u.GetName(),
		LogicInput:  []string{fmt.Sprintf("securityConfig:%s, requestInfo:%s", util.GetJSONIgnoreError(securityConfig), reviewResult.RequestInfo)},
		LogicOutput: []string{fmt.Sprintf("isAvailable:%v, FailReason:%s, responseInfo:%s", reviewResult.IsAvailable, reviewResult.FailReason, reviewResult.ResponseInfo)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(u.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "securityConfig:%s, requestInfo:%s", util.GetJSONIgnoreError(securityConfig), reviewResult.RequestInfo)
	constant.DataOutputNodeLog.Infof(logCtx, "isAvailable:%v, FailReason:%s,  responseInfo:%s", reviewResult.IsAvailable, reviewResult.FailReason, reviewResult.ResponseInfo)
}

func (u *SecurityReviewLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.SecurityReviewLogic.itemMerge")
	defer span.Finish()

	macro.ProcessNodeLog.Infof(ctx, "item:%s, ReviewResult:%s, IsSecurityPassed:%s", item.GetBizItem().Text, util.GetJSONIgnoreError(res), res.IsAvailable)
	// log.Infof(ctx, "before set. item:%s, ReviewResult:%s, IsSecurityPassed:%s", item.GetBizItem().Text, util.GetJSONIgnoreError(res), res.IsAvailable)

	item.GetBizItem().GetSecurity().ReviewResult = res

	log.Infof(ctx, "after set. item:%s, ReviewResult:%s", item.GetBizItem().Text, util.GetJSONIgnoreError(item.GetBizItem().GetSecurity()))
	return nil
}

// CheckItem 后续改为数据依赖的话，不应该在非interface方法中传入RequestContext。CheckItem应该改为interface的方法
func CheckItem(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	items []*data_frame.ItemData[entities.Item],
	sourceId rpc.RiskCheckSourceId, scene string, chatMappingType entities.ChatMappingType, storeSource conf.LogicStoreKey,
	extraStoreSource conf.LogicStoreKey, setRedLineAnswer bool, isStreaming bool, answerType string) *model.ReviewResult {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.CheckItem.func")
	defer span.Finish()

	var dialogs = BuildDialogRecords(storeSource, extraStoreSource, requestCtx, items)

	params := &rpc.RiskCheckParams{
		Contents:       message.NewDialogueWrapperArr(&dialogs).ToConvertRiskCheckContents(),
		MemberId:       requestCtx.GetBizContext().MemberId(),
		SourceId:       sourceId,
		Scene:          scene,
		ClientSource:   requestCtx.GetBizContext().GetClientSource().String(),
		TrafficSource:  requestCtx.GetBizContext().GetTrafficSource().String(),
		DataSourceType: requestCtx.GetBizContext().GetZhiDaProSourceType().String(),
	}

	dataSourceType := requestCtx.GetBizContext().GetZhiDaProSourceType().String()
	if dataSourceType != "" && requestCtx.GetBizContext().GetSecurityZhiDaProSourceType() != "" {
		dataSourceType += fmt.Sprintf(".%s", requestCtx.GetBizContext().GetSecurityZhiDaProSourceType())
	}
	params.DataSourceType = dataSourceType
	params.ChatModel = requestCtx.GetBizContext().GetCustomChatModel().String()
	if chatMappingType == entities.ChatMappingTypeQueryMerge {
		params.QueryExtra = &risk_check.QuestionInfo{
			QuestionType: thrift.StringPtr(rpc.RiskCheckQuestionTypeAlgo.ToConvert()),
		}
	} else if chatMappingType == entities.ChatMappingTypeQuery {
		params.QueryExtra = &risk_check.QuestionInfo{
			QuestionType: thrift.StringPtr(rpc.RiskCheckQuestionTypeUser.ToConvert()),
		}
	} else if chatMappingType == entities.ChatMappingTypeLLMAnswer {
		params.AnswerExtra = rpc.NewRiskAnswerInfo()

		if isStreaming {
			params.AnswerExtra.IsLast = thrift.BoolPtr(false)
		}

		if answerType != "" {
			params.AnswerExtra.AnswerType = thrift.StringPtr(answerType)
		}
	}

	if setRedLineAnswer {
		if params.AnswerExtra == nil {
			params.AnswerExtra = rpc.NewRiskAnswerInfo()
		}
		params.AnswerExtra.IsFixedAnswer = thrift.BoolPtr(true)
	}
	ip, _ := requestCtx.DataMap().GetString(logCtx, graph_macro.ZagKeyIp)
	if ip != "" {
		params.IP = ip
	}
	userAgent, _ := requestCtx.DataMap().GetString(logCtx, graph_macro.ZagKeyUserAgent)
	if userAgent != "" {
		params.UserAgent = userAgent
	}

	resp, err := impl.DefaultRiskCheckRPCImpl.RiskCheckDialog(ctx, params)

	if err != nil {
		log.Errorf(ctx, "security review, err: %+v", err)

		return &model.ReviewResult{
			IsAvailable:  false,
			FailReason:   "服务异常",
			RequestInfo:  util.GetJSONIgnoreError(params),
			ResponseInfo: util.GetJSONIgnoreError(resp),
		}
	}

	if resp.Res != 1 {
		log.Infof(ctx, "Security review failed. request:%s response:%s", util.GetJSONIgnoreError(params), util.GetJSONIgnoreError(resp))
	}

	reviewResult := &model.ReviewResult{
		IsAvailable:  resp.Res == 1, // 1是通过
		FailReason:   cast.ToString(resp.Res.ToConvert()),
		RequestInfo:  util.GetJSONIgnoreError(params),
		ResponseInfo: util.GetJSONIgnoreError(resp),
	}

	return reviewResult
}

func BuildDialogRecords(
	storeSource conf.LogicStoreKey,
	extraStoreSource conf.LogicStoreKey,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	items []*data_frame.ItemData[entities.Item]) []*message.DialogueWrapper {

	// 如果配置了 取原始数据 则尝试去取原始数据，如果取不到则用当前的item 总是送安全绝对不能为空
	if strings.TrimSpace(storeSource.String()) != "" {
		sourceQueryItems, isOk := requestCtx.GetCommonContext().GetLogicData(storeSource.String()).([]*data_frame.ItemData[entities.Item])
		if isOk && sourceQueryItems != nil && len(sourceQueryItems) > 0 {
			items = sourceQueryItems
		}
	}

	// 如果配置了额外拼接原始数据，则拼接在 items 前，用于 llm answer 拼接输入 query
	if strings.TrimSpace(extraStoreSource.String()) != "" {
		sourceQueryItems, isOk := requestCtx.GetCommonContext().GetLogicData(extraStoreSource.String()).([]*data_frame.ItemData[entities.Item])
		if isOk && sourceQueryItems != nil && len(sourceQueryItems) > 0 {
			items = append(sourceQueryItems, items...)
		}
	}

	// 获取会话历史，并截断最长轮数
	var dialogRecords = requestCtx.GetBizContext().GetHistoryDialogue()
	dialogRecords = dialogRecords[util2.Max(0, len(dialogRecords)-historyMaxLength):]

	dialogue := message.DialogueWrapper{}
	for _, item := range items {
		texts := make([]string, 0)
		// 排除异常 空字符串内容调用安全接口（空内容调用安全接口会报错）
		texts = append(texts, util.RemoveTags(item.GetBizItem().Think))
		texts = append(texts, util.RemoveTags(item.GetBizItem().Text))
		textContent := strings.Join(texts, "\n")
		if textContent == "" {
			continue
		}

		record := &model.DialogRecord{
			MemberId:        requestCtx.GetBizContext().MemberId(),
			AiId:            0,
			MessageId:       cast.ToString(item.GetBizItem().MessageId),
			ConversationId:  cast.ToString(requestCtx.GetBizContext().GetSessionId()),
			Scene:           requestCtx.GetBizContext().GetBizType(),
			MessageType:     int64(item.GetBizItem().Type),
			MessageContent:  textContent,
			ParentMessageId: "",
			RecordAt:        time.Now(),
			ErrorType:       model.DialogErrorTypeNormal.ToConvert(),
			SessionId:       requestCtx.GetBizContext().GetSessionId(),
		}

		switch item.GetBizItem().ChatTextTurnoverType {
		case entities.ChatMappingTypeLLMAnswer:
			record.RoleType = model.RoleTypeAI.ToConvert()
			record.CreateType = model.DialogCreateTypeLLM.ToConvert()
			dialogue.Answer = record
		default:
			record.RoleType = model.RoleTypeUser.ToConvert()
			record.CreateType = model.DialogCreateTypeInput.ToConvert()
			if dialogue.Query != nil {
				record.MessageContent = dialogue.Query.MessageContent + "," + record.MessageContent
			}
			dialogue.Query = record
		}
	}
	dialogRecords = append(dialogRecords, &dialogue)
	return dialogRecords
}
