package recall

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
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
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 补充arxiv 召回

type KbReplenishArxivRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	outSiteSearchRecallService search_recall.OutSiteSearchRecallService
	contentCoreClient          rpc.ContentCoreRPC
	kbSource                   conf.KbSource
	kbSourceLogName            string
	replenishMaxVersion        int
}

func NewKbReplenishArxivRecallLogic(name string, config map[string]string) *KbReplenishArxivRecallLogic {
	res := &KbReplenishArxivRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.replenishMaxVersion = 0
	res.kbSource = conf.KbSourceBing
	res.kbSourceLogName = fmt.Sprintf("arxiv_%s", res.kbSource.String())
	res.outSiteSearchRecallService = search_recall.NewOutSiteSearchRecallService()
	res.contentCoreClient = impl.NewContentCoreRPCImpl()
	// 召回源
	res.RecallFunc = res.realRecall
	return res
}

func (s *KbReplenishArxivRecallLogic) realRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	startTime := time.Now().UnixMilli()
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, s.GetName(), logic_context.CacheSourceByTidb, "recall.KbReplenishArxivRecallLogic.realRecall_"+s.kbSourceLogName)
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
		"func": "KbReplenishArxivRecallLogic.realMapping",
	})
	logger.Debugf(ctx, "do running")

	universalKnowledgeBaseType := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.KnowledgeBaseType)
	recallSize := cast.ToInt32(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.ConfigRecallSize))
	query := requestCtx.GetBizContext().GetQueryMergeText()
	span.LogFields(log.OmittedString("query", query))
	if query == "" {
		return resp, nil
	}

	logger.Infof(ctx, "print searchRecallSize: %d", recallSize)
	if recallSize <= 0 {
		return resp, nil
	}
	// 召回 站外摘要文章
	contentResult := s.contentRecall(ctx, query, s.kbSource, recallSize, requestCtx.GetCommonContext().RequestId())
	arxivIds := s.buildArxivIds(contentResult)
	realContentResult := s.batchGetContentPaperByOutSiteTypeId(ctx, arxivIds)
	for _, arxivId := range arxivIds {
		if realContent, isOk := realContentResult[arxivId]; isOk && realContent != nil {
			item := s.genItem(realContent.ContentID, realContent.GetDocType(), 0, enums.ParseKnowledgeBaseType(universalKnowledgeBaseType)).IntoFrameItem(requestCtx)
			resp = append(resp, item)
		}
	}

	log.StatsdRecall(ctx, s.kbSourceLogName, "recall_content", len(resp))
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(len(resp)), s.kbSourceLogName)
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), s.kbSourceLogName), float64(len(resp)))
	log.StatsdRecall(ctx, s.kbSourceLogName, "recall_resp", len(resp))

	s.saveTracing(logCtx, requestCtx, query, contentResult, len(resp), startTime, recallSize)
	return resp, nil
}

// Recall 内容召回
func (s *KbReplenishArxivRecallLogic) contentRecall(ctx context.Context,
	query string, kbSource conf.KbSource, recallSize int32, traceId string) []*rpc.OutSiteSearchRecallAnswerResult {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbReplenishArxivRecallLogic.contentRecall_"+kbSource.String())
	defer span.Finish()

	recallQuery := fmt.Sprintf("%s site:arxiv.org", query)

	var outSiteRecallType search_recall.OutSiteSearchRecallType
	switch kbSource {
	case conf.KbSourceBing:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeBing
	case conf.KbSourceSougou:
		outSiteRecallType = search_recall.OutSiteSearchRecallTypeSougou
	default:
	}

	// 站外搜索召回文章
	searchRecall := s.outSiteSearchRecallService.OutSiteSearchRecall(ctx, outSiteRecallType, recallQuery, recallSize, traceId, nil)

	// 最多为 限制数量的2倍召回
	return searchRecall[:zrecUtil.Min(int(recallSize), len(searchRecall))]
}

func (s *KbReplenishArxivRecallLogic) buildArxivIds(recallContents []*rpc.OutSiteSearchRecallAnswerResult) []string {
	arxivIds := make([]string, 0)
	// 截取内容ID，并尝试扩充v1-v6 召回
	for _, recallContent := range recallContents {
		originalID := ""
		if strings.HasPrefix(recallContent.Url, "https://arxiv.org/abs") {
			parts := strings.Split(recallContent.Url, "arxiv.org/abs/")
			if len(parts) > 1 {
				originalID = parts[1]
			}
		} else if strings.HasPrefix(recallContent.Url, "https://arxiv.org/pdf") {
			parts := strings.Split(recallContent.Url, "arxiv.org/pdf/")
			if len(parts) > 1 {
				originalID = parts[1]
			}
		}
		if originalID == "" {
			continue
		}
		arxivIds = append(arxivIds, originalID)
	}
	return arxivIds
}

func (s *KbReplenishArxivRecallLogic) batchGetContentPaperByOutSiteTypeId(ctx context.Context, arxivIds []string) map[string]*model.Content {
	groupDict := make(map[rpc.OutSitePaper]rpc.OutSitePaper)
	outSitePapers := make([]rpc.OutSitePaper, 0)
	// 截取内容ID，并尝试扩充v1-vn 召回
	for _, arxivId := range arxivIds {
		// 去除版本号
		sourceOriginalID := removeVersionSuffix(arxivId)
		sourceRpcDto := rpc.OutSitePaper{
			OutId:     sourceOriginalID,
			PaperType: rpc.OutSitePaperTypeArxiv,
		}
		for i := 0; i <= s.replenishMaxVersion; i++ {
			currOutSitePaperId := sourceOriginalID
			if i != 0 {
				// 示例ID 2307.02288v2
				currOutSitePaperId = fmt.Sprintf("%sv%d", sourceOriginalID, i)
			}

			rpcDto := rpc.OutSitePaper{
				OutId:     currOutSitePaperId,
				PaperType: rpc.OutSitePaperTypeArxiv,
			}
			outSitePapers = append(outSitePapers, rpcDto)
			groupDict[rpcDto] = sourceRpcDto
		}
	}

	groupPapers := make(map[rpc.OutSitePaper][]lo.Tuple2[*model.Content, int64])
	rpcResult := s.contentCoreClient.BatchGetContentPaperByOutSiteTypeId(ctx, outSitePapers)
	for k, v := range rpcResult {
		if groupId, isOk := groupDict[k]; isOk {
			if _, isArrOk := groupPapers[groupId]; !isArrOk {
				groupPapers[groupId] = make([]lo.Tuple2[*model.Content, int64], 0)
			}
			versionNumber, _ := extractVersionNumber(k.OutId)
			groupPapers[groupId] = append(groupPapers[groupId], lo.Tuple2[*model.Content, int64]{
				A: v,
				B: cast.ToInt64(versionNumber),
			})
		}
	}

	// 对扩充召回内容排序
	for _, arr := range groupPapers {
		// Version 倒序排序
		sort.Slice(arr, func(i, j int) bool {
			return arr[i].B > arr[j].B
		})
	}

	result := make(map[string]*model.Content)
	for k, v := range groupPapers {
		result[k.OutId] = v[0].A
	}
	return result
}

func (s *KbReplenishArxivRecallLogic) genItem(docId int64, docType content.DocType_Type, score float64, bizBaseType enums.KnowledgeBaseType) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 "",
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			Content: "",
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallerName:               s.GetName(),
				IndexSource:                conf.IndexSourceZhihu,
				UniversalKnowledgeBaseType: bizBaseType,
				RecallScore:                score,
				KbSources:                  []conf.KbSource{conf.KbSourceZhihuArxiv, s.kbSource},
			},
		},
		Security: &model.Security{},
	}
	return item
}

func (s *KbReplenishArxivRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, recallContents []*rpc.OutSiteSearchRecallAnswerResult, respChunkLength int, startTime int64, recallSize int32) {

	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{fmt.Sprintf("query:%s, recallSize:%d", query, recallSize)},
		LogicOutput: []string{fmt.Sprintf("recall doc:%s, recall chunk length:%d", util.GetJSONIgnoreError(recallContents), respChunkLength)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)
	constant.DataInputNodeLog.Infof(logCtx, "query:%s, recallSize:%d", query, recallSize)
	constant.DataOutputNodeLog.Infof(logCtx, "recall doc:%s, recall chunk length:%d", util.GetJSONIgnoreError(recallContents), respChunkLength)
}

// 定义正则表达式，匹配末尾的版本标识 v1 到 v9
var removeVersionRegexp = regexp.MustCompile(`v[1-9]\d*$`)

// extractVersionNumber 使用正则表达式提取字符串末尾的版本标识中的数字
func extractVersionNumber(s string) (string, error) {
	// 使用正则表达式查找匹配的内容
	matches := removeVersionRegexp.FindStringSubmatch(s)
	if len(matches) > 1 {
		// 返回匹配的数字部分
		return matches[1], nil
	}
	// 如果没有匹配到，返回错误
	return "", fmt.Errorf("no version number found in the string")
}

// removeVersionSuffix 使用正则表达式移除字符串末尾的版本标识
func removeVersionSuffix(s string) string {
	// 使用正则表达式替换匹配的内容为空字符串
	result := removeVersionRegexp.ReplaceAllString(s, "")
	return result
}
