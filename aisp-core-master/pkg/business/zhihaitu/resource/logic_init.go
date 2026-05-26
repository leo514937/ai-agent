package resources

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/logic/retrieval"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/logic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

var sceneName = graph_constant.ApiZhihaituChat

var initOnce = util.Make(func() interface{} {
	log.Infof(context.Background(), "PutLogic start")
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.UserMessageLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewUserMessageLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.ChatHistoryLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewChatHistoryLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&query_merge.QueryMergeLogic{}, func(name string, config map[string]string) interface{} {
		return query_merge.NewQueryMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prompt.BuildPromptLogic{}, func(name string, config map[string]string) interface{} {
		return prompt.NewBuildPromptLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.AsyncChatRespLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewAsyncChatRespLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&generate.ChatByModelGatewayLogic{}, func(name string, config map[string]string) interface{} {
		return generate.NewChatByModelGatewayLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&condition.IfElseConditionLogic{}, func(name string, config map[string]string) interface{} {
		return condition.NewIfElseConditionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&condition.IfElseMultiConditionLogic{}, func(name string, config map[string]string) interface{} {
		return condition.NewIfElseMultiConditionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.BuildChatResponseBaseLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewBuildChatResponseBaseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.BuildResponseLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewBuildResponseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.RedLineLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewRedLineLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.KnowledgeEnhanceLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewKnowledgeEnhanceLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.FAQLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewFAQLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.SecurityReviewLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewSecurityReviewLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.SecurityReviewBaseLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewSecurityReviewBaseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.ExternalSiteableRetrievalLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewExternalSiteableRetrievalLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&retrieval.RetrievalMergeLogic{}, func(name string, config map[string]string) interface{} {
		return retrieval.NewRetrievalMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&empty.EmptyBaseLogic{}, func(name string, config map[string]string) interface{} {
		return empty.NewEmptyBaseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&util2.RecordLogic{}, func(name string, config map[string]string) interface{} {
		return util2.NewRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&util2.RecordUpdateLogic{}, func(name string, config map[string]string) interface{} {
		return util2.NewRecordUpdateLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&util2.ReportAnswerLogic{}, func(name string, config map[string]string) interface{} {
		return util2.NewReportAnswerLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&util2.ReportQuestionLogic{}, func(name string, config map[string]string) interface{} {
		return util2.NewReportQuestionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prompt.QueryPromptBaseLogic{}, func(name string, config map[string]string) interface{} {
		return prompt.NewQueryPromptBaseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&consumer.SaveDialogRecordLogic{}, func(name string, config map[string]string) interface{} {
		return consumer.NewSaveDialogRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.DefItemRespLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewDefItemRespLogic(name, config)
	})
	log.Infof(context.Background(), "PutLogic end")

	log.Infof(context.Background(), "InitZagDriver start")
	graph.InitZagDriver(sceneName)
	log.Infof(context.Background(), "InitZagDriver end")

	return nil
})

func Init(scene string) interface{} {
	sceneName = scene
	log.Infof(context.Background(), "initOnce: %s", sceneName)

	return initOnce()
}
