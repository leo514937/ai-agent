package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type GeneratorIdType string

func (g GeneratorIdType) ToConvert() string {
	return string(g)
}

const (
	// GeneratorIdTypeDef 默认词
	GeneratorIdTypeDef GeneratorIdType = "IDGenerator:seq"
	// GeneratorIdTypeSessionId SessionId
	GeneratorIdTypeSessionId GeneratorIdType = "id_gen:type:session_id"
	// GeneratorIdTypeWord 兴趣词
	GeneratorIdTypeWord GeneratorIdType = "id_gen:type:word"
	// GeneratorIdTypeMessageId MessageId
	GeneratorIdTypeMessageId GeneratorIdType = "id_gen:type:message_id"
	// GeneratorIdTypeDocumentId 内容Id
	GeneratorIdTypeDocumentId GeneratorIdType = "id_gen:type:doc_id"
	// GeneratorIdTypeBaseId 知识库Id
	GeneratorIdTypeBaseId GeneratorIdType = "id_gen:type:base_id"
)

//go:generate mockery --name IDGenerator
type IDGenerator interface {
	GenerateID(ctx context.Context) (int64, error)
	GenerateIDByType(ctx context.Context, gType GeneratorIdType) (int64, error)
}

var DefaultIDGenerator IDGenerator

func init() {
	DefaultIDGenerator = NewIDGenerator()
}

type IDGeneratorImpl struct {
	redisClient redis.Client
}

func NewIDGenerator() IDGenerator {
	return &IDGeneratorImpl{
		redisClient: resource.RedisByIdGenerator,
	}
}

// GenerateID 生成Id （兼容老业务）
func (i *IDGeneratorImpl) GenerateID(ctx context.Context) (int64, error) {
	return i.GenerateIDByType(ctx, GeneratorIdTypeDef)
}

// GenerateIDByType	根据类型生成Id
func (i *IDGeneratorImpl) GenerateIDByType(ctx context.Context, gType GeneratorIdType) (int64, error) {
	// 第一位为 0， 确保时间戳在 42 位
	id := (((1 << 42) - 1) & util.TimeUnixMilli()) << 21
	seqCmd := i.redisClient.Incr(ctx, gType.ToConvert())
	if err := seqCmd.Err(); err != nil {
		log.WithError(ctx, err).Error(ctx, "failed to get seq")
		return -1, err
	}
	seq := seqCmd.Val()

	id = id + ((1<<21 - 1) & seq)
	return id, nil
}
