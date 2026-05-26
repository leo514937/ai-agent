package word

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/personal_knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/cespare/xxhash/v2"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 指定文档相关词召回/生成

// WordSpecifiedDocRecallOrGenLogic 指定文档相关词召回/生成
type WordSpecifiedDocRecallOrGenLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	personalKnowledgeBaseService service.PersonalKnowledgeBaseService
	wordMapperService            word.WordMapperService
	docRelateQueryDao            dao.DocRelateQueryDao
	wordType                     int32
	maxLength                    int
	recallOrGenConfig            string
}

func NewWordSpecifiedDocRecallOrGenLogic(name string, config map[string]string) *WordSpecifiedDocRecallOrGenLogic {
	res := &WordSpecifiedDocRecallOrGenLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.recallOrGenConfig = config[conf.ConfigRecallOrGen]
	res.maxLength = 2000
	res.wordType = int32(proto.QueryType_RELATE_WORD)
	res.personalKnowledgeBaseService = service.NewPersonalKnowledgeBaseServiceImpl()
	res.docRelateQueryDao = impl.NewDocRelateQueryDaoImpl()
	res.wordMapperService = word.NewWordMapperService()
	res.MergeFunc = res.recallOrGen
	return res
}

func (l *WordSpecifiedDocRecallOrGenLogic) recallOrGen(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordSpecifiedDocRecallLogic.recallOrGen")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	startTime := time.Now().UnixMilli()
	logger := log.WithField(ctx, "func", "recallOrGen")
	logger.Debug(ctx, "do running")

	// 填充已有的query
	queriesItem := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().QueryType != proto.QueryType_QUERY_UNDEFINED
	})
	for _, queryItem := range queriesItem {
		resp = append(resp, queryItem)
	}

	var queriesMap map[model.Content][]string
	if conf.ConfigRecallOrGenByRecall == l.recallOrGenConfig {
		queriesMap = l.getQueriesByRecall(ctx, requestCtx.GetBizContext().GetSpecifiedDocAboutQueriesRequest())
		for _, doc := range requestCtx.GetBizContext().GetSpecifiedDocAboutQueriesRequest() {
			modelContent := l.getModelContent(doc)
			queriesTmp, isExist := queriesMap[modelContent]
			if !isExist || len(queriesTmp) == 0 {
				recallItem := l.genRecallItem(modelContent.ContentID, modelContent.GetDocType(), doc.GetTitle(), doc.GetAbstract())
				resp = append(resp, recallItem.IntoFrameItem(requestCtx))
			}
		}
	} else {
		queriesMap = l.getQueriesByGen(ctx, itemLists)
	}

	recallQueries := make([]model.WordMapperCreateDto, 0)
	for _, queries := range queriesMap {
		for _, wordStr := range queries {
			recallQueries = append(recallQueries, model.WordMapperCreateDto{
				Word:     wordStr,
				WordType: l.wordType,
			})
		}
	}

	batchGetWordIdAndSaveWord := l.wordMapperService.BatchGetWordIdAndSaveWord(ctx, recallQueries)
	respQueries := make([]*proto.Query, 0)
	for wordDto, wordId := range batchGetWordIdAndSaveWord {
		queryItem := l.genQueryItem(wordDto, wordId)
		resp = append(resp, queryItem.IntoFrameItem(requestCtx))
	}
	l.saveTracing(requestCtx, respQueries, startTime)
	return resp, nil
}

func (l *WordSpecifiedDocRecallOrGenLogic) getQueriesByRecall(ctx context.Context, specifiedDocAboutQueriesRequest []*proto.DocAboutQueriesRequest) map[model.Content][]string {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "WordSpecifiedDocRecallLogic.getQueriesByRecall",
	})
	syncWordMap := util.NewSyncMap[model.Content, []string]()
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "recallWordsGroup"), 2000)
	for _, doc := range specifiedDocAboutQueriesRequest {
		modelContent := l.getModelContent(doc)
		wg.Go(func() error {
			queries := l.docRelateQueryDao.GetDocRelateQueries(ctx, modelContent.ContentID, modelContent.GetDocType())
			syncWordMap.Set(modelContent, queries)
			return nil
		})
	}
	// 等待所有 goroutine 完成
	wgErr := wg.Wait()
	if wgErr != nil {
		logger.Warnf(ctx, "recallWordsGroup Wait Err => %v", wgErr)
	}

	respMap := make(map[model.Content][]string)
	syncWordMap.Range(func(key model.Content, val []string) bool {
		respMap[key] = val
		return true
	})
	return respMap
}

func (l *WordSpecifiedDocRecallOrGenLogic) getQueriesByGen(ctx context.Context, itemLists [][]*data_frame.ItemData[entities.Item]) map[model.Content][]string {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "WordSpecifiedDocRecallLogic.getQueriesByGen",
	})

	// 拍平 ItemLists
	items := lo.Flatten(itemLists)
	recallItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})

	syncWordMap := util.NewSyncMap[model.Content, []string]()
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "genWordsGroup"), 3000)
	for _, recallItem := range recallItems {
		recallItem := recallItem
		wg.Go(func() error {
			modelContent := l.getModelContent(&proto.DocAboutQueriesRequest{
				DocId:    recallItem.GetBizItem().GetItemMeta().DocId,
				DocType:  model.GetZhiDaDocType(recallItem.GetBizItem().GetItemMeta().DocType),
				Title:    recallItem.GetBizItem().GetItemMeta().GetTitle(),
				Abstract: recallItem.GetBizItem().GetItemMeta().Abstract,
			})
			queries := l.personalKnowledgeBaseService.GetRelateQueryAndSave(ctx, &model.PersonalKnowledgeDoc{
				DocId:    recallItem.GetBizItem().GetItemMeta().DocId,
				DocType:  recallItem.GetBizItem().GetItemMeta().DocType,
				Title:    recallItem.GetBizItem().GetItemMeta().GetTitle(),
				Abstract: recallItem.GetBizItem().GetItemMeta().Abstract,
				Content:  recallItem.GetBizItem().GetItemMeta().Content,
			}, l.maxLength)
			syncWordMap.Set(modelContent, queries)
			return nil
		})
	}
	// 等待所有 goroutine 完成
	wgErr := wg.Wait()
	if wgErr != nil {
		logger.Warnf(ctx, "genWordsGroup Wait Err => %v", wgErr)
	}

	respMap := make(map[model.Content][]string)
	syncWordMap.Range(func(key model.Content, val []string) bool {
		respMap[key] = val
		return true
	})
	return respMap
}

func (l *WordSpecifiedDocRecallOrGenLogic) getModelContent(doc *proto.DocAboutQueriesRequest) model.Content {
	docId := doc.GetDocId()
	docType := util.ContentType2DocType(doc.GetDocType())
	// 如果docId 和 docType 为未知，且title 和 abs 不为空，则表示为文本类型 需要单独处理缓存key
	if docId <= 0 && docType == content.DocType_Unknown &&
		(doc.GetTitle() != "" || doc.GetAbstract() != "") {
		docId = int64(xxhash.Sum64String(fmt.Sprintf("%s\n%s", doc.GetTitle(), doc.GetAbstract())))
		docType = content.DocType_Text
	}
	return model.NewContentWithDocType(docId, docType)
}

func (l *WordSpecifiedDocRecallOrGenLogic) genQueryItem(wordDto model.WordMapperCreateDto, wordId int64) *entities.Item {
	query := &proto.Query{
		Id:        cast.ToString(wordId),
		Query:     wordDto.Word,
		QueryType: proto.QueryType(wordDto.WordType),
		RiskType:  macro.CensorTypeMap[proto.QueryType(wordDto.WordType)],
	}
	queryItem := entities.ItemFromQuery(query, -1, query.GetRiskType())
	queryItem.GetItemMeta().DocId = cast.ToInt64(query.GetId())
	queryItem.GetItemMeta().DocType = content.DocType_AiPrefabWord
	return queryItem
}

func (l *WordSpecifiedDocRecallOrGenLogic) genRecallItem(docId int64, docType content.DocType_Type, title string, abstract string) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			Title:    title,
			Abstract: abstract,
			DocId:    docId,
			DocType:  docType,
			RecallSourceInfo: &model.RecallSourceInfo{
				IndexSource: conf.IndexSourceZhihu,
				KbSources:   []conf.KbSource{conf.KbSourceUserSpecified},
			},
		},
		Security: &model.Security{},
	}
	return item
}

func (l *WordSpecifiedDocRecallOrGenLogic) saveTracing(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	respQueries []*proto.Query, startTime int64) {
	logicTracing := &proto.LogicTracing{
		LogicName:   l.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(requestCtx.GetBizContext().GetSpecifiedDocAboutQueriesRequest())},
		LogicOutput: []string{util.GetJSONIgnoreError(respQueries)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(l.GetName(), logicTracing)
}
