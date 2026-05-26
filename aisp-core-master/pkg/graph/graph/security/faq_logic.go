package security

import (
	"context"
	"errors"
	"fmt"
	"math/rand"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	apollo_config "git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type faqResult struct {
	answer     string
	showRecall bool
}

const embeddingRecallTopK = 10

// FAQLogic
// @logicAuthor: keyan01
// @logicInfo: 通过用户的question找到answer
// @logicOutput: 0 | faq的answer string
// @logicOutput: 1 | 命中faq时是否展示召回 bool
type FAQLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]

	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[entities.Item], res faqResult) error

	operationBaseManagementService operation_base.OperationBaseManagementService
	operationBaseService           operation_base.OperationBaseService

	matchFuncMap map[conf.FaqMatchType]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error)

	rumClient    rpc.RumClient[float32]
	configClient config.Client
}

func NewFAQLogic(name string, config map[string]string) *FAQLogic {
	l := &FAQLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	l.MappingFunc = l.fetchA
	l.BizNodeType = "fetch"

	l.ItemMergeFunc = l.itemMerge

	l.rumClient = impl.DefaultFloat32RumClientImpl

	l.operationBaseManagementService = operation_base.DefaultOperationBaseManagementService
	l.operationBaseService = operation_base.DefaultOperationBaseService

	l.matchFuncMap = map[conf.FaqMatchType]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error){
		conf.FaqMatchTypeEmbeddingSimilarity: l.matchByEmbeddingSimilarity,
		conf.FaqMatchTypeFullMatch:           l.matchFullSentence,
		conf.FaqMatchTypeKeywordMatchAll:     l.matchKeywordAll,
		conf.FaqMatchTypeKeywordMatchAny:     l.matchKeywordAny,
	}

	l.configClient = apollo_config.GetClient()

	return l
}

func (u *FAQLogic) fetchA(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.FAQLogic.fetchA")
	defer span.Finish()

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", u.GetName())
		return itemList, nil
	}
	matchTypeKeyStr := requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.ConfigFaqMatchTypeKey)
	if matchTypeKeyStr == "" {
		return itemList, nil
	}

	startTime := time.Now().UnixMilli()

	faqMatchTypes := lo.Map(conf.SplitConfigArrayValue(matchTypeKeyStr),
		func(item string, _ int) conf.FaqMatchType {
			return conf.FaqMatchType(cast.ToInt(item))
		})
	if len(faqMatchTypes) == 0 {
		log.Errorf(ctx, "FAQLogic faqMatchTypes is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), u.GetName()))
		return itemList, nil
	}

	var resMap map[data_frame.UniqueId]faqResult
	errMap := map[string]error{}

	var err error
	for _, matchType := range faqMatchTypes {
		resMap, err = u.matchFuncMap[matchType](ctx, requestCtx, user, itemList)
		if err != nil {
			log.Error(ctx, requestCtx.GetCommonContext(), u.GetBizNodeType(), u.OriginName(), err)
			errMap[matchType.ConvertToName()] = err
			continue
		}

		if len(resMap) != 0 {
			log.Infof(ctx, "FAQLogic use rule %s, resMap: %v", matchType.ConvertToName(), resMap)
			break
		}
	}

	for _, item := range itemList {
		if res, ok := resMap[*item.GetCommonItem().GetUniqueId()]; ok {
			_ = u.ItemMergeFunc(ctx, item, res)

			requestCtx.DataMap().SetString(logCtx, u.GetOutputName(0), res.answer)
			if u.GetOutputSize() > 1 {
				requestCtx.DataMap().SetBool(logCtx, u.GetOutputName(1), res.showRecall)
			}
		}
	}

	u.saveTracing(logCtx, requestCtx, itemList[0].GetBizItem().Text, util.GetJSONIgnoreError(resMap), errMap, startTime)

	return itemList, nil
}

func (u *FAQLogic) matchFullSentence(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error) {

	resMap := make(map[data_frame.UniqueId]faqResult)
	promptInput := u.buildPromptInput(requestCtx, items)

	for _, item := range items {
		query := item.GetBizItem().Text
		// 按照顺序，命中整句 faq
		sentenceFaqFmt := u.getSentenceFaq(ctx, u.getFaqKey(requestCtx), query)
		if sentenceFaqFmt != "" {
			answer, err := model.GenPrompt(&promptInput, sentenceFaqFmt, cast.ToString(1))
			if err == nil {
				hit := answer != ""
				log.StatsdCheckItem(ctx, "FAQLogic.matchFullSentence.all", !hit)

				if hit {
					resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = faqResult{answer, false}
					continue
				}
			}
		}
	}

	return resMap, nil
}

func (u *FAQLogic) matchKeywordAll(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error) {
	resMap := make(map[data_frame.UniqueId]faqResult)
	promptInput := u.buildPromptInput(requestCtx, items)

	for _, item := range items {
		query := item.GetBizItem().Text
		// 命中关键词 faq
		keywordFaqFmt := u.getMatchAllKeyWordFaq(ctx, u.getFaqKey(requestCtx), query)
		if keywordFaqFmt != "" {
			answer, err := model.GenPrompt(&promptInput, keywordFaqFmt, cast.ToString(1))
			if err == nil {
				hit := answer != ""
				log.StatsdCheckItem(ctx, "FAQLogic.matchKeywordAll.all", !hit)
				if hit {
					resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = faqResult{answer, false}
					continue
				}
			}
		}
	}

	return resMap, nil
}

func (u *FAQLogic) matchKeywordAny(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error) {
	resMap := make(map[data_frame.UniqueId]faqResult)
	promptInput := u.buildPromptInput(requestCtx, items)

	for _, item := range items {
		query := item.GetBizItem().Text
		// 命中关键词 faq
		keywordFaqFmt := u.getMatchAnyKeyWordFaq(ctx, u.getFaqKey(requestCtx), query)
		if keywordFaqFmt != "" {
			answer, err := model.GenPrompt(&promptInput, keywordFaqFmt, cast.ToString(1))
			if err == nil {
				hit := answer != ""
				log.StatsdCheckItem(ctx, "FAQLogic.matchKeywordAny.all", !hit)
				if hit {
					resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = faqResult{answer, false}
					continue
				}
			}
		}
	}

	return resMap, nil
}

func (u *FAQLogic) getSimilarityThreshold(ctx context.Context, faqKey string, similarityThresholdKey string) (float32, error) {
	var thresholds map[string]float32

	err := util.JSONUnmarshal([]byte(u.configClient.GetString(similarityThresholdKey)), &thresholds)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "unmarshal embeddingSimilarityThreshold error")
		return 0, err
	}

	threshold, ok := thresholds[faqKey]
	if !ok {
		log.WithError(ctx, err).Errorf(ctx, "unmarshal embeddingSimilarityThreshold error. no key %s", faqKey)
		return 0, err
	}

	return threshold, nil
}

func (u *FAQLogic) getFaqKey(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	return requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.ConfigFaqKey)
}

func (u *FAQLogic) matchByEmbeddingSimilarity(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]faqResult, error) {
	resMap := make(map[data_frame.UniqueId]faqResult)

	faqKey := u.getFaqKey(requestCtx)
	similarityThresholdKey := requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.ConfigFaqSimilarityThreshold)

	threshold, err := u.getSimilarityThreshold(ctx, faqKey, similarityThresholdKey)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "getSimilarityThreshold error")
		return resMap, err
	}

	queryEmbedding := u.getEmbedding(ctx, requestCtx, items[0].GetBizItem().Text)
	if len(queryEmbedding) == 0 {
		log.Error(ctx, "BatchGetTextKlaraEmbedding error. result is empty")
		return resMap, err
	}

	var (
		answer     string
		showRecall bool
	)

	rumTableName, ok := u.operationBaseManagementService.GetSceneToRumTableNameMap(ctx)[faqKey]
	if !ok || rumTableName == "" {
		log.Errorf(ctx, "no rum table. faqKey=%s", faqKey)
		return resMap, errors.New("no rum table")
	}
	searchResult := u.rumClient.RumSearch(ctx, rumTableName, [][]float32{queryEmbedding}, embeddingRecallTopK, "", nil)
	if len(searchResult) == 0 {
		log.WithError(ctx, err).Error(ctx, "RumSearch result is empty")
		return resMap, err
	}

	if len(searchResult[0]) != 0 {
		top1 := u.selectOne(searchResult[0])
		if top1.Sim >= threshold {
			faqBase, _ := u.operationBaseManagementService.ListFaqBaseById(ctx, top1.GetId())
			if faqBase != nil {
				answerTemplate := faqBase.Answer
				promptInput := u.buildPromptInput(requestCtx, items)
				answer, err = model.GenPrompt(&promptInput, answerTemplate, cast.ToString(1))
				if err != nil {
					log.WithError(ctx, err).Error(ctx, "GenPrompt error")
				}

				showRecall = faqBase.ShowRecall == model.ShowRecallYes
			}
		}
	}

	hit := answer != ""
	if hit {
		resMap[*data_frame.NewUniqueId(items[0].GetCommonItem().Id())] = faqResult{
			answer,
			showRecall,
		}
	}

	log.StatsdCheckItem(ctx, "FAQLogic.matchByEmbeddingSimilarity.all", !hit)

	return resMap, nil
}

// results的结果中如果有多个分数相同的，则从这些结果中随机选择一个结果
func (u *FAQLogic) selectOne(results []*rpc.SearchResult) *rpc.SearchResult {
	if len(results) == 1 {
		return results[0]
	}

	maxSim := results[0].Sim
	var candidates []*rpc.SearchResult
	for _, result := range results {
		if util.CompareFloat(result.Sim, maxSim) {
			candidates = append(candidates, result)
		} else {
			break
		}
	}

	if len(candidates) == 0 {
		return results[0]
	}

	randomOne := candidates[rand.Intn(len(candidates))]
	return randomOne
}

func (u *FAQLogic) getEmbedding(ctx context.Context, requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], query string) []float32 {
	u.ZagStatsD.RecordTime(requestContext.GetCommonContext(), "bgeInfer.charSize", int64(len(query)))

	embeddingModelName := requestContext.GetBizContext().GetLogicConfig(u.GetName(), conf.EmbeddingModelName)
	if embeddingModelName == "" {
		embeddingModelName = "ensemble"
	}
	bgeEmbeddingClient := impl.GetBgeEmbeddingClient(embeddingModelName)

	embeddings := bgeEmbeddingClient.BatchInferEmbedding(ctx, []string{query})
	return embeddings[0]
}

func (u *FAQLogic) getSentenceFaq(ctx context.Context, faqKey string, query string) string {
	faqs := u.operationBaseService.ListFaqs(ctx, faqKey, conf.FaqMatchTypeFullMatch)
	queryHash := util.ConvertToRemovedSymbolHash(query)
	for _, faq := range faqs {
		if faq.QuestionNoSymbolHash == queryHash {
			return faq.Answer
		}
	}
	return ""
}

func (u *FAQLogic) getMatchAllKeyWordFaq(ctx context.Context, faqKey string, query string) string {
	faqs := u.operationBaseService.ListFaqs(ctx, faqKey, conf.FaqMatchTypeKeywordMatchAll)
	for _, faq := range faqs {
		keywordSlice := strings.Split(faq.Question, ",")
		// 要求关键词全包含，才可以返回默认回答
		containAll := false
		for _, keyword := range keywordSlice {
			if strings.Contains(query, keyword) {
				// 包含则为true，继续判断下一个词
				containAll = true
			} else {
				// 发现一个不包含的则为false，退出循环
				containAll = false
				break
			}
		}
		if containAll {
			return faq.Answer
		}
	}
	return ""
}

func (u *FAQLogic) getMatchAnyKeyWordFaq(ctx context.Context, faqKey string, query string) string {
	faqs := u.operationBaseService.ListFaqs(ctx, faqKey, conf.FaqMatchTypeKeywordMatchAny)
	for _, faq := range faqs {
		keywordSlice := strings.Split(faq.Question, ",")
		for _, keyword := range keywordSlice {
			if strings.Contains(query, keyword) {
				return faq.Answer
			}
		}
	}
	return ""
}

func (u *FAQLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res faqResult) error {
	item.GetBizItem().GetSecurity().FAQ = res.answer
	return nil
}

func (u *FAQLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	text string, faqResult string, errMap map[string]error, startTime int64) {

	logicTracing := &proto.LogicTracing{
		LogicName:    u.GetName(),
		LogicInput:   []string{fmt.Sprintf("text:%s, sceneKey:%s", text, u.getFaqKey(requestCtx))},
		LogicOutput:  []string{faqResult},
		LogicProcess: util.GetJSONIgnoreError(errMap),
		EdgeSelect:   "",
		StartTimeMs:  startTime,
		EndTimeMs:    time.Now().UnixMilli(),
		CostMs:       time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(u.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "text:%s, sceneKey:%s", text, u.getFaqKey(requestCtx))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", faqResult)
	macro.ProcessNodeLog.Infof(logCtx, "err:%s", util.GetJSONIgnoreError(errMap))

}

func (u *FAQLogic) buildPromptInput(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) model.PromptInput {
	promptInput := model.PromptInput{
		Query: items[0].GetBizItem().Text,
	}

	authorMeta := requestCtx.GetBizContext().AuthorInfo().UserMeta()
	if authorMeta != nil {
		promptInput.Topic = authorMeta.GetFinalSkilledAnswer()
		promptInput.AuthorName = authorMeta.GetUserName()
	}

	return promptInput
}
