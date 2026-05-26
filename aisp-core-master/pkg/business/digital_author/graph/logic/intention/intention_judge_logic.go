package intention

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type IntentionJudgeLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewIntentionJudgeLogic(name string, config map[string]string) *IntentionJudgeLogic {
	res := &IntentionJudgeLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (i *IntentionJudgeLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "intention.IntentionJudgeLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(itemList))

	startTime := time.Now().UnixMilli()
	if len(itemList) != 1 {
		log.Errorf(ctx, "intention judge logic itemList size is %d not 1", len(itemList))
		return itemList, nil
	}

	// 取当前 item，即英文 moe 的结果
	item := itemList[0]
	intentionText := strings.TrimSpace(item.GetBizItem().Text)
	span.LogFields(log.Message("IntentionJudgeLogic"), log.String("intentionText", intentionText), log.String("respMessageId", requestCtx.GetBizContext().RespMessageId()))

	// 意图识别的结果
	var intentionType proto.IntentionType
	switch intentionText {
	case "有搜索意图":
		intentionType = proto.IntentionType_SEARCH_INTENTION
	case "无搜索意图":
		intentionType = proto.IntentionType_NO_SEARCH_INTENTION
	case "意图不明确":
		intentionType = proto.IntentionType_AMBIGUOUS
	default:
		intentionType = proto.IntentionType_AMBIGUOUS
	}

	log.WithField(ctx, "respMessageId", requestCtx.GetBizContext().RespMessageId()).Infof(ctx, "intention judge result:%d", intentionType)
	// 记录意图识别的结果到 context
	requestCtx.GetBizContext().SetIntention(&proto.Intention{
		IntentionType: intentionType,
	})

	// 新
	util.Increment(ctx, macro.CommonStatsPrefix+".%s.%s.count", requestCtx.GetBizContext().Scenes(), "intention", intentionType.String())
	// 老
	statsd.Increment(fmt.Sprintf(macro.OriginCommonStatsPrefix+".%s.%s.count", requestCtx.GetBizContext().Scenes(), "intention", intentionType.String()))
	i.saveTracing(fmt.Sprintf("%s,%s,", item.GetBizItem().Text, intentionText), intentionType.String(), startTime, requestCtx)
	return []*data_frame.ItemData[entities.Item]{requestCtx.GetBizContext().GetQueryMerge().IntoFrameItem(requestCtx)}, nil
}

func (i *IntentionJudgeLogic) saveTracing(input string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   i.GetName(),
		LogicInput:  []string{input},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(i.GetName(), logicTracing)
}

func (i *IntentionJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "intention.IntentionJudgeLogic.chooseKey")
	defer span.Finish()

	switch param.RequestContext.GetBizContext().GetIntention().GetIntentionType() {
	case proto.IntentionType_SEARCH_INTENTION:
		return proto.IntentionType_SEARCH_INTENTION.String()
	case proto.IntentionType_NO_SEARCH_INTENTION:
		return proto.IntentionType_NO_SEARCH_INTENTION.String()
	default:
		return proto.IntentionType_AMBIGUOUS.String()
	}
}
