package process

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/stream"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/zhida"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

const hoteventScene = "kafka.hotevent"

type HotEventIndexProcessor struct {
	redisDao             dao.HotEventIndexDao
	rumClient            rpc.RumClient[float32]
	rumCache             rum_cache.RumCache
	klaraEmbeddingClient rpc.KlaraRpcClient
	modelGatewayRPC      *rpc.ModelGatewayRouter
	wordWrapperService   word.WordMapperService
}

func NewHotEventIndexProcessor() *HotEventIndexProcessor {
	return &HotEventIndexProcessor{
		redisDao:             impl.DefaultHotEventIndexDaoImpl,
		rumClient:            rpcImpl.DefaultFloat32RumClientImpl,
		rumCache:             rum_cache.NewRumCache(),
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("ensemble_offline"),
		modelGatewayRPC:      rpc.DefaultModelGatewayRouter,
		wordWrapperService:   word.NewWordMapperService(),
	}
}

func (h *HotEventIndexProcessor) TopicName() macro.TopicName {
	return macro.HotEvent
}

func (h *HotEventIndexProcessor) Process(ctx context.Context, message *stream.Message) error {
	msg := &module.HotEventKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".unmarshal.count", hoteventScene))
		return errors.New("unmarshal error")
	}

	// 根据 msg.HotEvent.IsAbandon 来区分 upsert or delete
	if msg.HotEvent.IsAbandon == module.Yes {
		// 删除操作
		h.delWord(ctx, msg.HotEvent.HotSpotName, msg.HotEvent.Id)
	} else if msg.HotEvent.IsAbandon == module.No && msg.HotEvent.IsFollowed == module.Yes && msg.HotEvent.IsOperation == module.Yes {
		// upsert 操作
		h.upsertWord(ctx, msg.HotEvent.HotSpotName, msg.HotEvent.Id)
	}

	return nil
}

func (h *HotEventIndexProcessor) upsertWord(ctx context.Context, word string, originId int64) {
	wordId := h.redisDao.GetWordOriginId2WordId(ctx, originId)
	log.Infof(ctx, "[HotEvent] Upsert PrefabWordToRum wordId: %d, word: %s, originId:%d", wordId, word, originId)

	var syncStatus, method string

	if wordId == 0 {
		// 没有词 id，词新增流程
		isok := h.insertWord(ctx, word, originId)
		if isok {
			syncStatus = "succ"
		} else {
			syncStatus = "fail"
		}
		method = "insert"
	} else {
		// 存在词 id，词更新流程
		isok, affectedRows := h.updateWord(ctx, word, wordId)
		if isok {
			syncStatus = "succ"
		} else {
			syncStatus = "fail"
		}
		if affectedRows > 0 {
			method = "update"
		} else {
			method = "duplicate"
		}
	}

	statsd.Increment(fmt.Sprintf(macro.OriginCommonStatsPrefix+".%s.%s.count", hoteventScene, method, syncStatus))
}

// 词新增流程：判断时效性-> 新增 mysql 获取词 id -> 写 rum -> 存储 redis word 时效情况，存 redis word id 映射关系
func (h *HotEventIndexProcessor) insertWord(ctx context.Context, word string, wordOriginId int64) bool {
	// 写 mysql
	wordId, err := h.wordWrapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
		Word:     word,
		WordType: int32(proto.QueryType_RELATE_WORD_HOT_EVENT),
		SourceId: util.Int64String(wordOriginId),
	})
	if err != nil || wordId == 0 {
		log.Errorf(ctx, "insert word error:%+v", err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".insert_mysql.count", hoteventScene))
		return false
	}

	// 写 rum
	isSucc := h.syncRum(ctx, word, wordId)

	// 存储词的时效性情况
	err = h.redisDao.SetWordCreateTimeAndTimeliness(ctx, wordId, macro.TimelinessShort)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".set_redis.count", hoteventScene))
	}

	// 存储词 id 映射关系
	err = h.redisDao.SetWordOriginId2WordId(ctx, wordOriginId, wordId)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".set_redis.count", hoteventScene))
	}
	return isSucc
}

// 词更新流程：更新 mysql -> 写 rum -> 存储 redis word 时效情况
func (h *HotEventIndexProcessor) updateWord(ctx context.Context, word string, wordId int64) (bool, int64) {
	affectedRows, err := h.wordWrapperService.UpdateWordById(ctx, wordId, word)
	if err != nil {
		log.Errorf(ctx, "update word error:%+v", err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".update_mysql.count", hoteventScene))
		return false, 0
	} else if affectedRows == 0 {
		return true, affectedRows
	}

	isSucc := h.syncRum(ctx, word, wordId)

	err = h.redisDao.SetWordCreateTimeAndTimeliness(ctx, wordId, macro.TimelinessShort)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".set_redis.count", hoteventScene))
	}
	return isSucc, affectedRows
}

func (h *HotEventIndexProcessor) delWord(ctx context.Context, word string, wordOriginId int64) {
	wordId := h.redisDao.GetWordOriginId2WordId(ctx, wordOriginId)
	if wordId == 0 {
		return
	}
	log.Infof(ctx, "[HotEvent] Del PrefabWordToRum wordId: %d, word: %s", wordId, word)
	// 删除 MySQL
	_, deleteMySQLErr := h.wordWrapperService.RemoveWordId(ctx, wordId, int32(proto.QueryType_RELATE_WORD_HOT_EVENT))
	// 删除 rum
	actionRes := h.rumClient.RumDelete(ctx, macro.AiPrefabWordV3RumTable, wordId, "")
	// 清除词缓存（判断是否是预制词）
	resource.RedisLocalCache.BatchDelete(ctx, []string{word}, util.StringKeyGeneratorFunc, util.SuggestQueriesKeyOption)
	if !actionRes || deleteMySQLErr != nil {
		// 保存删除错误记录到 redis中 便于后期进行后过滤(只有异常情况下才会有记录)
		h.rumCache.SaveDeleteErrorCache(ctx, wordId, macro.AiPrefabWordV3RumTable)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".del.count", hoteventScene))
		log.Errorf(ctx, "Del PrefabWordToRum Err wordId: %d, word: %s, rum del:%v, mysql err:%v", wordId, word, actionRes, deleteMySQLErr)
	} else {
		statsd.Increment(fmt.Sprintf(macro.OriginCommonStatsPrefix+".del.succ.count", hoteventScene))
		log.Infof(ctx, "Del PrefabWordToRum wordId: %d, word: %s success", wordId, word)
	}
}

func (h *HotEventIndexProcessor) syncRum(ctx context.Context, word string, wordId int64) bool {
	embeddings := h.klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{word})
	if len(embeddings) != 1 {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".get_emb.count", hoteventScene))
		log.Errorf(ctx, "embedding result count is:%d", len(embeddings))
		return false
	}

	raw := &model.PrefabWordExtraInfo{Word: word}

	resp := h.rumClient.RumUpsert(ctx, macro.AiPrefabWordV3RumTable, wordId, embeddings[0], "", map[string]interface{}{
		macro.PrefabWordQueryTypeFieldName: proto.QueryType_RELATE_WORD_HOT_EVENT,
		macro.PrefabWordRawFieldName:       util.GetJSONIgnoreError(raw),
	})

	if resp == false {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".sync_rum.count", hoteventScene))
		log.Errorf(ctx, "upsert rum table:%s id:%d failed", macro.AiPrefabWordV3RumTable, wordId)
	}
	return resp
}

// 2024.8.27 更新，时效性模型判断完基本都是无时效，临时下线，热点事件消息流过来的，全按短时效处理
func (h *HotEventIndexProcessor) getTimeliness(ctx context.Context, query string) macro.TimelinessType {
	promptInput := model.PromptInput{
		Query: query,
	}

	promptContent, err := model.GenPrompt(&promptInput, conf.PromptByTimeLimitationJudgment, "1001")
	if err != nil {
		log.Errorf(ctx, "BuildPromptLogic buildPrompt template parse error: %+v", err)
		return ""
	}

	messages := []*dto.ChatRequestMessage{{
		Content: promptContent,
		Role:    dto.ChatRequestMessageRoleUser,
	}}

	req := &dto.ChatRequest{
		ModelName:   "timeliness-for-zhida",
		AIProfile:   conf.PromptBySystem,
		Messages:    messages,
		MaxTokens:   lo.ToPtr[int32](128),
		Stop:        []string{"<|im_end|>"},
		Temperature: lo.ToPtr[float32](1.0),
	}

	response, err := h.modelGatewayRPC.Chat(ctx, req)

	if err != nil || response == nil {
		return ""
	}

	return macro.TimelinessType(response.Content)
}
