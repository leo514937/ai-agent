package recall

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 安全知识增强召回

type KbEnhanceRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	orderGroup int
}

func NewKbEnhanceRecallLogic(name string, config map[string]string) *KbEnhanceRecallLogic {
	res := &KbEnhanceRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 召回排序分组
	res.orderGroup = cast.ToInt(config[conf.SummaryRecallOrderGroup.ToConvert()])
	res.RecallFunc = res.realRecall
	return res
}

func (k *KbEnhanceRecallLogic) realRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "recall.KbEnhanceRecallLogic.realRecall_"+conf.KbSourceZhihuKbEnhance.String())
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	query := requestCtx.GetBizContext().RequestMessage().Text
	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()
	span.LogFields(log.OmittedString("query", query))
	logger := log.WithField(ctx, "KbEnhanceRecallLogic", map[string]any{
		"class":         "KbEnhanceRecallLogic",
		"func":          "realRecall",
		"query":         query,
		"respMessageId": requestCtx.GetBizContext().RespMessageId(),
	})

	var resp []*data_frame.ItemData[entities.Item]
	// 豁免安全的，不过知识增强
	if requestCtx.GetBizContext().GetIsExemptSecurity() {
		return resp, nil
	}

	// 检查必要条件
	if query == "" || queryMerge == "" {
		return resp, nil
	}

	realQuery := query
	knowledgeEnhance, keyword, hit := "", "", false
	// 如果query 直接命中知识库增强 则直接返回
	if query != "" {
		// 使用 query 和 query_merge 进行匹配
		// 匹配出的知识作为 召回 的 context 的一个知识放在列表最后
		knowledgeEnhance, keyword, hit = operation_base.DefaultOperationBaseService.HitKnowledgeEnhance(query)
	}

	// 如果query没命中 则使用 queryMerge进行尝试 直接命中知识库增强 则直接返回
	if !hit && queryMerge != "" {
		// 使用 query 和 query_merge 进行匹配
		// 匹配出的知识作为 召回 的 context 的一个知识放在列表最后
		knowledgeEnhance, keyword, hit = operation_base.DefaultOperationBaseService.HitKnowledgeEnhance(queryMerge)
		realQuery = queryMerge
	}
	log.StatsdCheckItem(ctx, "KnowledgeEnhanceLogic.fetch.all", !hit)

	// 如果还未命中知识库增强 则直接返回空的召回内容
	if !hit {
		return resp, nil
	}

	item := entities.ItemFromSummary(knowledgeEnhance, k.orderGroup)
	item.GetItemMeta().GetRecallSourceInfo().KbSources = []conf.KbSource{conf.KbSourceZhihuKbEnhance}
	resp = append(resp, item.IntoFrameItem(requestCtx))
	logger.Infof(ctx, "knowledge enhance:%s", knowledgeEnhance)
	k.saveSecurityTracing(knowledgeEnhance, keyword, requestCtx)
	log.StatsdRecall(ctx, conf.KbSourceZhihuKbEnhance.String(), "recall_content", len(resp))

	k.saveTracing(logCtx, requestCtx, realQuery, knowledgeEnhance, len(resp), startTime)
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(len(resp)), conf.KbSourceZhihuKbEnhance.String())
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), conf.KbSourceZhihuKbEnhance.String()), float64(len(resp)))
	log.StatsdRecall(ctx, conf.KbSourceZhihuKbEnhance.String(), "recall_resp", len(resp))
	return resp, nil
}

func (k *KbEnhanceRecallLogic) saveSecurityTracing(knowledgeEnhance string, keyword string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	securityTracing := &proto.SecurityTracing{
		KnowledgeEnhance:        knowledgeEnhance,
		KnowledgeEnhanceKeyword: keyword,
	}
	securityChan := requestCtx.GetBizContext().ProcessTracing().SecurityTracing
	if len(securityChan) < entities.MaxTracingChanSize {
		securityChan <- securityTracing
	}
}

func (k *KbEnhanceRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, knowledgeEnhance string, respChunkLength int, startTime int64) {

	logicTracing := &proto.LogicTracing{
		LogicName:   k.GetName(),
		LogicInput:  []string{fmt.Sprintf("query:%s, searchRecallLimit:%d", query, 1)},
		LogicOutput: []string{fmt.Sprintf("recall KbEnhance:%s, recall KbEnhance length:%d", knowledgeEnhance, respChunkLength)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(k.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "query:%s, searchRecallLimit:%d", query, 1)
	constant.DataOutputNodeLog.Infof(logCtx, "recall KbEnhance:%s, recall KbEnhance length:%d", knowledgeEnhance, respChunkLength)

}
