package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/logic/choose"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&choose.RequestKeyVerifyLogic{}, func(name string, config map[string]string) interface{} {
		return choose.NewRequestKeyVerifyLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.ZhidaMCPRecallLimitLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewZhidaMCPRecallLimitLogic(name, config)
	})
}
