package security

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 站外召回内容标题摘要安审逻辑
type SecurityReviewRecallLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *model.ReviewResult]
	riskClient        rpc.RiskCheckRPC
	fullContentMaxLen int
	abstractMaxLen    int
}

func NewSecurityReviewRecallLogic(name string, config map[string]string) *SecurityReviewRecallLogic {
	res := &SecurityReviewRecallLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *model.ReviewResult](name, config),
	}

	res.fullContentMaxLen = 5000
	res.abstractMaxLen = 100
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.riskClient = rpcImpl.NewRiskCheckRPCImpl()
	return res
}

func (s *SecurityReviewRecallLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*model.ReviewResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.SecurityReviewRecallLogic.fetch")

	startTime := time.Now().UnixMilli()

	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	// 获取 过滤白名单配置
	filterIncludeDocTypeArr, filterIncludePaperArr := graphUtil.GetFilterIncludeTypeConfig(s.Name, requestCtx)
	// 获取 附加排除的召回类型
	extraExcludedKbSources := s.getFilterExtraExcludeKbSourceConfig(requestCtx)

	// 判断是否检查全量文章
	isCheckFullContent := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.FilterLogicConfByIsCheckFullContent))

	resMap := make(map[data_frame.UniqueId]*model.ReviewResult)
	var resultMap sync.Map

	sourceQuery := requestCtx.GetBizContext().GetCurrentDialogue().Query
	query := requestCtx.GetBizContext().GetQueryMergeText()

	group := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", s.GetName(), "riskCheckRecallTitleAndAbstract"), 3000).SetLimit(10)
	for _, itemTmp := range items {
		item := itemTmp
		// 过滤白名单
		hitFilterWhiteList := item.GetBizItem().IsHitFilterWhiteList(filterIncludeDocTypeArr, filterIncludePaperArr)
		if !hitFilterWhiteList {
			continue
		}

		// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSources(extraExcludedKbSources) {
			continue
		}

		if item.GetBizItem().GetItemMeta().DocType == content.DocType_Member {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = &model.ReviewResult{
				IsAvailable: true,
			}
			continue
		}

		// 初始化设置当前item的安审结果为false
		reviewInitResult := &model.ReviewResult{}
		reviewInitResult.IsAvailable = false
		reviewInitResult.FailReason = "init"
		reviewInitResult.RequestInfo = fmt.Sprintf("title:%s, abstract:%s", item.GetBizItem().GetItemMeta().Title, item.GetBizItem().GetItemMeta().Abstract)
		reviewInitResult.ResponseInfo = "init"
		resultMap.Store(item, reviewInitResult)
		group.Go(func() error {
			// 摘要
			abstract := util.UnicodeSubstr(item.GetBizItem().GetItemMeta().Abstract, 0, s.abstractMaxLen)
			if abstract == "" {
				abstract = util.UnicodeSubstr(item.GetBizItem().GetItemMeta().Content, 0, s.abstractMaxLen)
			}
			// 全量内容
			fullContent := ""
			if isCheckFullContent {
				fullContent = util.UnicodeSubstr(item.GetBizItem().GetItemMeta().Content, 0, s.fullContentMaxLen)
				if fullContent == "" {
					fullContent = abstract
				}
			}

			res, rErr := s.riskClient.RiskCheckRecallTitleAbstract(ctx, rpc.RiskCheckRecallDto{
				Source:        item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String(),
				Url:           item.GetBizItem().GetItemMeta().Url,
				Query:         query,
				Title:         item.GetBizItem().GetItemMeta().Title,
				Abstract:      abstract,
				FullContent:   fullContent,
				MemberId:      requestCtx.GetBizContext().MemberId(),
				UserIp:        requestCtx.GetBizContext().RequestHeader().GetIp(),
				SessionId:     cast.ToString(requestCtx.GetBizContext().GetSessionId()),
				QuestionId:    sourceQuery.MessageId,
				QuestionText:  sourceQuery.MessageContent,
				ClientSource:  requestCtx.GetBizContext().GetClientSource().String(),
				TrafficSource: requestCtx.GetBizContext().GetTrafficSource().String(),
			})
			if rErr != nil || res == nil {
				return rErr
			}

			reviewResult := &model.ReviewResult{}
			reviewResult.IsAvailable = res.Res == rpc.RiskCheckResPass
			reviewResult.FailReason = cast.ToString(res.Res.ToConvert())
			reviewResult.RequestInfo = fmt.Sprintf("title:%s, abstract:%s", item.GetBizItem().GetItemMeta().Title, abstract)
			reviewResult.ResponseInfo = util.GetJSONIgnoreError(res)
			resultMap.Store(item, reviewResult)
			log.StatsdCheckItem(ctx, "SecurityReviewRecallLogic.fetch.all", reviewResult.IsAvailable)
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

func (s *SecurityReviewRecallLogic) saveLogicTracing(logCtx context.Context, reviewResults []*model.ReviewResult, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
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

func (s *SecurityReviewRecallLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.SecurityReviewRecallLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetSecurity().ReviewResult = res
	return nil
}

// getFilterExtraExcludeKbSourceConfig 获取过滤 排除召回类型
func (s *SecurityReviewRecallLogic) getFilterExtraExcludeKbSourceConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []conf.KbSource {
	filterLogicConfByExtraExcludeKbSourceStrArr := strings.Split(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.FilterLogicConfByExtraExcludeKbSourceArr), ",")
	filterExtraExcludeKbSourceArr := make([]conf.KbSource, 0)
	for _, kbSourceStr := range filterLogicConfByExtraExcludeKbSourceStrArr {
		kbSource := conf.KbSource(kbSourceStr)
		if kbSource == "" {
			continue
		}
		filterExtraExcludeKbSourceArr = append(filterExtraExcludeKbSourceArr, kbSource)
	}
	return filterExtraExcludeKbSourceArr
}
