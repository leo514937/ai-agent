package shared

import (
	"context"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"github.com/samber/lo"
)

type SpamBlockerZhihu struct {
	antispamRPC rpc.AntispamRPC
}

func (s *SpamBlockerZhihu) IsSpam(ctx context.Context, tenantID int64, taskID int64, userID string, conversationID int64, userMessage string, environment Headers) (bool, error) {
	return s.antispamRPC.IsSpam(ctx, lo.Must(utils.ParseInt64(userID)), environment)
}

func init() {
	DefaultSpamBlocker = &SpamBlockerZhihu{
		antispamRPC: rpc.DefaultAntispamRPC,
	}
}
