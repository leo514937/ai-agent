package security

import (
	"context"
	"fmt"
	"sync"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 词安审逻辑
type SecurityReviewWordLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *model.ReviewResult]
	riskClient rpc.RiskCheckRPC
}

func NewSecurityReviewWordLogic(name string, config map[string]string) *SecurityReviewWordLogic {
	res := &SecurityReviewWordLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *model.ReviewResult](name, config),
	}

	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge

	res.riskClient = rpcImpl.NewRiskCheckRPCImpl()

	return res
}

func (s *SecurityReviewWordLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*model.ReviewResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.SecurityReviewWordLogic.fetch")

	startTime := time.Now().UnixMilli()

	riskSource := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.RiskConfigWordSource.ToConvert())

	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*model.ReviewResult)
	var resultMap sync.Map

	group := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", s.GetName(), "riskCheckInterestWord"), 3000).SetLimit(10)
	for _, item := range items {
		item := item
		group.Go(func() error {
			res, rErr := s.riskClient.RiskCheckInterestWord(ctx, item.GetBizItem().Text, riskSource)
			if rErr != nil || res == nil {
				return rErr
			}

			reviewResult := &model.ReviewResult{}
			reviewResult.IsAvailable = res.Res == rpc.RiskCheckResPass
			reviewResult.FailReason = cast.ToString(res.Res.ToConvert())
			reviewResult.RequestInfo = fmt.Sprintf("%s, soruce:%s", item.GetBizItem().Text, riskSource)
			reviewResult.ResponseInfo = util.GetJSONIgnoreError(res)

			log.StatsdCheckItem(ctx, "SecurityReviewWordLogic.fetch.all", reviewResult.IsAvailable)

			resultMap.Store(item, reviewResult)
			return nil
		})
	}
	_ = group.Wait()

	var reviewResults []*model.ReviewResult
	resultMap.Range(func(key, value interface{}) bool {
		item, _ := key.(*data_frame.ItemData[entities.Item])
		reviewResult, _ := value.(*model.ReviewResult)
		reviewResults = append(reviewResults, reviewResult)
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = reviewResult
		return true
	})

	s.saveLogicTracing(logCtx, reviewResults, startTime, requestCtx)

	return resMap, nil
}

func (s *SecurityReviewWordLogic) saveLogicTracing(logCtx context.Context, reviewResults []*model.ReviewResult, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
) {
	var input []string
	var output []string

	for _, reviewResult := range reviewResults {
		input = append(input, reviewResult.RequestInfo)
		output = append(output, reviewResult.ResponseInfo)
	}

	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  input,
		LogicOutput: output,
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%s", input)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", output)

}

func (s *SecurityReviewWordLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.SecurityReviewWordLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetSecurity().ReviewResult = res
	return nil
}
