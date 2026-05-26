package resources

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/finalizer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/generate_post"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/intention"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/prepare"
	digitalAuthorPrompt "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/recall_merge"
	digitalAuthorResp "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/task"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

func init() {
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.AuthorMetaLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewAuthorMetaLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prepare.DigitalAuthorChatHistoryLogic{}, func(name string, config map[string]string) interface{} {
		return prepare.NewDigitalAuthorChatHistoryLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&digitalAuthorResp.DigitalAuthorBuildResponseLogic{}, func(name string, config map[string]string) interface{} {
		return digitalAuthorResp.NewDigitalAuthorBuildResponseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.UspScoreLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewUspScoreLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&intention.IntentionJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return intention.NewIntentionJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&intention.AlreadyIntentionJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return intention.NewAlreadyIntentionJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.SearchIntentionLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewSearchIntentionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.UcpTagLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewUcpLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.KlaraEmbeddingFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewKlaraEmbeddingFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.QuKeywordFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewQuKeywordFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.UnifiedEmbeddingFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewUnifiedEmbeddingFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ContentCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewContentCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ParentContentCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewParentContentCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall_merge.RecallMergeLogic{}, func(name string, config map[string]string) interface{} {
		return recall_merge.NewRecallMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.ExternalTracingRecordLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewTracingRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&digitalAuthorPrompt.BuildDigitalAuthorPromptLogic{}, func(name string, config map[string]string) interface{} {
		return digitalAuthorPrompt.NewBuildDigitalAuthorPromptLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&task.TaskFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return task.NewTaskFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&intention.Task2SummaryJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return intention.NewTask2SummaryJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.MultiChatSummaryLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewMultiChatSummaryLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&filter.IndexDeleteFilterLogic{}, func(name string, config map[string]string) interface{} {
		return filter.NewIndexDeleteFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&finalizer.InternalTracingRecordLogic{}, func(name string, config map[string]string) interface{} {
		return finalizer.NewInternalTracingRecordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&generate_post.ChatPostLogic{}, func(name string, config map[string]string) interface{} {
		return generate_post.NewChatPostLogic(name, config)
	})
}
