package dao

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type PrefabWordV2Dao interface {
	// SavePrefabWordV2ToRedisSet 保存预制问答到redis set
	SavePrefabWordV2ToRedisSet(ctx context.Context, queryType proto.QueryType, word *model.PrefabWord) error

	// GetRandomPrefabWordV2ByRedis 获取随机词(带类型)
	GetRandomPrefabWordV2ByRedis(ctx context.Context, maxLimit int64, queryType proto.QueryType) []*model.PrefabWord

	// GetRandomPrefabQueryV2ByRedis 获取随机词(带类型)
	GetRandomPrefabQueryV2ByRedis(ctx context.Context, maxLimit int64, queryType proto.QueryType) []*proto.Query

	// HandleToConvertQuery 去重并转换为 proto.Query
	HandleToConvertQuery(words []*model.PrefabWord) []*proto.Query

	// HandleToConvertQueryV2 新版去重并转换为 proto.Query
	HandleToConvertQueryV2(prefabWords []*model.PrefabWordInfo) []*proto.Query

	// RemovePrefabWordV2Redis 删除词
	RemovePrefabWordV2Redis(ctx context.Context, queryType proto.QueryType, wordId int64) error

	// RemoveAllRedisV2ByType 删除词(根据类型全部)
	RemoveAllRedisV2ByType(ctx context.Context, queryType proto.QueryType) error
}
