package dao

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// WordMapperTableName 表名
const WordMapperTableName = "word_mapper"
const (
	WordMapperFieldID        = "id"
	WordMapperFieldWordId    = "word_id"
	WordMapperFieldWordType  = "word_type"
	WordMapperFieldWord      = "word"
	WordMapperFieldSourceId  = "source_id"
	WordMapperFieldDeleted   = "deleted"
	WordMapperFieldCreatedAt = "created_at"
	WordMapperFieldUpdatedAt = "updated_at"
)

//go:generate mockery --name WordMapperDAO
type WordMapperDAO interface {

	// DelByWordId 根据wordId 删除(逻辑)
	DelByWordId(ctx context.Context, wordId int64) (int64, error)

	// DelByWordIdAndType 根据wordId 删除(逻辑)
	DelByWordIdAndType(ctx context.Context, wordId int64, wordType int32) (int64, error)

	// UpdateWordById 根据 wordId 更新 word 的内容
	UpdateWordById(ctx context.Context, wordId int64, word string) (int64, error)

	// GetByWordId 根据wordId获取wordMapper
	GetByWordId(ctx context.Context, wordId int64) (*model.WordMapper, error)

	// GetByWordIdAndType 根据wordId获取wordMapper
	GetByWordIdAndType(ctx context.Context, wordId int64, wordType int32) (*model.WordMapper, error)

	// GetByWordAndType 根据word和type获取wordMapper
	GetByWordAndType(ctx context.Context, word string, wordType int32) (*model.WordMapper, error)

	// GetWordIdAndCreate 获取wordId并创建（最大重试1次）
	GetWordIdAndCreate(ctx context.Context, wordDto *model.WordMapperCreateDto) (int64, error)

	// WordExist 判断词是否存在
	WordExist(ctx context.Context, word string, wordTypes []int32) bool

	// GetValidWordByType 获取词
	GetValidWordByType(ctx context.Context, wordType []proto.QueryType, limit uint64) ([]*model.WordMapper, error)
}
