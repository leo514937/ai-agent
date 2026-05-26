package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
)

type UcpGRPC interface {
	BatchGetBayesTagInfos(ctx context.Context, queries []string) [][]*common.TagInfo
}
