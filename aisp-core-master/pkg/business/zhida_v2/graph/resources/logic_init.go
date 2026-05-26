package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.RequestConfigLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewRequestConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.UniversalBaseInfoLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewUniversalBaseInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.MountDoc2SpecifiedDocRecallLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewMountDoc2SpecifiedDocRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.RefProducerBeginLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewRefProducerBeginLogic(name, config)
	})
}
