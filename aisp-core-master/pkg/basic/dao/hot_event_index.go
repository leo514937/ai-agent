package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
)

type HotEventIndexDao interface {
	// 存储热点引导词的创建时间和时效性
	SetWordCreateTimeAndTimeliness(ctx context.Context, wordId int64, timeliness macro.TimelinessType) error
	// 获取热点引导词的创建时间和时效性
	GetWordCreateTimeAndTimeliness(ctx context.Context, wordId int64) (int64, macro.TimelinessType)
	// 存储热点引导词 kafka 消息过来的原始 id 和我们内部维护词 id 的映射
	SetWordOriginId2WordId(ctx context.Context, wordOriginId int64, wordId int64) error
	// 根据 originId 获取词 id
	GetWordOriginId2WordId(ctx context.Context, wordOriginId int64) int64
}
