package conversation

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/metrics"
)

type Service interface {
	// CreateConversation 创建对话
	CreateConversation(ctx context.Context, tenantID, taskID int64, creatorID string, system map[string]any) (conversation *model.Conversation, err error)
	// GetConversation 获取对话
	GetConversation(ctx context.Context, tenantID, conversationID int64) (conversation *model.Conversation, err error)
}

var DefaultService Service

func NewServiceImpl() Service {
	return &ServiceImpl{
		conversationDAO: dao.DefaultConversationDAO,
		idGenerator:     dao.DefaultIDGenerator,

		metricsClient: metrics.NewClient("core.service.conversation"),
	}
}

type ServiceImpl struct {
	conversationDAO dao.ConversationDAO
	idGenerator     dao.IDGenerator

	metricsClient metrics.Client
}

func (s *ServiceImpl) GetConversation(ctx context.Context, tenantID, conversationID int64) (conversation *model.Conversation, err error) {
	s.metricsClient.Count(ctx, "get", 1)
	return s.conversationDAO.GetConversationByID(ctx, tenantID, conversationID)
}

func (s *ServiceImpl) CreateConversation(ctx context.Context, tenantID, taskID int64, creatorID string, system map[string]any) (conversation *model.Conversation, err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id": tenantID,
		"task_id":   taskID,
		"creator":   creatorID,
		"system":    system,
	})
	s.metricsClient.Count(ctx, "create", 1)
	conversationID, err := s.idGenerator.GenerateID(ctx)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to generate conversation id")
		return nil, err
	}
	_, err = s.conversationDAO.CreateConversation(ctx, &model.Conversation{
		ID:        conversationID,
		TenantID:  tenantID,
		TaskID:    taskID,
		CreatorID: creatorID,
		State:     model.ConversationStateNormal,
		System:    system,
	})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "create conversation failed")
		return nil, err
	}
	return s.conversationDAO.GetConversationByID(ctx, tenantID, conversationID)
}

var _ Service = (*ServiceImpl)(nil)

func init() {
	DefaultService = NewServiceImpl()
}
