package dao

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

type PrefabWordDao interface {
	// SavePrefabWordToRedisSet 保存预制问答到redis set
	SavePrefabWordToRedisSet(ctx context.Context, queryType proto.QueryType, word *PrefabWord) error

	// GetRandomPrefabWordByRedis 获取随机词
	GetRandomPrefabWordByRedis(ctx context.Context, maxLimit int64) []string

	// GetRandomPrefabQueryByRedis 获取随机词(带类型)
	GetRandomPrefabQueryByRedis(ctx context.Context, maxLimit int64) []*proto.Query

	// RemovePrefabWordToRedisSet 删除词
	RemovePrefabWordRedis(ctx context.Context, queryType proto.QueryType, word *PrefabWord) error

	// RemoveAllRedisByType 删除词(根据类型全部)
	RemoveAllRedisByType(ctx context.Context, queryType proto.QueryType) error
}

type PrefabWord struct {
	QueryType      proto.QueryType
	AiQuestion     string
	SourceQuestion string
}
