package mapping

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

// MultiChatSummaryLogic 多轮对话生成 summary
type MultiChatSummaryLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
	klaraService klara_model.KlaraModelService
	maxCount     int
}

func NewMultiChatSummaryLogic(name string, config map[string]string) *MultiChatSummaryLogic {
	res := &MultiChatSummaryLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.klaraService = klara_model.NewKlaraModelServiceImpl()
	res.maxCount = 8
	res.MappingFunc = res.realMapping
	return res
}

func (s *MultiChatSummaryLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "mapping.MultiChatSummaryLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	var result []*data_frame.ItemData[entities.Item]

	// 当前场景只针对历史会话生成 summary，不用当前 query 或 queryMerge 的结果
	dialogueHist := requestCtx.GetBizContext().GetHistoryDialogue()
	// 获取最近的 maxCount 条
	dialogueHist = dialogueHist[util2.Max(0, len(dialogueHist)-s.maxCount):]

	summary, err := s.klaraService.MultiChatSummary(ctx, dialogueHist)

	log.Debugf(ctx, "gen multi chat summary:%s", summary)

	if err != nil {
		return result, err
	}

	item := entities.ItemWithTextAndType(summary, entities.ChatMappingTypeSummary)
	item.ChatRespType = proto.ChatRespType_TASK
	result = append(result, item.IntoFrameItem(requestCtx))

	s.saveTracing(dialogueHist, summary, startTime, requestCtx)

	return result, nil

}

func (s *MultiChatSummaryLogic) saveTracing(historyDialogue []*message.DialogueWrapper, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(historyDialogue)},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)
}
