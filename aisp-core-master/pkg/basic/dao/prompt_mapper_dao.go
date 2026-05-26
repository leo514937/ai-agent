package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// PromptMapperTableName 表名
const PromptMapperTableName = "prompt_mapper"
const (
	PromptMapperFieldID         = "id"
	PromptMapperFieldPromptCode = "prompt_code"
	PromptMapperFieldPrompt     = "prompt"
	PromptMapperFieldRemark     = "remark"
	PromptMapperFieldCreatedAt  = "created_at"
	PromptMapperFieldUpdatedAt  = "updated_at"
)

//go:generate mockery --name PromptMapperDAO
type PromptMapperDAO interface {
	// Insert 新增
	Insert(ctx context.Context, dto *model.PromptMapperDto) (int64, error)
	// UpdateById 修改
	UpdateById(ctx context.Context, id int64, dto *model.PromptMapperDto) (int64, error)
	// DeleteById 删除
	DeleteById(ctx context.Context, id int64) (int64, error)
	// GetById 查询
	GetById(ctx context.Context, id int64) (*model.PromptMapper, error)
	// GetByCode 查询
	GetByCode(ctx context.Context, code string) (*model.PromptMapper, error)
}
