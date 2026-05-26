package resources

import (
	"sync"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

var (
	initOnce sync.Once
)

func InitAIDailyLogic() {
	initOnce.Do(func() {
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.PrepareLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewPrepareLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetPlaylistLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetPlaylistLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetMostLikeQuestionsLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetMostLikeQuestionsLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetQuestionByThemeIDLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetQuestionByThemeIDLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetQuestionDetailLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetQuestionDetailLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetThemeLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetThemeLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.CalcQuestionSimLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewCalcQuestionSimLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.CalcThemeSimLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewCalcThemeSimLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.ContentRegulateLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewContentRegulateLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SecurityRegulateLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewSecurityRegulateLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SelectDataLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewSelectDataLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetAnswerAuthorLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetAnswerAuthorLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetUserInfoLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetUserInfoLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetViewedQuestionsLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetViewedQuestionsLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetQuestionByHighLabelsLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetQuestionByHighLabelsLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.ParsePlaylistLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewParsePlaylistLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.PackageResponseLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewPackageResponseLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SavePlaylistLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewSavePlaylistLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SaveTiDBQuestionLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewSaveTiDBQuestionLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SaveRuceneLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewSaveRuceneLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.GetDataAfterFilterLogic{}, func(name string, config map[string]string) interface{} {
			return logic.NewGetDataAfterFilterLogic(name, config)
		})
		logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&empty.EmptyBaseLogic{}, func(name string, config map[string]string) interface{} {
			return empty.NewEmptyBaseLogic(name, config)
		})
	})
}
