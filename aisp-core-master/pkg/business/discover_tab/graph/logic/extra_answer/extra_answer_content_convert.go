package extra_answer

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: liubingbing
// @logicInfo: 相关追问跳转直答，message 拼接 QA 作为历史对话

// ExtraAnswerContentCovertLogic 相关追问跳转直答，message 拼接 QA 作为历史对话
type ExtraAnswerContentCovertLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	allowDocTypes []proto.DocType
	maxLen        int
	contentClient rpc.ContentCoreRPC
}

func NewExtraAnswerContentCovertLogic(name string, config map[string]string) *ExtraAnswerContentCovertLogic {
	res := &ExtraAnswerContentCovertLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.doHandle
	res.maxLen = 256
	res.allowDocTypes = []proto.DocType{proto.DocType_ANSWER}
	res.contentClient = impl.NewContentCoreRPCImpl()
	return res
}

func (l *ExtraAnswerContentCovertLogic) doHandle(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	isEnable := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.IsEnableLogic))
	if !isEnable {
		return items, nil
	}

	resp := make([]*data_frame.ItemData[entities.Item], 0)
	startTime := time.Now().UnixMilli()
	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, l.GetName(), "ExtraAnswerContentCovertLogic.doHandle")
	defer logic_context.DeferContext(span, l.GetName(), requestCtx, &resp)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(resp))
	logger := log.WithFields(ctx, map[string]any{
		"func": "ExtraAnswerContentCovertLogic.doHandle",
	})
	logger.Debugf(ctx, "do running")

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", l.GetName())
		return items, nil
	}

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	// 非法过滤
	if requestCtx.GetBizContext().GetChatExtraInfo() == nil ||
		requestCtx.GetBizContext().GetChatExtraInfo().GetSourceContent().GetDocId() <= 0 ||
		!lo.Contains(l.allowDocTypes, requestCtx.GetBizContext().GetChatExtraInfo().GetSourceContent().GetDocType()) {
		return items, nil
	}

	// 召回的内容需要根据业务需求进行过滤
	questionTitle := ""
	answerContent := ""
	sourceContent := requestCtx.GetBizContext().GetChatExtraInfo().GetSourceContent()
	modelContent := model.NewContentWithDocType(sourceContent.GetDocId(), aiContent.DocType_Answer)
	contentInfoMap := l.contentClient.BatchGetContent(ctx, []model.Content{modelContent},
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody)
	contentInfo, contentInfoIsOk := contentInfoMap[modelContent]
	if contentInfoIsOk && contentInfo.GetOutID() != "" && contentInfo.GetContentBody() != nil {
		// 过滤html标签
		body := contentInfo.GetContentBody().GetBody()
		filteredBody, err := util.ContentHtml2Markdown(ctx, body)
		if err == nil && filteredBody != "" {
			answerContent = filteredBody
			// 超过最大长度后截取 最大保留 256 长度，截断后拼接字符串"..."
			if util.UnicodeLen(answerContent) > l.maxLen {
				answerContent = util.UnicodeSubstr(answerContent, 0, l.maxLen) + "..."
			}
		}

		// 查询answer 对应 question 的标题
		if contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
			contentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
			parentContentId := contentInfo.GetExtInfo().GetParentInfo().ContentID
			parentContentResultMap := l.contentClient.BatchGetContentByContentID(ctx, []string{parentContentId}, base.ContentInfoFieldContentTitle)
			parentContentInfo, parentContentInfoIsOk := parentContentResultMap[parentContentId]
			if parentContentInfoIsOk && parentContentInfo.GetOutID() != "" && parentContentInfo.GetTitle() != "" {
				questionTitle = parentContentInfo.GetTitle()
			}
		}
	}

	// 2. 当前 item 内容拼接QA对到对话历史
	// message 里塞QA对
	extraQuery := entities.NewQueryDialogFormQuery(requestCtx.GetBizContext().RequestInfo(), requestCtx.GetBizContext().GetBizType())
	extraQueryMessage := message.TextMessage{Content: questionTitle}
	extraQuery.MessageContent = extraQueryMessage.Content
	extraQuery.CreateType = model.DialogCreateTypeTmp.ToConvert()
	extraAnswer := entities.NewAnswerDialogFormProtoChatRequest(requestCtx.GetBizContext(), answerContent, model.DialogCreateTypeTmp, model.DialogErrorTypeNormal)
	dialogues := requestCtx.GetBizContext().GetHistoryDialogue()
	dialogues = append(dialogues, &message.DialogueWrapper{Query: extraQuery, Answer: extraAnswer})
	requestCtx.GetBizContext().SetHistoryDialogue(dialogues)

	// 3. 对于当前 items 里的 召回内容删除, 并对于当前用户的query 做处理 questionTitle+原始query
	// 修改图流程中用户原始Query内容，用于召回，但不修改上下文中原始query（保留一份最原始的query用于模型生成）
	queryItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeQuery
	})
	if queryItems != nil && len(queryItems) > 0 {
		queryItems[0].GetBizItem().Text = fmt.Sprintf("%s %s", questionTitle, queryItems[0].GetBizItem().Text)
	}

	resp = append(resp, items...)
	l.saveTracing(logCtx, fmt.Sprintf("questionTitle: %s, answerContent:%s", questionTitle, answerContent), util.GetJSONIgnoreError(resp), startTime, requestCtx)

	return resp, nil
}

func (l *ExtraAnswerContentCovertLogic) saveTracing(logCtx context.Context, request string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   l.GetName(),
		LogicInput:  []string{request},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(l.GetName(), logicTracing)
	constant.DataInputNodeLog.Infof(logCtx, "%v", request)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)
}
