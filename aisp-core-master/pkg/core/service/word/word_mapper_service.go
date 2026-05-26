package word

import (
	"context"
	"database/sql"
	"encoding/base64"
	"fmt"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/pkg/errors"
	"github.com/spf13/cast"
)

type WordMapperService interface {
	// BatchGetWordIdAndSaveWord 批量获取wordId并创建（最大重试1次）
	BatchGetWordIdAndSaveWord(ctx context.Context, wordsDto []model.WordMapperCreateDto) map[model.WordMapperCreateDto]int64
	// GetWordIdAndSaveWord 获取wordId并创建（最大重试1次）
	GetWordIdAndSaveWord(ctx context.Context, wordDto *model.WordMapperCreateDto) (int64, error)
	// GetSourceWordInfo 获取wordId并创建（最大重试1次）
	GetSourceWordInfo(ctx context.Context, wordId int64, wordType int32) (*model.WordMapper, error)
	// RemoveWordId 删除词 需要同时删除 当前缓存数据
	RemoveWordId(ctx context.Context, wordId int64, wordType int32) (bool, error)
	// RemoveWord 删除词 需要同时删除 当前缓存数据
	RemoveWord(ctx context.Context, wordStr string, wordType int32) (bool, error)
	// IsWordByBefore 当前是否为词的前置检查
	IsWordByBefore(word string) bool
	// IsPrefabWord 当前词是否为引导词
	IsPrefabWord(ctx context.Context, word string) bool
	// GetValidWordByType 获取词
	GetValidWordByTypes(ctx context.Context, wordType []proto.QueryType, limit uint64) ([]*model.WordMapper, error)
	// UpdateWordById 更新词内容
	UpdateWordById(ctx context.Context, wordId int64, word string) (int64, error)
}

type WordMapperServiceImpl struct {
	dao       dao.WordMapperDAO
	wordCache *cache.SafeCache
}

var (
	_                        WordMapperService = (*WordMapperServiceImpl)(nil)
	DefaultWordMapperService WordMapperService
	cacheKeyPrefix           = "word:"
)

func init() {
	DefaultWordMapperService = NewWordMapperService()
}

func NewWordMapperService() *WordMapperServiceImpl {
	return NewWordMapperServiceByTimeOut(86400)
}

func NewWordMapperServiceByTimeOut(cacheTimeOutBySec int64) *WordMapperServiceImpl {
	return &WordMapperServiceImpl{
		dao: daoImpl.DefaultWordMapperDAO,
		wordCache: cache.NewSafeCache(&cache.SafeCacheConfig{
			DefCacheTimeOut: cacheTimeOutBySec,
		}),
	}
}

// GetSourceWordInfo 获得原始词信息
func (s *WordMapperServiceImpl) GetSourceWordInfo(ctx context.Context, wordId int64, wordType int32) (*model.WordMapper, error) {
	wordMapper, err := s.dao.GetByWordIdAndType(ctx, wordId, wordType)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, errors.Errorf("not matched word => wordId: %v", wordId)
	} else if err != nil {
		return nil, err
	}

	return wordMapper, nil
}

// RemoveWordId 删除词
func (s *WordMapperServiceImpl) RemoveWordId(ctx context.Context, wordId int64, wordType int32) (bool, error) {
	// 先查询本地词状态
	wordMapper, err := s.dao.GetByWordIdAndType(ctx, wordId, wordType)
	if err != nil {
		return false, err
	}

	return s.doRemoveWord(ctx, wordMapper, wordType)
}

// RemoveWord 删除词
func (s *WordMapperServiceImpl) RemoveWord(ctx context.Context, wordStr string, wordType int32) (bool, error) {
	// 先查询本地词状态
	wordMapper, err := s.dao.GetByWordAndType(ctx, wordStr, wordType)
	if err != nil {
		return false, err
	}
	return s.doRemoveWord(ctx, wordMapper, wordType)
}

// RemoveWordId 删除词
func (s *WordMapperServiceImpl) doRemoveWord(ctx context.Context, wordMapper *model.WordMapper, wordType int32) (bool, error) {
	logger := log.WithField(ctx, "RemoveWord", util.GetJSONIgnoreError(wordMapper))
	cacheKey := s.getRedisKey(wordMapper.Word, wordMapper.WordType)
	// 如果当前状态时 已删除 则不需要再进行删除
	if wordMapper.Deleted == cast.ToInt64(macro.Dict_Yes) {
		return true, nil
	}

	// 删除 词ID ， 并从 Redis 安全缓存中删除
	_, _ = s.wordCache.RemoveCache(ctx, cacheKey)

	// 删除 词， 并从数据库中删除
	delCount, delSqlErr := s.dao.DelByWordIdAndType(ctx, wordMapper.WordId, wordType)
	if delSqlErr != nil {
		dbErr := errors.Errorf("remove word cache failed by mysql - wordId:%d, error => %v", wordMapper.WordId, delSqlErr)
		logger.Errorf(ctx, dbErr.Error())
		return false, delSqlErr
	}
	if delCount == 0 {
		dbErr := errors.Errorf("remove word cache failed by mysql - wordId:%d, error => %s", wordMapper.WordId, "count is 0")
		logger.Errorf(ctx, dbErr.Error())
		return false, dbErr
	}

	// 缓存一致性双删 词ID ， 并从 Redis 安全缓存中删除
	_, cacheErr := s.wordCache.RemoveCache(ctx, cacheKey)
	if cacheErr != nil && !errors.Is(cacheErr, redis.ErrNil) {
		redisErr := errors.Errorf("remove word cache failed by redis - wordId:%d, error => %s", wordMapper.WordId, cacheErr)
		logger.Errorf(ctx, redisErr.Error())
		return false, redisErr
	}
	return true, nil
}

// GetWordIdAndSaveWord 获取wordId并创建（最大重试1次）
func (s *WordMapperServiceImpl) GetWordIdAndSaveWord(ctx context.Context, wordDto *model.WordMapperCreateDto) (int64, error) {
	cacheKey := s.getRedisKey(wordDto.Word, wordDto.WordType)
	// 获取 词ID ， 并加入 Redis 安全缓存
	getCache, ok := s.wordCache.GetCache(ctx, cacheKey,
		func(ctx context.Context, key string) (string, error) {
			wordId, err := s.dao.GetWordIdAndCreate(ctx, wordDto)
			if err != nil {
				return "", err
			}
			return cast.ToString(wordId), nil
		})
	// 如果 ok 则需要 处理模版
	if ok {
		return cast.ToInt64(getCache), nil
	}
	return 0, errors.Errorf("get word id failed => %s", wordDto.Word)
}

// BatchGetWordIdAndSaveWord 批量获取wordId并创建（最大重试1次）
func (s *WordMapperServiceImpl) BatchGetWordIdAndSaveWord(ctx context.Context, wordsDto []model.WordMapperCreateDto) map[model.WordMapperCreateDto]int64 {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "BatchGetWordIdAndSaveWord",
	})

	// 生成词Id
	syncMap := util.NewSyncMap[model.WordMapperCreateDto, int64]()
	wg := safe_group.NewGroupWithTimeout("BatchGetWordIdAndSaveWord", 4000)
	for _, wordItem := range wordsDto {
		wordItem := wordItem
		wg.Go(func() error {
			wordId, wErr := s.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
				WordType: wordItem.WordType,
				Word:     wordItem.Word,
			})
			if wErr != nil {
				logger.Warnf(ctx, "word id gen error => word:%v err:%v", wordItem, wErr)
				return nil
			}

			syncMap.Set(wordItem, wordId)
			return nil
		})
	}
	// 等待所有 goroutine 完成
	wgErr := wg.Wait()
	if wgErr != nil {
		logger.Warnf(ctx, "BatchGetWordIdAndSaveWord Wait Err => %v", wgErr)
	}

	resp := make(map[model.WordMapperCreateDto]int64)
	syncMap.Range(func(key model.WordMapperCreateDto, value int64) bool {
		resp[key] = value
		return true
	})
	return resp
}

const PrefabWordMaxLength = 20

var suggestQueryTypes = []int32{
	int32(proto.QueryType_PREFAB_WORD_QUESTION),
	int32(proto.QueryType_PREFAB_WORD_HOT_QUESTION),
	int32(proto.QueryType_RELATE_WORD_HOT_EVENT),
}

func (s *WordMapperServiceImpl) IsWordByBefore(word string) bool {
	// 空内容，不是引导词
	if util.UnicodeLen(word) == 0 {
		return false
	}
	// 超过PrefabWordMaxLength，不是引导词
	if util.UnicodeLen(word) > PrefabWordMaxLength {
		return false
	}
	return true
}

func (s *WordMapperServiceImpl) IsPrefabWord(ctx context.Context, word string) bool {
	// 前置检查
	isPassed := s.IsWordByBefore(word)
	if !isPassed {
		return false
	}

	// 读取 tidb 判断是否是引导词，结果加 redis+local 二级缓存
	res := make(map[string]bool, 1)
	resource.RedisLocalCache.BatchGet(ctx, []string{word}, util.StringKeyGeneratorFunc,
		func(words interface{}) interface{} {
			oneWord := words.([]string)[0]
			resultMap := make(map[string]bool, 1)
			isExist := s.dao.WordExist(ctx, oneWord, suggestQueryTypes)
			resultMap[oneWord] = isExist
			return resultMap
		}, &res, util.SuggestQueriesKeyOption)

	return res[word]
}

func (s *WordMapperServiceImpl) GetValidWordByTypes(ctx context.Context, wordType []proto.QueryType, limit uint64) ([]*model.WordMapper, error) {
	return s.dao.GetValidWordByType(ctx, wordType, limit)
}

func (s *WordMapperServiceImpl) UpdateWordById(ctx context.Context, wordId int64, word string) (int64, error) {
	affectedRows, err := s.dao.UpdateWordById(ctx, wordId, word)
	if affectedRows != 1 {
		log.Warnf(ctx, "update word failed, wordId: %d, word: %s, AffectedRows: %d", wordId, word, affectedRows)
	}
	return affectedRows, err
}

func (s *WordMapperServiceImpl) getRedisKey(word string, wordType int32) string {
	encodedKey := base64.StdEncoding.EncodeToString([]byte(encodeWord(word)))
	return fmt.Sprintf("%s%s_%d", cacheKeyPrefix, encodedKey, wordType)
}

func encodeWord(word string) string {
	return strings.ReplaceAll(strings.TrimSpace(word), " ", "&nbsp;")
}

func decodeWord(word string) string {
	return strings.ReplaceAll(strings.TrimSpace(word), "&nbsp;", " ")
}
