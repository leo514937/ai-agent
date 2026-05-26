package dialogue

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

//go:generate mockery --name MessageExtractor
type MessageExtractor interface {
	// Extract 会根据用户消息，提取历史消息
	Extract(ctx context.Context, tenantID, conversationID int64) ([]*model.Dialogue, error)
}

type SlideWindowExtractor struct {
	dialogueDAO dao.DialogueDAO
}

func (e *SlideWindowExtractor) Extract(ctx context.Context, tenantID, conversationID int64) ([]*model.Dialogue, error) {
	logger := log.WithField(ctx, "conversationID", conversationID)

	var (
		history []*model.Dialogue
		step    int64 = 200
		max           = 400
	)
	for i := 0; i < 3; i++ {
		partial, err := e.dialogueDAO.ListDialogueByConversationID(ctx, tenantID, conversationID, step*int64(i), step)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to list dialogue by conversation id")
			return nil, err
		}
		if len(partial) == 0 {
			break
		}
		history = append(history, lo.Filter(partial, func(item *model.Dialogue, _ int) bool {
			return item.State == model.DialogueStateSuccess && item.AuditState == model.DialogueAuditStatePass
		})...)
		if len(history) >= max {
			break
		}
	}
	return lo.Reverse(lo.Slice(history, 0, max)), nil
}

var _ MessageExtractor = (*SlideWindowExtractor)(nil)

func NewSlideWindowExtractor() *SlideWindowExtractor {
	return &SlideWindowExtractor{
		dialogueDAO: dao.DefaultDialogueDAO,
	}
}

var DefaultHistoryExtractor MessageExtractor = NewSlideWindowExtractor()
