package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/extra_answer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	aiTabRerank "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.TracingRecordLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewTracingRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.RecallTracingRecordLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewRecallTracingRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.SaveQueryResultLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewSaveQueryResultLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.LastNRecordLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewLastNRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.RequestConfigLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewRequestConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.QueryDefinitionLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewQueryDefinitionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&aiTabRerank.AuthorMergeLogic{}, func(name string, config map[string]string) interface{} {
		return aiTabRerank.NewAuthorMergeLogic(name, config)
	})

	// 追问相关词 缓存
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.SaveRelatedWordCacheLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewSaveRelatedWordCacheLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.GetRelatedWordCacheLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewGetRelatedWordCacheLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.RelatedWordDisassemblyInfoLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewRelatedWordDisassemblyInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.RelatedWordContentCovertLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewRelatedWordContentCovertLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.SearchRelatedWordRecallCacheLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewSearchRelatedWordRecallCacheLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.SearchRelatedWordRecallFilterLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewSearchRelatedWordRecallFilterLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&extra_answer.ExtraAnswerContentCovertLogic{}, func(name string, config map[string]string) interface{} {
		return extra_answer.NewExtraAnswerContentCovertLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.LoadApolloConfigLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewLoadApolloConfigLogic(name, config)
	})
}
