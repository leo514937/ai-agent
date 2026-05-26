package recall

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/crawler_webpage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/search_recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 站外 召回 并 格式化文章

type KbOutSiteRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	outSiteSearchRecallService search_recall.OutSiteSearchRecallService
	crawlerWebpageService      crawler_webpage.CrawlerWebpageService
	kbSource                   conf.KbSource
}

func NewKbOutSiteRecallLogic(name string, config map[string]string) *KbOutSiteRecallLogic {
	res := &KbOutSiteRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.outSiteSearchRecallService = search_recall.NewOutSiteSearchRecallService()
	res.kbSource = conf.KbSource(config[conf.SummaryRecallSource.ToConvert()])
	res.crawlerWebpageService = crawler_webpage.DefaultCrawlerWebpageService
	// 召回源
	res.RecallFunc = res.realRecall
	return res
}

func (s *KbOutSiteRecallLogic) getRecallConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ZSearchRecallConfig {
	logicConfigStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if logicConfigStr == "" {
		log.Errorf(ctx, "KbOutSiteRecallLogic-%s getConfig error => config is empty", s.GetName())
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), s.GetName()))
		return conf.ZSearchRecallConfig{}
	}
	recallConfig := conf.ZSearchRecallConfig{}
	err := json.Unmarshal([]byte(logicConfigStr), &recallConfig)
	if err != nil {
		log.Errorf(ctx, "KbOutSiteRecallLogic-%s getConfig error => %s", s.GetName(), err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), s.GetName()))
		return conf.ZSearchRecallConfig{}
	}

	// 如果没有配置，则尝试
	if recallConfig.KnowledgeBaseType == "" {
		universalKnowledgeBaseType := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.KnowledgeBaseType)
		recallConfig.KnowledgeBaseType = enums.ParseKnowledgeBaseType(universalKnowledgeBaseType)
	}

	return recallConfig
}

func (s *KbOutSiteRecallLogic) realRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()

	recallConfig := s.getRecallConfig(ctx, requestCtx)
	resp := make([]*data_frame.ItemData[entities.Item], 0)

	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, s.GetName(), logic_context.CacheSourceByTidb, "recall.KbOutSiteRecallLogic.realRecall_"+s.kbSource.String())
	span := logicContext.Span
	ctx = logicContext.Ctx
	logCtx := logicContext.LogCtx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&resp))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		// data_frame 有些内部参数无法序列化，所以需要重新创建一下 item
		entities_util.ItemList2DataFrameListAndPush(&logicContext.CacheResp.Resp, requestCtx, &resp)
		return resp, nil
	}

	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithFields(ctx, map[string]any{
		"func":       "KbOutSiteRecallLogic.realMapping",
		"recallType": s.kbSource.String(),
	})
	logger.Infof(ctx, "do recall")

	query := requestCtx.GetBizContext().GetQueryMergeText()
	span.LogFields(log.OmittedString("query", query))
	if query == "" {
		return resp, nil
	}

	logger.Infof(ctx, "print searchRecallSize: %d", recallConfig.RecallSize)
	if recallConfig.RecallSize <= 0 {
		return resp, nil
	}
	// 召回 站外摘要文章
	contentResult := s.contentRecall(ctx, requestCtx, query, s.kbSource, recallConfig)
	// 取出指定个数的内容
	limitContents := contentResult
	// 创建 item
	for _, content := range limitContents {
		// 格式化摘要
		snippet := strings.ReplaceAll(content.Snippet, "[图片]", "")
		kbRecallRespItem := entities.ItemFromSummaryOtherRecall(
			content.Name, snippet, content.Url, content.MainText, s.kbSource, recallConfig.OrderGroup).IntoFrameItem(requestCtx)
		// 业务知识库
		kbRecallRespItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseType = recallConfig.KnowledgeBaseType
		linkType, subType, token := util.ParseLinkInfo(kbRecallRespItem.GetBizItem().GetItemMeta().Url)
		// 设置发布时间
		kbRecallRespItem.GetBizItem().GetItemMeta().PublishedTime = content.PublishedTime
		// 判断是否知乎召回
		if linkType == util.LinkTypeZhihu && token != "" {
			kbRecallRespItem.GetBizItem().GetItemMeta().UrlToken = token
			kbRecallRespItem.GetBizItem().GetItemMeta().DocType = model.GetDocType(subType)
		}
		kbRecallRespItem.GetBizItem().GetItemMeta().RecallSourceInfo.ExtraInfo = content.ExtraInfo
		// 记录召回队列名称
		kbRecallRespItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallerName = s.GetName()
		resp = append(resp, kbRecallRespItem)
	}

	log.StatsdRecall(ctx, s.kbSource.String(), "recall_content", len(resp))
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(len(resp)), s.kbSource.String())
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), s.kbSource.String()), float64(len(resp)))
	log.StatsdRecall(ctx, s.kbSource.String(), "recall_resp", len(resp))

	// 索引压力较大，2025.6.5 暂停实时流写入，全网搜重新规划，有需要再开启
	// s.asyncIndex(resp)
	s.saveTracing(logCtx, requestCtx, query, contentResult, len(resp), startTime, recallConfig)
	return resp, nil
}

func (s *KbOutSiteRecallLogic) asyncIndex(items []*data_frame.ItemData[entities.Item]) {
	// 异步写入索引
	ctx := context.Background()
	safe_group.SafeGo(func() error {
		// 限制并发数为 5
		group := safe_group.NewGroupWithTimeout("asyncOutSiteDoc2Index", 8000).SetLimit(5)

		for _, item := range items {
			itemMeta := item.GetBizItem().GetItemMeta()
			// 只针对站外内容补充索引
			if itemMeta.DocType != content.DocType_Link {
				continue
			}

			group.Go(func() error {
				messageContent := &module.CrawlerWebpageKafkaMsg{
					Title:            item.GetBizItem().GetItemMeta().Title,
					LinkUrl:          item.GetBizItem().GetItemMeta().Url,
					MetaUrl:          item.GetBizItem().GetItemMeta().Url,
					Source:           string(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()),
					Content:          item.GetBizItem().GetItemMeta().Content,
					Abstract:         item.GetBizItem().GetItemMeta().Abstract,
					Domain:           item.GetBizItem().GetItemMeta().Domain,
					PublishTime:      item.GetBizItem().GetItemMeta().PublishedTime,
					IsCrawlerAllowed: true,
					CrawlerTime:      time.Now().UnixMilli(),
					OtherInfo: util.GetJSONIgnoreError(map[string]interface{}{
						"source_type": "zhida",
					}),
				}

				err := s.crawlerWebpageService.UpsertDbAndIndex(ctx, messageContent)
				if err != nil {
					log.Errorf(ctx, "outsite recall async index error: %s, item:%s", err, util.GetJSONIgnoreError(messageContent))
				}
				return err
			})
		}

		return nil
	}, "async_outsite_index")
}

// Recall 内容召回
func (s *KbOutSiteRecallLogic) contentRecall(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, kbSource conf.KbSource, recallConfig conf.ZSearchRecallConfig) []*rpc.OutSiteSearchRecallAnswerResult {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbOutSiteRecallLogic.contentRecall_"+kbSource.String())
	defer span.Finish()

	recallQuery := s.genRecallQuery(requestCtx, query)

	var outSiteRecallType search_recall.OutSiteSearchRecallType
	switch kbSource {
	case conf.KbSourceBing:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeBing
	case conf.KbSourceSougou:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeSougou
	case conf.KbSourceQuark:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeQuark
	case conf.KbSourceSerper:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeSerper
	case conf.KbSourceKexin:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeKexin
	default:
	}

	extParams := make(map[string]string)
	if recallConfig.Freshness != "" {
		extParams["freshness"] = recallConfig.Freshness
	}

	// 站外搜索召回文章
	searchRecall := s.outSiteSearchRecallService.OutSiteSearchRecall(ctx,
		outSiteRecallType,
		recallQuery,
		recallConfig.RecallSize,
		requestCtx.GetCommonContext().RequestId(),
		extParams)

	// 最多为 限制数量的2倍召回
	return searchRecall[:zrecUtil.Min(int(recallConfig.RecallSize), len(searchRecall))]
}

func (s *KbOutSiteRecallLogic) genRecallQuery(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string) string {
	recallQuery := query
	// 目前来看业务逻辑不会单独使用 独一份站外召回源作为 rag输入，所以取消掉改处理逻辑
	//// 判断是否是与知乎做的混合召回，如果是混合召回的情况下 不需要限制知乎源
	//zhihuRecallConfig := requestCtx.GetBizContext().GetSummaryRecallOptionDetail(conf.KbSourceZhihu)
	//if zhihuRecallConfig.RecallSize <= 0 {
	//	recallQuery += " 知乎"
	//}
	return recallQuery
}

func (s *KbOutSiteRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, recallContents []*rpc.OutSiteSearchRecallAnswerResult, respChunkLength int, startTime int64, logicConfig conf.ZSearchRecallConfig) {

	logicTracing := &proto.LogicTracing{
		LogicName:       s.GetName(),
		LogicInput:      []string{fmt.Sprintf("query:%s, config:%s", s.genRecallQuery(requestCtx, query), util.GetJSONIgnoreError(logicConfig))},
		LogicOutput:     []string{},
		EdgeSelect:      "",
		StartTimeMs:     startTime,
		EndTimeMs:       time.Now().UnixMilli(),
		CostMs:          time.Now().UnixMilli() - startTime,
		LogicOutputJson: util.GetJSONIgnoreError(recallContents),
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "query:%s, config:%s", s.genRecallQuery(requestCtx, query), util.GetJSONIgnoreError(logicConfig))
	constant.DataOutputNodeLog.Infof(logCtx, "recall doc:%s, recall chunk length:%d", util.GetJSONIgnoreError(recallContents), respChunkLength)
}
