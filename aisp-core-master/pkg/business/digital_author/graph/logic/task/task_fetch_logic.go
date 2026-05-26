package task

import (
	"context"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

const taskFmt = "任务%d"
const isTaskSelected = "是"

type TaskFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, int64]
	klaraService klara_model.KlaraModelService
	maxCount     int
}

func NewTaskFetcherLogic(name string, config map[string]string) *TaskFetcherLogic {
	res := &TaskFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, int64](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.maxCount = 8
	res.klaraService = klara_model.NewKlaraModelServiceImpl()
	return res
}

func (t *TaskFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]int64, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "fetch.TaskFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()

	resMap := make(map[data_frame.UniqueId]int64)

	// 此处只处理 query merge 之后的 task 命中情况，因此 items 的长度应该为 1
	if len(items) != 1 {
		log.Errorf(ctx, "task fetcher logic itemList size is %d not 1", len(items))
		return resMap, nil
	}

	var queryList []string
	var taskList []string

	tasks := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).Task()
	// 用户没有配置 task，直接返回
	if len(tasks) == 0 {
		return resMap, nil
	}

	// 拼接历史 query + 当前query
	for _, v := range requestCtx.GetBizContext().GetHistoryDialogue() {
		// 过滤非 text 类型的 query
		if int64(proto.ChatMessageType_TEXT) != v.Query.MessageType {
			continue
		}
		queryList = append(queryList, v.Query.MessageContent)
	}
	queryList = queryList[util2.Max(0, len(queryList)-t.maxCount):]
	queryList = append(queryList, requestCtx.GetBizContext().RequestMessage().GetText())

	// 拼接 task 内容和 task 映射表
	taskMap := map[string]*proto.TaskInfo{}
	for idx, taskInfo := range tasks {
		taskList = append(taskList, taskInfo.Description)
		taskMap[fmt.Sprintf(taskFmt, idx+1)] = taskInfo
	}

	taskResult, err := t.klaraService.TaskJudge(ctx, queryList, taskList)
	if err != nil {
		return resMap, nil
	}

	for k, v := range taskResult {
		if strings.EqualFold(v, isTaskSelected) {
			if taskInfo, exist := taskMap[k]; exist {
				resMap[*data_frame.NewUniqueId(items[0].GetCommonItem().Id())] = taskInfo.GetId()
			}
		}
	}
	t.saveTracing(queryList, taskList, taskResult, startTime, requestCtx)

	return resMap, nil
}

func (t *TaskFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res int64) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "fetch.TaskFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().HitTaskId = res
	return nil
}

func (t *TaskFetcherLogic) saveTracing(queryList []string, taskList []string, response map[string]string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   t.GetName(),
		LogicInput:  append(queryList, taskList...),
		LogicOutput: []string{util.GetJSONIgnoreError(response)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(t.GetName(), logicTracing)
}
