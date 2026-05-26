package root

import (
	"context"
	"fmt"
	"sort"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	dialogService "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_record"
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

// @logicAuthor: zhoupengcheng
// @logicInfo: 获取对话历史记录
// @logicOutput: 0 | 对话历史记录。[]*message.DialogueWrapper
type ChatHistoryLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*message.DialogueWrapper]
	dialogRecordService dialogService.DialogService
	limitRecords        uint64
}

func NewChatHistoryLogic(name string, config map[string]string) *ChatHistoryLogic {
	res := &ChatHistoryLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*message.DialogueWrapper](name, config),
	}
	res.dialogRecordService = dialogService.NewDefaultDialogService()
	res.limitRecords = 50
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

func (c *ChatHistoryLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) ([]*message.DialogueWrapper, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.ChatHistoryLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	log.Infof(ctx, "ChatHistoryLogic realFillUser user: %+v", user)

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ChatHistorySkip.ToConvert()))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", c.GetName())
		return []*message.DialogueWrapper{}, nil
	}

	// 根据 sessionId 获取会话历史
	sessionId := cast.ToInt64(requestCtx.GetBizContext().GetSessionId())

	currMessageId := requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageId

	dialogList, err := c.dialogRecordService.GetDialogListBySessionId(
		ctx, sessionId, c.limitRecords)
	if err != nil || dialogList == nil {
		dialogList = []*model.DialogRecord{}
	}

	groupDialog := lo.GroupBy(dialogList, func(item *model.DialogRecord) string {
		if item.ParentMessageId != "" {
			return item.ParentMessageId
		}
		return item.MessageId
	})

	var historySlice [][]*model.DialogRecord
	for k, v := range groupDialog {
		// 如果当前messageId 等于 分组key，则表示为重答，不作为对话历史上下文数据
		if k == currMessageId {
			if len(v) > 0 {
				util.Timing(ctx, macro.CommonStatsPrefix+".re_answer_period", time.Since(v[0].RecordAt))
			}
			continue
		}
		historySlice = append(historySlice, v)
	}

	// 排序 并且转换为  tuple
	dialogTuples := lo.Map(historySlice, func(items []*model.DialogRecord, _ int) lo.Tuple2[int64, *message.DialogueWrapper] {
		res := lo.Tuple2[int64, *message.DialogueWrapper]{}
		wrapper := message.DialogueWrapper{}
		for _, item := range items {
			switch item.RoleType {
			case model.RoleTypeUser.ToConvert():
				wrapper.Query = item
				if res.A == 0 {
					res.A = item.RecordAt.UnixMilli()
				}
			case model.RoleTypeAI.ToConvert():
				// 过滤掉 cite、think 标签内容
				item.MessageContent = util.RemoveTags(item.MessageContent)
				wrapper.Answer = item
				res.A = item.RecordAt.UnixMilli()
			default:
				continue
			}
		}

		if wrapper.Query == nil {
			wrapper.Query = &model.DialogRecord{}
		}
		if wrapper.Answer == nil {
			wrapper.Answer = &model.DialogRecord{}
		}
		res.B = &wrapper
		return res
	})
	// 按照时间 正排
	sort.Slice(dialogTuples, func(i, j int) bool {
		return dialogTuples[i].A < dialogTuples[j].A
	})
	wrappers := lo.Map(dialogTuples, func(item lo.Tuple2[int64, *message.DialogueWrapper], index int) *message.DialogueWrapper {
		return item.B
	})

	// 按照 安全在 24.1.19 指出，在安全检测发生异常行为时, 需要禁止多轮对话
	// 先去找到有效历史消息游标 并进行裁切
	var startIndex int
	for i := len(wrappers) - 1; i >= 0; i-- {
		if isSecurityUnPassed(wrappers[i].Query) || isSecurityUnPassed(wrappers[i].Answer) {
			startIndex = i + 1
			break
		}
	}
	wrappersRes := wrappers[startIndex:]

	constant.DataInputNodeLog.Infof(logCtx, "sessionId:%d", sessionId)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(wrappersRes))
	c.saveTracing(sessionId, wrappersRes, startTime, requestCtx)
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".%s.length", float64(len(wrappersRes)), "history")
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".%s.length", requestCtx.GetBizContext().Scenes(), "history"), float64(len(wrappersRes)))
	requestCtx.DataMap().SetObjMap(logCtx, c.GetOutputName(0), wrappersRes)
	return wrappersRes, nil
}

func (c *ChatHistoryLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], wrappersRes []*message.DialogueWrapper) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.ChatHistoryLogic.realMergeUser")
	defer span.Finish()

	requestCtx.GetBizContext().SetHistoryDialogue(wrappersRes)
	return nil
}

func isSecurityUnPassed(dialog *model.DialogRecord) bool {
	if dialog.ErrorType == model.DialogErrorTypeSecurityRejection.ToConvert() ||
		dialog.ErrorType == model.DialogErrorTypeSecurityCover.ToConvert() ||
		dialog.ErrorType == model.DialogErrorTypeRedLine.ToConvert() {
		return true
	}
	return false
}

func (c *ChatHistoryLogic) saveTracing(session int64, historyDialogue []*message.DialogueWrapper, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	var outputStr []string
	for _, hist := range historyDialogue {
		outputStr = append(outputStr, util.GetJSONIgnoreError(hist))
	}
	logicTracing := &proto.LogicTracing{
		LogicName:   c.GetName(),
		LogicInput:  []string{fmt.Sprintf("session: %d, limit: %d", session, c.limitRecords)},
		LogicOutput: []string{fmt.Sprintf("relCount: %d", len(outputStr))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(c.GetName(), logicTracing)
}
