package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type SegmentRPC interface {
	Segment(ctx context.Context, text string, stopWordType string, removePuncts bool, removeEmoji bool, mergeCoarse bool) *content.Segment
	Clean(ctx context.Context, text string) string
}
