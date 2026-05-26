package impl

import (
	"context"
	"encoding/base64"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
)

const (
	// prefabWordAndSourceRedisKey redis key
	prefabWordAndSourceRedisKey = "prefab_word_and_source"
	// prefabWordSetRedisKey redis key
	prefabWordSetRedisKey = "prefab_word_set"
)

func NewPrefabWordDao() dao.PrefabWordDao {
	return &PrefabWordDaoImpl{
		redisClient: resource.RedisByPrefabWord,
		ttl:         90 * 24 * time.Hour,
	}
}

type PrefabWordDaoImpl struct {
	redisClient redis.Client
	ttl         time.Duration
}

func (p *PrefabWordDaoImpl) getSetRedisKey(key string, queryType proto.QueryType) string {
	return fmt.Sprintf("%s:%s", key, queryType.String())
}

func (p *PrefabWordDaoImpl) getKvRedisKey(key string, queryType proto.QueryType, AiQuestion string) string {
	aiQuestionByBase64 := base64.StdEncoding.EncodeToString([]byte(AiQuestion))
	return fmt.Sprintf("%s:%s:%s", key, queryType.String(), aiQuestionByBase64)
}

func (p *PrefabWordDaoImpl) SavePrefabWordToRedisSet(ctx context.Context, queryType proto.QueryType,
	word *dao.PrefabWord) error {

	pipe := p.redisClient.Pipeline()
	pipe.SAdd(ctx, p.getSetRedisKey(prefabWordSetRedisKey, queryType), word.AiQuestion)
	pipe.Expire(ctx, p.getSetRedisKey(prefabWordSetRedisKey, queryType), p.ttl)
	pipe.Set(ctx, p.getKvRedisKey(prefabWordAndSourceRedisKey, queryType, word.AiQuestion), word.SourceQuestion, p.ttl)
	// 执行Pipeline
	_, err := pipe.Exec(ctx)
	return err
}

func (p *PrefabWordDaoImpl) GetRandomPrefabWordByRedis(ctx context.Context, maxLimit int64) []string {
	queryByRedis := p.GetRandomPrefabQueryByRedis(ctx, maxLimit)
	words := make([]string, 0)
	for _, w := range queryByRedis {
		words = append(words, w.Query)
	}
	return words
}

func (p *PrefabWordDaoImpl) GetRandomPrefabQueryByRedis(ctx context.Context, maxLimit int64) []*proto.Query {
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeProcessor",
		"func":  "Process",
	})

	words := make([]*proto.Query, 0)
	if maxLimit <= 0 {
		return words
	}

	recSetKey := p.getSetRedisKey(prefabWordSetRedisKey, proto.QueryType_PREFAB_WORD_QUESTION)
	hotSetKey := p.getSetRedisKey(prefabWordSetRedisKey, proto.QueryType_PREFAB_WORD_HOT_QUESTION)

	recWords := make([]string, 0)
	hotWords := make([]string, 0)
	recPrefabWords := make([]*dao.PrefabWord, 0)
	hotPrefabWords := make([]*dao.PrefabWord, 0)
	prefabWords := make([]*dao.PrefabWord, 0)

	// 分别从两个redis set 中获取引导词
	wg := safe_group.NewGroup("GetRandomPrefabWordByRedis")
	if maxLimit == 1 {
		recWord, recWordErr := p.redisClient.SRandMemberN(ctx, recSetKey, maxLimit).Result()
		if recWordErr != nil {
			return words
		}
		recWords = recWord
		res, recMGetWordErr := p.mGetSourceQuestion(ctx, proto.QueryType_PREFAB_WORD_QUESTION, recWords)
		if recMGetWordErr != nil {
			return words
		}
		recPrefabWords = res
	} else {
		wg.Go(func() error {
			recWord, err := p.redisClient.SRandMemberN(ctx, recSetKey, maxLimit/2).Result()
			if err != nil {
				return err
			}
			recWords = recWord
			return nil
		})
		wg.Go(func() error {
			hotWord, err := p.redisClient.SRandMemberN(ctx, hotSetKey, maxLimit/2).Result()
			if err != nil {
				return err
			}
			hotWords = hotWord
			return nil
		})
		wgSetErr := wg.Wait()
		if wgSetErr != nil {
			logger.Errorf(ctx, "GetRandomPrefabWordByRedis(GetSet) Wait Err => %v", wgSetErr)
		}

		// 同一问题衍生词 查询
		wg.Go(func() error {
			res, err := p.mGetSourceQuestion(ctx, proto.QueryType_PREFAB_WORD_QUESTION, recWords)
			if err != nil {
				return err
			}
			recPrefabWords = res
			return nil
		})
		wg.Go(func() error {
			res, err := p.mGetSourceQuestion(ctx, proto.QueryType_PREFAB_WORD_HOT_QUESTION, hotWords)
			if err != nil {
				return err
			}
			hotPrefabWords = res
			return nil
		})
		wgHashErr := wg.Wait()
		if wgHashErr != nil {
			logger.Errorf(ctx, "GetRandomPrefabWordByRedis(Union) Wait Err => %v", wgHashErr)
		}
	}

	// 词再去重 防止优质内容与热榜重复
	prefabWords = append(prefabWords, recPrefabWords...)
	prefabWords = append(prefabWords, hotPrefabWords...)
	unionWords := lo.UniqBy(prefabWords, func(w *dao.PrefabWord) interface{} {
		return w.AiQuestion
	})

	// 根据原始问题分组去重
	groupWordsBySourceQuestion := lo.GroupBy(unionWords, func(w *dao.PrefabWord) interface{} {
		return w.SourceQuestion
	})
	for k, ws := range groupWordsBySourceQuestion {
		if k == "" {
			for _, w := range ws {
				words = append(words, &proto.Query{Query: w.AiQuestion, QueryType: w.QueryType})
			}
			continue
		}
		words = append(words, &proto.Query{Query: ws[0].AiQuestion, QueryType: ws[0].QueryType})
	}
	return words
}

func (p *PrefabWordDaoImpl) mGetSourceQuestion(ctx context.Context, queryType proto.QueryType, qiWords []string) ([]*dao.PrefabWord, error) {
	if qiWords == nil || len(qiWords) == 0 {
		return []*dao.PrefabWord{}, nil
	}

	keys := make([]string, 0)
	for _, w := range qiWords {
		keys = append(keys, p.getKvRedisKey(prefabWordAndSourceRedisKey, queryType, w))
	}

	res, err := p.redisClient.MGet(ctx, keys...).Result()
	if err != nil {
		log.Errorf(ctx, "GetRandomPrefabWordByRedis(MGet) Err => %v", err)
		return []*dao.PrefabWord{}, err
	}

	prefabWords := make([]*dao.PrefabWord, 0)
	for i, sourceQuestion := range res {
		if sourceQuestion == nil {
			continue
		}

		prefabWords = append(prefabWords, &dao.PrefabWord{
			QueryType:      queryType,
			AiQuestion:     qiWords[i],
			SourceQuestion: sourceQuestion.(string),
		})
	}
	return prefabWords, nil
}

func (p *PrefabWordDaoImpl) RemovePrefabWordRedis(ctx context.Context, queryType proto.QueryType,
	word *dao.PrefabWord) error {
	setKey := p.getSetRedisKey(prefabWordSetRedisKey, queryType)
	kvKey := p.getKvRedisKey(prefabWordAndSourceRedisKey, queryType, word.AiQuestion)
	pipe := p.redisClient.Pipeline()
	pipe.SRem(ctx, setKey, word.AiQuestion)
	pipe.Del(ctx, kvKey)
	_, err := pipe.Exec(ctx)
	return err
}

func (p *PrefabWordDaoImpl) RemoveAllRedisByType(ctx context.Context, queryType proto.QueryType) error {
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeProcessor",
		"func":  "RemoveAllRedisByType",
	})

	setKey := p.getSetRedisKey(prefabWordSetRedisKey, queryType)

	res, sErr := p.redisClient.SMembers(ctx, setKey).Result()
	if sErr != nil {
		logger.Errorf(ctx, "SMembers error => %v", sErr)
	}

	// 如果有匹配的键，则执行删除操作
	if len(res) > 0 {
		kvKeys := make([]string, 0)
		for _, word := range res {
			kvKey := p.getKvRedisKey(prefabWordAndSourceRedisKey, queryType, word)
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
