package aisservice

import (
	"context"
	"unicode/utf8"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/shared"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/exception"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/budget"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/conversation"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialogue"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const UserMessageMaxLength = 8192 // 2 x 4096

type ChatBiz interface {
	CreateConversation(ctx context.Context, tenantID, taskID int64, creatorID string, system map[string]any) (conversation *model.Conversation, err error)
	GetConversation(ctx context.Context, tenantID, conversationID int64) (conversation *model.Conversation, err error)

	CreateDialogue(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}, env *model.RequestEnv) (dialogue *model.Dialogue, err error)
	CreateDialogueStream(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}, env *model.RequestEnv) <-chan util.Progress[*model.Dialogue]
}

type ChatBizImpl struct {
	tenantDAO       dao.TenantDAO
	taskDAO         dao.TaskDAO
	conversationDAO dao.ConversationDAO
	dialogueDAO     dao.DialogueDAO

	dialogueService     dialogue.Service
	conversationService conversation.Service
	budgetService       budget.Service

	rateLimiter shared.RateLimiter
	spamBlocker shared.SpamBlocker
}

var _ ChatBiz = (*ChatBizImpl)(nil)

var DefaultChatBiz ChatBiz

func init() {
	DefaultChatBiz = NewChatBiz()
}

func NewChatBiz() ChatBiz {
	return &ChatBizImpl{
		tenantDAO:       dao.DefaultTenantDAO,
		taskDAO:         dao.DefaultTaskDAO,
		conversationDAO: dao.DefaultConversationDAO,
		dialogueDAO:     dao.DefaultDialogueDAO,

		conversationService: conversation.DefaultService,
		dialogueService:     dialogue.DefaultService,
		budgetService:       budget.DefaultService,

		rateLimiter: shared.DefaultRateLimiter,
		spamBlocker: shared.DefaultSpamBlocker,
	}
}

func (c *ChatBizImpl) CreateConversation(ctx context.Context, tenantID, taskID int64, creator string, system map[string]any) (*model.Conversation, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenantID": tenantID,
		"taskID":   taskID,
		"creator":  creator,
		"system":   system,
	})

	tenant, err := c.tenantDAO.GetTenantByID(ctx, tenantID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get tenant by id")
		return nil, err
	}
	if tenant == nil {
		logger.Error(ctx, "tenant not found")
		return nil, exception.ErrTenantNotFound
	}
	logger = logger.WithField(ctx, "tenant", tenant)
	if tenant.State != model.TenantStateNormal {
		return nil, exception.ErrTenantStateInvalid
	}
	hasBudget, err := c.budgetService.HasBudget(ctx, tenantID, taskID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to check budget")
		return nil, err
	}
	if !hasBudget {
		logger.Warn(ctx, "budget exceeded")
		return nil, exception.ErrBudgetExceeded
	}

	task, err := c.taskDAO.GetTaskByID(ctx, tenantID, taskID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get task by id")
		return nil, err
	}
	if task == nil {
		logger.Error(ctx, "task not found")
		return nil, exception.ErrTaskNotFound
	}
	logger = logger.WithField(ctx, "task", task)
	if task.State != model.TaskStateNormal {
		logger.Error(ctx, "task state invalid")
		return nil, exception.ErrTaskStateInvalid
	}

	allow, err := c.rateLimiter.TryAcquire(ctx, tenantID, taskID, task.RateLimit)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to check rate limit")
		return nil, err
	}
	if !allow {
		logger.WithField(ctx, "ratelimit", task.RateLimit).Error(ctx, "rate limit exceeded")
		return nil, exception.ErrRateLimitExceeded.New("rate limit exceeded: current_rate>%d", task.RateLimit)
	}

	resp, err := c.conversationService.CreateConversation(ctx, tenantID, taskID, creator, system)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to create conversation")
		return nil, err
	}
	return resp, nil
}

func (c *ChatBizImpl) GetConversation(ctx context.Context, tenantID, conversationID int64) (*model.Conversation, error) {
	return c.conversationService.GetConversation(ctx, tenantID, conversationID)
}

func (c *ChatBizImpl) CreateDialogue(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}, env *model.RequestEnv) (dialogue *model.Dialogue, err error) {
	// 预算检查比较松散
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenantID":       tenantID,
		"taskID":         taskID,
		"conversationID": conversationID,
		"userMessage":    userMessage,
	})

	if utf8.RuneCountInString(userMessage) > UserMessageMaxLength {
		logger.Error(ctx, "user message too long")
		return nil, exception.ErrUserMessageTooLong
	}

	tenant, err := c.tenantDAO.GetTenantByID(ctx, tenantID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get tenant by id")
		return nil, err
	}
	if tenant == nil {
		logger.Error(ctx, "tenant not found")
		return nil, exception.ErrTenantNotFound
	}
	logger = logger.WithField(ctx, "tenant", tenant)
	if tenant.State != model.TenantStateNormal {
		logger.Error(ctx, "tenant state invalid")
		return nil, exception.ErrTenantStateInvalid
	}

	task, err := c.taskDAO.GetTaskByID(ctx, tenantID, taskID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get task by id")
		return nil, err
	}
	if task == nil {
		logger.Error(ctx, "task not found")
		return nil, exception.ErrTaskNotFound
	}
	logger = logger.WithField(ctx, "task", task)
	if task.State != model.TaskStateNormal {
		logger.Error(ctx, "task state invalid")
		return nil, exception.ErrTaskStateInvalid
	}

	var conversation *model.Conversation
	if task.ConversationModel == model.ConversationModelTask && conversationID == 0 {
		conversation, err = c.conversationService.CreateConversation(ctx, tenantID, taskID, userID, nil)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to create conversation")
			return nil, err
		}
		logger.Info(ctx, "create conversation success")
		conversationID = conversation.ID
	} else {
		var err error
		conversation, err = c.conversationDAO.GetConversationByID(ctx, tenantID, conversationID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to get conversation by id")
			return nil, err
		}
	}

	if conversation == nil {
		logger.Error(ctx, "conversation not found")
		return nil, exception.ErrConversationNotFound
	}
	logger = logger.WithField(ctx, "conversation", conversation)
	if conversation.State != model.ConversationStateNormal {
		logger.Error(ctx, "conversation state invalid")
		return nil, exception.ErrConversationStateInvalid
	}
	allow, err := c.rateLimiter.TryAcquire(ctx, tenantID, taskID, task.RateLimit)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to check rate limit")
		return nil, err
	}
	if !allow {
		logger.Error(ctx, "rate limit exceeded")
		return nil, exception.ErrRateLimitExceeded
	}

	hasBudget, err := c.budgetService.HasBudget(ctx, tenantID, taskID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to check budget")
		return nil, err
	}
	if !hasBudget {
		logger.Warn(ctx, "budget exceeded")
		return nil, exception.ErrBudgetExceeded
	}

	if isSpam, err := c.spamBlocker.IsSpam(ctx, tenantID, taskID, userID, conversationID, userMessage, env.Headers); err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to check spam")
		return nil, err
	} else if isSpam {
		logger.Error(ctx, "spam detected")
		return nil, exception.ErrSpamDetected
	}

	dialogue, err = c.dialogueService.CreateDialogue(ctx, tenantID, taskID, userID, conversationID, userMessage, custom)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to create dialogue")
		return nil, err
	}

	var modelName string
	dialogue, modelName, err = c.dialogueService.ProcessDialogue(util.WithoutCancel(ctx), dialogue)
	if dialogue.State == model.DialogueStateSuccess {
		err := c.budgetService.TriggerBilling(ctx, tenantID, taskID, dialogue.ID, modelName, dialogue.InputTokenCount, dialogue.OutputTokenCount)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to update budget")
		}
	}
	return dialogue, err
}

func (c *ChatBizImpl) CreateDialogueStream(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}, env *model.RequestEnv) <-chan util.Progress[*model.Dialogue] {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenantID":       tenantID,
		"taskID":         taskID,
		"conversationID": conversationID,
		"userMessage":    userMessage,
	})

	ret := make(chan util.Progress[*model.Dialogue])
	utils.SafelyGo(func() {
		defer close(ret)

		defer func() {
			panic_ := recover()
			if panic_ != nil {
				logger.WithField(ctx, "panic", panic_).Errorf(ctx, "panic in CreateDialogueStream")
				ret <- util.Progress[*model.Dialogue]{E: exception.ErrInternal.New("panic in CreateDialogueStream")}
			}
		}()

		if utf8.RuneCountInString(userMessage) > UserMessageMaxLength {
			logger.Error(ctx, "user message too long")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrUserMessageTooLong}
			return
		}

		tenant, err := c.tenantDAO.GetTenantByID(ctx, tenantID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to get tenant by id")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}
		if tenant == nil {
			logger.Error(ctx, "tenant not found")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrTenantNotFound}
			return
		}
		logger = logger.WithField(ctx, "tenant", tenant)
		if tenant.State != model.TenantStateNormal {
			logger.Error(ctx, "tenant state invalid")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrTenantStateInvalid}
			return
		}

		task, err := c.taskDAO.GetTaskByID(ctx, tenantID, taskID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to get task by id")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}
		if task == nil {
			logger.Error(ctx, "task not found")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrTaskNotFound}
			return
		}
		logger = logger.WithField(ctx, "task", task)
		if task.State != model.TaskStateNormal {
			logger.Error(ctx, "task state invalid")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrTaskStateInvalid}
			return
		}

		var conversation *model.Conversation
		if task.ConversationModel == model.ConversationModelTask && conversationID == 0 {
			conversation, err = c.conversationService.CreateConversation(ctx, tenantID, taskID, userID, nil)
			if err != nil {
				logger.WithError(ctx, err).Errorf(ctx, "failed to create conversation")
				ret <- util.Progress[*model.Dialogue]{E: err}
				return
			}
			logger.Info(ctx, "create conversation success")
			conversationID = conversation.ID
		} else {
			var err error
			conversation, err = c.conversationDAO.GetConversationByID(ctx, tenantID, conversationID)
			if err != nil {
				logger.WithError(ctx, err).Errorf(ctx, "failed to get conversation by id")
				ret <- util.Progress[*model.Dialogue]{E: err}
				return
			}
		}

		if conversation == nil {
			logger.Error(ctx, "conversation not found")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrConversationNotFound}
			return
		}
		logger = logger.WithField(ctx, "conversation", conversation)
		if conversation.State != model.ConversationStateNormal {
			logger.Error(ctx, "conversation state invalid")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrConversationStateInvalid}
			return
		}
		allow, err := c.rateLimiter.TryAcquire(ctx, tenantID, taskID, task.RateLimit)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to check rate limit")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}
		if !allow {
			logger.Error(ctx, "rate limit exceeded")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrRateLimitExceeded}
			return
		}

		hasBudget, err := c.budgetService.HasBudget(ctx, tenantID, taskID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to check budget")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}
		if !hasBudget {
			logger.Warn(ctx, "budget exceeded")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrBudgetExceeded}
			return
		}

		if isSpam, err := c.spamBlocker.IsSpam(ctx, tenantID, taskID, userID, conversationID, userMessage, env.Headers); err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to check spam")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		} else if isSpam {
			logger.Error(ctx, "spam detected")
			ret <- util.Progress[*model.Dialogue]{E: exception.ErrSpamDetected}
			return
		}

		dialogue, err := c.dialogueService.CreateDialogue(ctx, tenantID, taskID, userID, conversationID, userMessage, custom)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to create dialogue")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}

		ret <- util.Progress[*model.Dialogue]{V: dialogue}
		resultStream, modelName, err := c.dialogueService.ProcessDialogueStream(ctx, dialogue)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to process dialogue stream")
			ret <- util.Progress[*model.Dialogue]{E: err}
			return
		}

		for progress := range resultStream {
			if progress.E != nil {
				ret <- progress
				return
			}

			ret <- progress
			if progress.V.State == model.DialogueStateSuccess {
				err := c.budgetService.TriggerBilling(ctx, tenantID, taskID, progress.V.ID, modelName, progress.V.InputTokenCount, progress.V.OutputTokenCount)
				if err != nil {
					logger.WithError(ctx, err).Errorf(ctx, "failed to update budget")
				}
				break
			}
		}

	}, func(_ error) {})
	return ret
}
