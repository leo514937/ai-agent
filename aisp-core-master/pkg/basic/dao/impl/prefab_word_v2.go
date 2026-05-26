package impl

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

const (
	// prefabWordAndSourceV2RedisKey redis key
	prefabWordAndSourceV2RedisKey = "prefab_word_and_source_v2"
	// prefabWordSetRedisV2Key redis key
	prefabWordSetRedisV2Key = "prefab_word_set_v2"
)

func NewPrefabWordV2Dao() dao.PrefabWordV2Dao {
	return &PrefabWordV2DaoImpl{
		redisClient: resource.RedisByPrefabWord,
		ttl:         90 * 24 * time.Hour,
	}
}

type PrefabWordV2DaoImpl struct {
	redisClient redis.Client
	ttl         time.Duration
}

func (p *PrefabWordV2DaoImpl) SavePrefabWordV2ToRedisSet(ctx context.Context, queryType proto.QueryType,
	word *model.PrefabWord) error {
	jsonString, jsonStringErr := word.ToJsonString()
	if jsonStringErr != nil {
		return jsonStringErr
	}

	pipe := p.redisClient.Pipeline()
	pipe.SAdd(ctx, p.getSetRedisKey(prefabWordSetRedisV2Key, queryType), word.DocId)
	pipe.Expire(ctx, p.getSetRedisKey(prefabWordSetRedisV2Key, queryType), p.ttl)
	pipe.Set(ctx, p.getKvRedisKey(prefabWordAndSourceV2RedisKey, queryType, word.DocId), jsonString, p.ttl)
	// 执行Pipeline
	_, err := pipe.Exec(ctx)
	return err
}

func (p *PrefabWordV2DaoImpl) GetRandomPrefabWordV2ByRedis(ctx context.Context, maxLimit int64, queryType proto.QueryType) []*model.PrefabWord {
	if maxLimit <= 0 {
		return []*model.PrefabWord{}
	}

	setKey := p.getSetRedisKey(prefabWordSetRedisV2Key, queryType)
	randomWordIds, randomWordsErr := p.redisClient.SRandMemberN(ctx, setKey, maxLimit).Result()
	if randomWordsErr != nil {
		return []*model.PrefabWord{}
	}

	prefabWords, prefabWordsErr := p.mGetSourceQuestion(ctx, proto.QueryType_PREFAB_WORD_QUESTION, randomWordIds)
	if prefabWordsErr != nil {
		return []*model.PrefabWord{}
	}
	return prefabWords
}

func (p *PrefabWordV2DaoImpl) GetRandomPrefabQueryV2ByRedis(ctx context.Context, maxLimit int64, queryType proto.QueryType) []*proto.Query {
	words := make([]*proto.Query, 0)
	if maxLimit <= 0 {
		return words
	}

	setKey := p.getSetRedisKey(prefabWordSetRedisV2Key, queryType)
	randomWordIds, randomWordsErr := p.redisClient.SRandMemberN(ctx, setKey, maxLimit).Result()
	if randomWordsErr != nil {
		return words
	}

	prefabWords, prefabWordsErr := p.mGetSourceQuestion(ctx, proto.QueryType_PREFAB_WORD_QUESTION, randomWordIds)
	if prefabWordsErr != nil {
		return words
	}
	return p.HandleToConvertQuery(prefabWords)
}

func (p *PrefabWordV2DaoImpl) HandleToConvertQuery(prefabWords []*model.PrefabWord) []*proto.Query {
	words := make([]*proto.Query, 0)
	// 词再去重 防止优质内容与热榜重复
	unionWords := lo.UniqBy(prefabWords, func(w *model.PrefabWord) interface{} {
		return w.AiRewriteQuestion
	})

	// 根据原始问题分组去重
	groupWordsBySourceQuestion := lo.GroupBy(unionWords, func(w *model.PrefabWord) interface{} {
		return w.SourceQuestion
	})
	for k, ws := range groupWordsBySourceQuestion {
		if k == "" {
			for _, w := range ws {
				words = append(words, &proto.Query{
					Id:        cast.ToString(w.DocId),
					Query:     w.AiRewriteQuestion,
					QueryType: w.QueryType,
					RiskType:  macro.CensorTypeMap[w.QueryType]})
			}
			continue
		}
		words = append(words, &proto.Query{
			Id:        cast.ToString(ws[0].DocId),
			Query:     ws[0].AiRewriteQuestion,
			QueryType: ws[0].QueryType,
			RiskType:  macro.CensorTypeMap[ws[0].QueryType]})
	}
	return words
}

func (p *PrefabWordV2DaoImpl) HandleToConvertQueryV2(prefabWords []*model.PrefabWordInfo) []*proto.Query {
	words := make([]*proto.Query, 0)
	// 词再去重，防止不同类型词重复
	unionWords := lo.UniqBy(prefabWords, func(w *model.PrefabWordInfo) interface{} {
		return w.Word
	})

	// 比较业务的去重逻辑：原始问题去重
	uniqueSourceQuestionMap := map[string]bool{}

	for _, word := range unionWords {
		sourceQuestion := word.ExtraInfo.GetSourceQuestion()
		if sourceQuestion != "" {
			if !uniqueSourceQuestionMap[sourceQuestion] {
				words = append(words, prefabWordInfo2Query(word))
				uniqueSourceQuestionMap[sourceQuestion] = true
			}
		} else {
			words = append(words, prefabWordInfo2Query(word))
		}
	}

	return words
}
func prefabWordInfo2Query(prefabWord *model.PrefabWordInfo) *proto.Query {
	return &proto.Query{
		Id:        cast.ToString(prefabWord.WordId),
		QueryType: prefabWord.QueryType,
		Query:     prefabWord.Word,
		RiskType:  macro.CensorTypeMap[prefabWord.QueryType],
	}
}

func (p *PrefabWordV2DaoImpl) mGetSourceQuestion(ctx context.Context, queryType proto.QueryType, qiWordIds []string) ([]*model.PrefabWord, error) {
	if qiWordIds == nil || len(qiWordIds) == 0 {
		return []*model.PrefabWord{}, nil
	}

	keys := make([]string, 0)
	for _, w := range qiWordIds {
		keys = append(keys, p.getKvRedisKey(prefabWordAndSourceV2RedisKey, queryType, cast.ToInt64(w)))
	}

	res, err := p.redisClient.MGet(ctx, keys...).Result()
	if err != nil {
		log.Errorf(ctx, "GetRandomPrefabWordByRedis(MGet) Err => %v", err)
		return []*model.PrefabWord{}, err
	}

	prefabWords := make([]*model.PrefabWord, 0)
	for _, sourceQuestion := range res {
		if sourceQuestion == nil {
			continue
		}

		prefabWord, prefabWordErr := model.ParsePrefabWord(sourceQuestion.(string))
		if prefabWordErr != nil {
			continue
		}
		prefabWords = append(prefabWords, prefabWord)
	}
	return prefabWords, nil
}

func (p *PrefabWordV2DaoImpl) RemovePrefabWordV2Redis(ctx context.Context, queryType proto.QueryType, wordId int64) error {
	setKey := p.getSetRedisKey(prefabWordSetRedisV2Key, queryType)
	kvKey := p.getKvRedisKey(prefabWordAndSourceV2RedisKey, queryType, wordId)
	pipe := p.redisClient.Pipeline()
	pipe.SRem(ctx, setKey, wordId)
	pipe.Del(ctx, kvKey)
	_, err := pipe.Exec(ctx)
	return err
}

func (p *PrefabWordV2DaoImpl) RemoveAllRedisV2ByType(ctx context.Context, queryType proto.QueryType) error {
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeProcessor",
		"func":  "RemoveAllRedisByType",
	})

	setKey := p.getSetRedisKey(prefabWordSetRedisV2Key, queryType)

	res, sErr := p.redisClient.SMembers(ctx, setKey).Result()
	if sErr != nil {
		logger.Errorf(ctx, "SMembers error => %v", sErr)
	}

	// 如果有匹配的键，则执行删除操作
	if len(res) > 0 {
		kvKeys := make([]string, 0)
		for _, wordId := range res {
			kvKey := p.getKvRedisKey(prefabWordAndSourceV2RedisKey, queryType, cast.ToInt64(wordId))
			kvKeys = append(kvKeys, kvKey)
		}
		// 使用DEL命令删除匹配的键
		delCmd := p.redisClient.Del(ctx, kvKeys...)
		if err := delCmd.Err(); err != nil {
			logger.Errorf(ctx, "DEL error => %v", err)
		}
	}
	_, err := p.redisClient.Del(ctx, setKey).Result()
	return err
}

func (p *PrefabWordV2DaoImpl) getSetRedisKey(key string, queryType proto.QueryType) string {
	return fmt.Sprintf("%s:%s", key, queryType.String())
}

func (p *PrefabWordV2DaoImpl) getKvRedisKey(key string, queryType proto.QueryType, wordId int64) string {
	return fmt.Sprintf("%s:%s:%d", key, queryType.String(), wordId)
}
