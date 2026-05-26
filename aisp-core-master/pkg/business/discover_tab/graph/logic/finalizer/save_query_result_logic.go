package finalizer

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// SaveQueryResultLogic 针对引导词进来的请求，缓存住返回结果，用于下次请求相同 query 直接返回
// @logicAuthor: wangran
// @logicInfo: 针对引导词进来的请求，缓存住返回结果，用于下次请求相同 query 直接返回
// @logicInput: 0 | query string
// @logicInput: 1 | scene string
// @logicInput: 2 | 回答是否命中了缓存 bool
// @logicInput: 3 | query是否通过了所有安全相关的校验 bool
// @logicInput: 4 | queryMerge是否通过了所有安全相关的校验 bool
// @logicInput: 5 | 回答是否通过了所有安全模型的校验 bool
// @logicInput: 6 | 召回items合并截断后的结果 []*data_frame.ItemData[entities.Item]
// @logicInput: 7 | 相关词 []*proto.Query
// @logicOutput: 无
type SaveQueryResultLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	wordService word_service.WordMapperService
	redisDao    dao.QueryResultDao
	defCacheTTL int64
}

func NewSaveQueryResultLogic(name string, config map[string]string) *SaveQueryResultLogic {
	res := &SaveQueryResultLogic{
		BaseLogic:   logic.NewBaseLogic[entities.RequestContext](name, config),
		wordService: word_service.DefaultWordMapperService,
		redisDao:    impl.DefaultQueryResultDaoImpl,
	}
	res.RealDoFunc = res.consume
	res.defCacheTTL = 21600
	return res
}

func (q *SaveQueryResultLogic) consume(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "finalizer.QueryResultLogic.consume")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogMemberId(requestCtx.GetBizContext().MemberId()))

	// 开关控制是否存引导词请求结果，开发调试时开启
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen {
		return nil
	}

	query, _ := requestCtx.DataMap().GetString(logCtx, q.GetInputName(0))
	scene := requestCtx.GetBizContext().Scenes()
	hitResponseCache, _ := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(2))
	querySecurityAllPassed, _ := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(3))
	queryMergeSecurityAllPassed, _ := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(4))
	answerSecurityPassed, _ := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(5))

	newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 2*time.Second)
	defer cancel()

	constant.DataInputNodeLog.Infof(logCtx, "%s", query)

	// 命中缓存 或 被安全拒答、命中红线必答、faq、历史上下文长度不为0、是否通过前置检查 的不缓存结果
	if !requestCtx.GetBizContext().IsEnableCache() ||
		hitResponseCache ||
		!querySecurityAllPassed ||
		!queryMergeSecurityAllPassed ||
		!answerSecurityPassed ||
		len(requestCtx.GetBizContext().GetRealHistoryDialogue()) != 0 ||
		!q.wordService.IsWordByBefore(query) {
		macro.ProcessNodeLog.Infof(logCtx, "不缓存结果: 前置检查不通过，不满足以下判断 => {命中缓存或被安全拒答、命中红线必答、faq、历史上下文长度不为0、是否通过前置检查}")
		return nil
	}

	// 判断是否只缓存预制词
	chatQueryCacheIsOnlyPrefabWord := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert()))
	if chatQueryCacheIsOnlyPrefabWord {
		// 判断用户输入 query 是否来自引导词，只有引导词缓存结果
		isPrefabWord := q.wordService.IsPrefabWord(newCtx, query)
		if !isPrefabWord {
			// 打点记录
			macro.ProcessNodeLog.Infof(logCtx, "不是引导词")
			util.Increment(ctx, macro.CommonStatsPrefix+".chat.is_word_prefab.%s", cast.ToString(isPrefabWord))
			return nil
		}
		macro.ProcessNodeLog.Infof(logCtx, "是引导词")
		util.Increment(ctx, macro.CommonStatsPrefix+".chat.is_word_prefab.%s", cast.ToString(isPrefabWord))
	}

	// 获取最后的resp
	responseInfo := requestCtx.GetBizContext().GetChatEventResponseHandler().TransitionSource(requestCtx.GetBizContext().GetChatEvent().GetAllEventData(), true, nil)
	if responseInfo == nil {
		return nil
	}

	chatModel := requestCtx.GetBizContext().GetCustomChatModel().String()
	clientSource := requestCtx.GetBizContext().RequestHeader().GetClientSource().String()
	trafficSource := requestCtx.GetBizContext().RequestHeader().GetTrafficSource().String()

	// 流量来源缓存时效 TTL
	secTTL, _ := requestCtx.GetBizContext().GetChatCacheSecTTLByTrafficSource()
	// 如果小于 0 ，则认为是默认不启用缓存 比如 -1
	if secTTL < 0 {
		// 打点记录
		macro.ProcessNodeLog.Infof(logCtx, "ttl 小于 0，不启用缓存")
		return nil
	}

	cacheQuery := query
	// 2024-09-23 14:49:15
	// 如果是实体词场景 缓存为 query:docId:docType:matchOrder
	chatExtraInfo := requestCtx.GetBizContext().GetChatExtraInfo()
	sourceContent := chatExtraInfo.GetSourceContent()
	if lo.Contains(graphUtil.GetEntityTrafficSources(), requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) &&
		sourceContent != nil && sourceContent.GetDocId() > 0 {
		cacheQuery = fmt.Sprintf("%s:%d:%s:%d", query, sourceContent.GetDocId(), sourceContent.GetDocType().String(), chatExtraInfo.GetMatchOrder())
	}

	abMap := requestCtx.GetBizContext().GetAbParamAllValueWithoutDefaultFlattened()
	// 存储返回值信息
	err := q.redisDao.SetResponseInfoByTTL(newCtx, scene, clientSource, trafficSource, chatModel, abMap, cacheQuery, responseInfo, time.Duration(secTTL)*time.Second)
	if err != nil {
		span.LogFields(log.Message("redis set error"), log.ErrorField(err))
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(responseInfo))

	return err
}
