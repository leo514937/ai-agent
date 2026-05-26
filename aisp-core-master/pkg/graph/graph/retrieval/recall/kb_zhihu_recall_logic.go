package recall

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回 并 格式化文章

type KbZhihuRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	searchRpcClient rpc.SearchServiceRPC
}

func NewKbZhihuRecallLogic(name string, config map[string]string) *KbZhihuRecallLogic {
	res := &KbZhihuRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.searchRpcClient = impl.DefaultSearchServiceRpcImpl
	res.RecallFunc = res.realRecall
	return res
}

func (s *KbZhihuRecallLogic) getRecallConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ZSearchRecallConfig {
	logicConfigStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if logicConfigStr == "" {
		log.Errorf(ctx, "KbZhihuRecallLogic getConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), s.GetName()))
		return conf.ZSearchRecallConfig{}
	}
	recallConfig := conf.ZSearchRecallConfig{}
	err := json.Unmarshal([]byte(logicConfigStr), &recallConfig)
	if err != nil {
		log.Errorf(ctx, "KbZhihuRecallLogic getConfig error => %s", err)
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

func (s *KbZhihuRecallLogic) realRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, s.GetName(), logic_context.CacheSourceByTidb, "recall.KbZhihuRecallLogic.realRecall_"+conf.KbSourceZhihu.String())
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

	recallConfig := s.getRecallConfig(ctx, requestCtx)

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbZhihuRecallLogic.realMapping",
	})
	query := requestCtx.GetBizContext().GetQueryMergeText()
	span.LogFields(log.OmittedString("query", query))

	// 检查必要条件
	if query == "" {
		return resp, nil
	}

	// 输出召回数量配置
	logger.Infof(ctx, "print searchRecallSize: %d", recallConfig.RecallSize)

	// 召回
	itemList := s.contentRecall(ctx, query, requestCtx, recallConfig)

	for _, item := range itemList {
		resp = append(resp, item.IntoFrameItem(requestCtx))
	}

	s.saveTracing(logCtx, requestCtx, query, itemList, recallConfig, startTime)

	// 根据source 分组 后打点监控
	groupByKbSource := lo.GroupBy(itemList, func(item *entities.Item) string {
		return item.GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String()
	})
	groupByKbSourceAndCount := lo.MapValues(groupByKbSource, func(v []*entities.Item, k string) int {
		return len(v)
	})
	for _, vertical := range recallConfig.Vertical {
		source := vertical2KbSource(vertical, recallConfig.OnlyA4p).String()
		count := groupByKbSourceAndCount[vertical2KbSource(vertical, recallConfig.OnlyA4p).String()]
		log.StatsdRecall(ctx, source, "recall_content", count)
		// 新
		util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(count), source)
		// 老
		statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), source), float64(count))
		log.StatsdRecall(ctx, source, "recall_resp", count)
	}
	return resp, nil
}

// contentRecall 内容召回
func (s *KbZhihuRecallLogic) contentRecall(ctx context.Context, query string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], recallConfig conf.ZSearchRecallConfig) []*entities.Item {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbZhihuRecallLogic.contentRecall_"+conf.KbSourceZhihu.String())
	defer span.Finish()
	span.LogFields(log.Message("start."), log.OmittedString("recall_query", query))

	logger := log.WithField(ctx, "KbZhihuRecallLogic", map[string]any{
		"method": "contentRecall",
		"query":  query,
	})

	var resList []*entities.Item

	if recallConfig.RecallSize <= 0 {
		return resList
	}

	var authorIds []int64
	if requestCtx.GetBizContext().AuthorInfo() != nil {
		// 用户未开启知识库同步，不召回 p1 库
		isP1Enable := requestCtx.GetBizContext().AuthorInfo().UserMeta().IsEnableOnsite()
		if recallConfig.IndexLevel == conf.IndexLevel1 && !isP1Enable {
			return resList
		}

		// 用户未开启通用知识库，不召回 p2 库
		isP2Enable := requestCtx.GetBizContext().AuthorInfo().UserMeta().IsEnableUniversal()
		if recallConfig.IndexLevel == conf.IndexLevel2 && !isP2Enable {
			return resList
		}

		if requestCtx.GetBizContext().AuthorInfo().GetMemberId() > 0 {
			authorIds = []int64{requestCtx.GetBizContext().AuthorInfo().GetMemberId()}
		}
	}

	// 获取历史&当前挂载 member，当前挂载优先
	if len(requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountMembers()) > 0 {
		authorIds = requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountMembers()
	}
	if len(requestCtx.GetBizContext().GetCurrReferenceMount().GetMountMembers()) > 0 {
		authorIds = requestCtx.GetBizContext().GetCurrReferenceMount().GetMountMembers()
	}

	var restrictedScope *searchThrift.RestrictedScope

	if recallConfig.RestrictedScope.RestrictedScene != "" && len(authorIds) > 0 {
		promptInput := model.PromptInput{
			AuthorIds:  strings.Join(util.Int64SliceToString(authorIds), ","),
			IndexLevel: string(recallConfig.IndexLevel),
		}
		value, err := model.GenPrompt(&promptInput, recallConfig.RestrictedScope.RestrictedValue, cast.ToString(1001))
		if err == nil && value != "" {
			restrictedScope = &searchThrift.RestrictedScope{
				RestrictedScene: recallConfig.RestrictedScope.RestrictedScene,
				RestrictedField: recallConfig.RestrictedScope.RestrictedField,
				RestrictedValue: value,
			}
		}
	}

	relAbMap := make(map[string]string)
	if len(requestCtx.GetBizContext().GetAbParamMap()) > 0 {
		for _, exps := range requestCtx.GetBizContext().GetAbParamAllValue() {
			for expKey, expValue := range exps {
				relAbMap[expKey] = expValue
			}
		}
	}
	var searchResults []*searchThrift.SearchHit

	// 如果多个 restrict 条件，那么并发请求
	var values []string
	if restrictedScope != nil {
		values = strings.Split(restrictedScope.RestrictedValue, ",")
	} else {
		values = []string{""}
	}

	resultCh := make(chan []*searchThrift.SearchHit, len(values))
	group := safe_group.NewGroup("SearchService")

	for _, value := range values {
		value := value
		group.Go(func() error {
			req := rpc.SearchServiceRequest{
				Offset:              0,
				Limit:               recallConfig.RecallSize,
				Vertical:            recallConfig.Vertical,
				Query:               util2.CleanQueryAuthor(query),
				TimeAfter:           0,
				TimeBefore:          recallConfig.TimeBefore,
				MemberID:            requestCtx.GetBizContext().MemberId(),
				AbParams:            relAbMap,
				NeedQueryCorrection: !recallConfig.NeedNotQueryCorrection,
			}
			if restrictedScope != nil && value != "" {
				req.RestrictedScope = &searchThrift.RestrictedScope{
					RestrictedScene: restrictedScope.RestrictedScene,
					RestrictedField: restrictedScope.RestrictedField,
					RestrictedValue: value,
				}
			}
			if recallConfig.OnlyA4p {
				req.SearchFilterOption = &searchThrift.SearchFilterOption{
					HighQuality: lo.ToPtr(true),
				}
			}
			result := s.searchRpcClient.Search(ctx, req)
			resultCh <- result
			return nil
		})
	}

	go func() {
		wgErr := group.Wait()
		if wgErr != nil {
			log.Errorf(ctx, "Wait Err => %v", wgErr)
		}
		close(resultCh)
	}()

	for res := range resultCh {
		searchResults = append(searchResults, res...)
	}

	for _, res := range searchResults {
		if res.DocID == "" {
			continue
		}
		parts := strings.SplitN(res.DocID, "_", 2)
		if len(parts) != 2 {
			logger.Errorf(ctx, "zsearch recall resp illegal! len(parts) = %d", len(parts))
			continue
		}

		docId, err := util.String2Int64(res.OriginalID)
		docType := getDocType(parts[0])

		if err != nil || docId == 0 || docType == content.DocType_Unknown {
			logger.Errorf(ctx, "docId or docType illegal! docId:%s,docType:%s", res.OriginalID, parts[0])
			continue
		}

		resList = append(resList, s.genItem(docId, docType, recallConfig, res.Score, res.Vertical, res.ExtraFields))
	}

	return resList
}

func (s *KbZhihuRecallLogic) genItem(docId int64, docType content.DocType_Type, recallConfig conf.ZSearchRecallConfig, score float64, vertical searchThrift.Vertical, extraFields string) *entities.Item {
	urlToken := getUrlToken(extraFields)
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
				UniversalKnowledgeBaseType: recallConfig.KnowledgeBaseType,
				RecallerName:               s.GetName(),
				IndexSource:                conf.IndexSourceZhihu,
				IndexLevel:                 recallConfig.IndexLevel,
				RecallScore:                score,
				OrderGroup:                 recallConfig.OrderGroup,
				KbSources:                  []conf.KbSource{vertical2KbSource(vertical, recallConfig.OnlyA4p)},
			},
			Url: getUrl(docType, urlToken),
		},
		Security: &model.Security{},
	}

	return item
}

func vertical2KbSource(vertical searchThrift.Vertical, onlyA4p bool) conf.KbSource {
	switch vertical {
	case searchThrift.Vertical_CONTENT:
		if onlyA4p {
			return conf.KbSourceZhihuA4
		} else {
			return conf.KbSourceZhihu
		}
	case searchThrift.Vertical_DomesticScholar:
		return conf.KbSourceZhihuWeipu
	case searchThrift.Vertical_ForeignScholar:
		return conf.KbSourceZhihuArxiv
	default:
		return conf.KbSourceZhihu
	}
}

func getUrl(docType content.DocType_Type, urlToken string) string {
	switch docType {
	case content.DocType_Article:
		return fmt.Sprintf("https://zhuanlan.zhihu.com/p/%s", urlToken)
	case content.DocType_Answer:
		return fmt.Sprintf("https://www.zhihu.com/answer/%s", urlToken)
	default:
		return ""
	}
}

func getUrlToken(extraFields string) string {
	var extraFieldsMap map[string]interface{}
	err := json.Unmarshal([]byte(extraFields), &extraFieldsMap)
	if err != nil {
		return ""
	}

	if _, ok := extraFieldsMap["url_token"]; ok {
		return extraFieldsMap["url_token"].(string)
	} else {
		return ""
	}
}

func getDocType(docTypeStr string) content.DocType_Type {
	switch docTypeStr {
	case macro.ContentDocTypeArticle:
		return content.DocType_Article
	case macro.ContentDocTypeAnswer:
		return content.DocType_Answer
	case macro.ContentDocTypeWeiPu, macro.ContentDocTypeArxiv:
		return content.DocType_Paper
	default:
		return content.DocType_Unknown
	}
}

func (s *KbZhihuRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, recallContents []*entities.Item, recallConfig conf.ZSearchRecallConfig, startTime int64) {
	var tracingOutput []string
	var output []string
	for _, item := range recallContents {
		tracingOutput = append(tracingOutput, util.GetJSONIgnoreError(item))
		output = append(output, item.ToDescription())
	}
	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{fmt.Sprintf("query:%s, recallConfig:%s", query, util.GetJSONIgnoreError(recallConfig))},
		LogicOutput: tracingOutput,
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "query:%s, recallConfig:%s", query, util.GetJSONIgnoreError(recallConfig))
	// tracingOutput字段太长了，会被截断。所以这里只打印ItemMeta
	constant.DataOutputNodeLog.Infof(logCtx, "%s", output)
}
