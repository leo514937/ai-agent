package intention

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type Task2SummaryJudgeLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewTask2SummaryJudgeLogic(name string, config map[string]string) *Task2SummaryJudgeLogic {
	res := &Task2SummaryJudgeLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (i *Task2SummaryJudgeLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "intention.Task2SummaryJudgeLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(itemList))

	if len(itemList) != 1 {
		log.Errorf(ctx, "intention judge logic itemList size is %d not 1", len(itemList))
		return itemList, nil
	}

	// 取当前 item，即 queryMerge 的 item
	item := itemList[0]

	taskId := item.GetBizItem().GetItemMeta().HitTaskId

	// 根据 taskId，从数字分身任务重找到其任务目标
	var taskInfo *proto.TaskInfo
	if taskId != 0 {
		tasks := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).Task()
		for _, task := range tasks {
			if task.GetId() == taskId {
				taskInfo = task
				break
			}
		}
	}

	// 任务目标留资卡，则需要生成summary
	needSummary := taskInfo.GetGoal() == proto.TaskGoal_TEL_NUMBER

	log.WithField(ctx, "respMessageId", requestCtx.GetBizContext().RespMessageId()).Infof(ctx, "need summary result:%v, task:%s", needSummary, util.GetJSONIgnoreError(taskInfo))

	requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).SetHitTask(taskInfo)
	requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).SetNeedSummary(needSummary)

	return itemList, nil
}

func (i *Task2SummaryJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "intention.Task2SummaryJudgeLogic.chooseKey")
	defer span.Finish()

	if param.RequestContext.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).NeedSummary() {
		return entities.NeedSummary
	}
	return ""
}
