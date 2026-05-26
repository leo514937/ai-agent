package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/logic/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&generate.DirectChatLogic{}, func(name string, config map[string]string) interface{} {
		return generate.NewDirectChatLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.UniversalBaseInfoLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewUniversalBaseInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.PreparerDataTidyLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewPreparerDataTidyLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.KbDeepSearchAfterHandlerLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewKbDeepSearchAfterHandlerLogic(name, config)
	})
}
