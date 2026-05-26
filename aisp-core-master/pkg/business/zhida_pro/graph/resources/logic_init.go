package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/judge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&judge.DocRouterJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return judge.NewDocRouterJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ChunkRecallFetchLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewChunkRecallFetchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ChunkRerankFetchLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewChunkRerankFetchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.SpecifiedDocRecallLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewSpecifiedDocRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.KbRecallChunkAndReRankAfterLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewKbRecallChunkAndReRankAfterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.SpecifiedDocOverwriteConfigLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewSpecifiedDocOverwriteConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.RequestConfigLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewRequestConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.InternalDocMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewInternalDocMetaFetcherLogic(name, config)
	})

}
