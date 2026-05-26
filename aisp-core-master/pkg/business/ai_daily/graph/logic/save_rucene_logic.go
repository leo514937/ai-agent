package logic

import (
	"context"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	core_model "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/apollo"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type SaveRuceneLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	segmentRpc rpc.SegmentRPC
	ruceneRpc  rpc.RuceneServiceRPC
}

func NewSaveRuceneLogic(name string, config map[string]string) *SaveRuceneLogic {
	s := &SaveRuceneLogic{
		UserLogic:  framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
		segmentRpc: rpcImpl.DefaultSegmentImpl,
		ruceneRpc:  rpc.DefaultRuceneServiceRPC,
	}
	s.UserFunc = s.userFunc
	s.AddCondition(condition.NewSavePlaylistControl("SaveRucene"))
	return s
}

func (s *SaveRuceneLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	// 异步写rucene
	go s.SaveData(ctx, requestCtx.GetBizContext().GetPlayListData())
	return nil
}

// 同一个answer可能有不同版本内容，hash值相同视为同一个doc
func (s *SaveRuceneLogic) generateDocID(ctx context.Context, questionDetail *model.RedisQuestionDetail, answerDetail *model.RedisAnswerDetail) string {
	hash := util.MD5(questionDetail.LabelContent + "|" + questionDetail.QuestionTitle + "|" + questionDetail.QuestionDetail + "|" + answerDetail.AnswerSummary)
	return answerDetail.AnswerID + "_" + hash
}

func (s *SaveRuceneLogic) docIDsExistInRucene(ctx context.Context, docIDs []string) (map[string]struct{}, error) {
	termQuerys := make([]client.Query, 0)
	for _, v := range docIDs {
		termQuery := client.Query{
			QueryType: client.QueryTypeTermQuery,
			TermQuery: &client.TermQuery{
				Field: conf.RuceneFieldDocID,
				Value: v,
			},
		}
		termQuerys = append(termQuerys, termQuery)
	}
	query := client.Query{
		QueryType: client.QueryTypeBooleanQuery,
		BooleanQuery: &client.BooleanQuery{
			Filters: []client.Query{{
				QueryType: client.QueryTypeBooleanQuery,
				BooleanQuery: &client.BooleanQuery{
					Shoulds: termQuerys,
				},
			}},
		},
	}
	request := &client.SearchQueryRequest{
		From:               0,
		Size:               len(docIDs),
		QueryDef:           query,
		StoreFields:        []string{conf.RuceneFieldAnswerID, conf.RuceneFieldDocID},
		TransportTimeoutMs: 500,
		EarlyTerminate:     10000,
	}
	result := make(map[string]struct{})
	resp, err := s.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), conf.RucenePath, conf.RuceneIndex, request)
	if err != nil {
		return nil, err
	}
	for _, v := range resp.Hits {
		result[v.StoreFields.GetString(conf.RuceneFieldAnswerID)] = struct{}{}
	}
	return result, nil
}

func (s *SaveRuceneLogic) batchGetSegment(ctx context.Context, logger *log.ZhihuLogger, texts []string) map[string][]*core_model.Word {
	groupGetFunc := func(ids interface{}) interface{} {
		textArr := ids.([]string)
		segmentMap := make(map[string][]*core_model.Word)
		for _, v := range textArr {
			if len(v) == 0 {
				continue
			}
			result := make([]*core_model.Word, 0)
			response := s.segmentRpc.Segment(ctx, v, "Common", true, true, true)
			if response == nil {
				logger.Errorf(ctx, "[SaveRuceneLogic] getSegment failed")
				return result
			}
			for _, item := range response.Words {
				if item.GrainType == 1 {
					result = append(result, &core_model.Word{
						Value:  item.Word,
						Begin:  item.PositionBegin,
						Length: item.Length,
					})
				}
			}
			segmentMap[v] = result
		}
		return segmentMap
	}
	batchSize := apollo.GetInt("segment_batch_size", conf.SegmentBatchSize)
	resultMap := make(map[string][]*core_model.Word)
	safe_group.BatchGet(batchSize, texts, groupGetFunc, &resultMap)
	return resultMap
}

func (s *SaveRuceneLogic) generateRuceneDoc(ctx context.Context, existMap map[string]struct{}, questionDetails []*model.RedisQuestionDetail, segmentMap map[string][]*core_model.Word, createTime int64) []*model.RuceneDoc {
	ruceneDocs := make([]*model.RuceneDoc, 0)
	for _, question := range questionDetails {
		for _, answer := range question.Answers {
			if _, ok := existMap[answer.AnswerID]; !ok {
				answerDoc := &model.RuceneDoc{
					AnswerID: answer.AnswerID,
					DocId:    s.generateDocID(ctx, question, answer),
					ParentID: question.QuestionID,
					QuestionTitle: core_model.SegmentInfo{
						Words: segmentMap[question.QuestionTitle],
						Raw:   question.QuestionTitle,
						Store: true,
					},
					Theme: core_model.SegmentInfo{
						Words: segmentMap[question.LabelContent],
						Raw:   question.LabelContent,
						Store: true,
					},
					Summary: core_model.SegmentInfo{
						Words: segmentMap[answer.AnswerSummary],
						Raw:   answer.AnswerSummary,
						Store: true,
					},
					QuesSummary: core_model.SegmentInfo{
						Words: segmentMap[question.QuestionDetail],
						Raw:   question.QuestionDetail,
						Store: true,
					},
					AuthorID:   answer.AnswerAuthorHashID,
					CreateTime: createTime,
				}
				ruceneDocs = append(ruceneDocs, answerDoc)
			}
		}
	}
	return ruceneDocs
}

func (s *SaveRuceneLogic) saveRucene(ctx context.Context, logger *log.ZhihuLogger, ruceneDocs []*model.RuceneDoc) {
	ruceneBatchSize := apollo.GetInt("rucene_batch_size", conf.RuceneBatchSize)
	groupDoFunc := func(ids interface{}) {
		docs := ids.([]*model.RuceneDoc)
		for _, doc := range docs {
			err := s.ruceneRpc.Add(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), conf.RucenePath, conf.RuceneIndex, doc, "")
			if err != nil {
				logger.Errorf(ctx, "[SaveRuceneLogic] rucene add err: %v", err)
				statsd.Increment("ai-daily-web.save_data.write_rucene.error.count")
			}
		}
	}
	safe_group.WindowGroupDo(ruceneBatchSize, ruceneDocs, groupDoFunc)
}

func (s *SaveRuceneLogic) SaveData(ctx context.Context, playListData *model.PlayListData) error {
	defer func() {
		if r := recover(); r != nil {
			log.Errorf(ctx, "[SaveRuceneLogic] saveData panic: %v", r)
		}
	}()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.save_rucene", time.Since(start).Milliseconds())
	}()
	logger := log.WithFields(ctx, map[string]interface{}{
		"token": playListData.HashToken,
	})
	docIDs := make([]string, 0)
	for _, question := range playListData.FinalQuestionDetails {
		for _, answer := range question.Answers {
			docIDs = append(docIDs, s.generateDocID(ctx, question, answer))
		}
	}
	// 判断是否已经写过，返回answerID
	existMap, err := s.docIDsExistInRucene(ctx, docIDs)
	if err != nil {
		logger.Errorf(ctx, "[SaveRuceneLogic] search rucene failed.err=%v", err)
		statsd.Increment("ai-daily-web.save_data.search_rucene.error.count")
		return err
	}
	texts := make([]string, 0)
	questionAddMap := make(map[string]struct{})
	for _, question := range playListData.FinalQuestionDetails {
		for _, answer := range question.Answers {
			if _, ok := existMap[answer.AnswerID]; !ok {
				if _, ok2 := questionAddMap[question.QuestionID]; !ok2 {
					texts = append(texts, question.QuestionDetail)
					texts = append(texts, question.LabelContent)
					texts = append(texts, question.QuestionTitle)
					questionAddMap[question.QuestionID] = struct{}{}
				}
				texts = append(texts, answer.AnswerSummary)
			}
		}
	}
	if len(texts) == 0 {
		return nil
	}
	// 获取分词信息
	segmentMap := s.batchGetSegment(ctx, logger, texts)
	// 生成ruceneDoc
	ruceneDocs := s.generateRuceneDoc(ctx, existMap, playListData.FinalQuestionDetails, segmentMap, playListData.CardGenerateTime.Unix())
	s.saveRucene(ctx, logger, ruceneDocs)
	return nil
}
