package grpc

import (
	"context"
	"strconv"

	"git.in.zhihu.com/go/utils"
	proto "git.in.zhihu.com/zhihu/aisp-core/gen-go/grpc/zhihu/aisp_core_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/aisservice"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/exception"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	structpb "github.com/golang/protobuf/ptypes/struct"
	"github.com/grpc-ecosystem/grpc-gateway/v2/runtime"
	"github.com/samber/lo"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/emptypb"
)

var (
	RegisterAispCoreServiceServer    func(registrar grpc.ServiceRegistrar)
	RegisterAispCoreServieHTTPServer func(mux *runtime.ServeMux)
)

type AISPCoreService struct {
	proto.UnimplementedAispCoreServiceServer
	chatBiz aisservice.ChatBiz
}

var _ proto.AispCoreServiceServer = &AISPCoreService{}

func NewAISPCoreService() *AISPCoreService {
	return &AISPCoreService{
		chatBiz: aisservice.DefaultChatBiz,
	}
}

func (s *AISPCoreService) CreateConversation(ctx context.Context, req *proto.CreateConversationRequest) (*proto.Conversation, error) {
	logger := log.WithField(ctx, "request", req)
	if req.GetTenantId() == 0 {
		logger.Warn(ctx, "tenant_id is not set")
		return nil, TenantIDNotSet
	}
	if req.GetTaskId() == 0 {
		logger.Warn(ctx, "task_id is not set")
		return nil, TaskIDNotSet
	}

	if req.GetCreatorId() < 0 {
		logger.Warn(ctx, "creator_id must be greater than or equal to 0")
		return nil, MemberIDNotSet
	}

	creatorID := strconv.FormatInt(req.GetCreatorId(), 10)
	conversion, err := s.chatBiz.CreateConversation(ctx, req.TenantId, req.TaskId, creatorID, lo.MapValues(req.System, func(value *structpb.Value, _ string) any {
		return value.AsInterface()
	}))
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "create conversation failed")
		return nil, Wrap(err)
	}
	logger.Info(ctx, "create conversation success")
	return convertConversion(conversion), nil
}

func (s *AISPCoreService) GetConversation(ctx context.Context, req *proto.GetConversationRequest) (*proto.Conversation, error) {
	logger := log.WithField(ctx, "request", req)
	if req.GetTenantId() == 0 {
		logger.Warn(ctx, "tenant_id is not set")
		return nil, TenantIDNotSet
	}
	if req.GetTaskId() == 0 {
		logger.Warn(ctx, "task_id is not set")
		return nil, TaskIDNotSet
	}
	if req.GetConversationId() == 0 {
		logger.Warn(ctx, "conversation_id is not set")
		return nil, ConversationIDNotSet
	}
	if req.GetMemberId() < 0 {
		logger.Warn(ctx, "creator_id must be greater than or equal to 0")
		return nil, MemberIDNotSet
	}
	memberID := strconv.FormatInt(req.GetMemberId(), 10)
	conversation, err := s.chatBiz.GetConversation(ctx, req.GetTenantId(), req.GetConversationId())

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "get conversation failed")
		return nil, Wrap(err)
	}
	if conversation == nil {
		logger.Warn(ctx, "conversation not found")
		return nil, ConversationNotFound
	}
	if conversation.CreatorID != memberID {
		logger.Warn(ctx, "permission denied")
		return nil, PermissionDenied
	}
	return convertConversion(conversation), nil
}

func convertConversion(conversation *model.Conversation) *proto.Conversation {
	if conversation == nil {
		return nil
	}
	return &proto.Conversation{
		Id:        conversation.ID,
		CreatorId: lo.Must(utils.ParseInt64(conversation.CreatorID)),
		State:     proto.Conversation_State(proto.Conversation_State_value[string(conversation.State)]),
	}
}

func (s *AISPCoreService) DeleteConversation(ctx context.Context, req *proto.DeleteConversationRequest) (*emptypb.Empty, error) {
	return nil, nil
}

func (s *AISPCoreService) CreateDialogue(ctx context.Context, req *proto.CreateDialogueRequest) (*proto.Dialogue, error) {
	logger := log.WithField(ctx, "req", req)

	if req.GetUserMessage() == "" {
		logger.Warn(ctx, "user message is empty")
		return nil, UserMessageNotSet
	}

	if req.GetTenantId() == 0 {
		logger.Warn(ctx, "tenant id is empty")
		return nil, TenantIDNotSet
	}

	if req.GetTaskId() == 0 {
		logger.Warn(ctx, "task id is empty")
		return nil, TaskIDNotSet
	}

	dialogue, err := s.chatBiz.CreateDialogue(
		ctx,
		req.GetTenantId(),
		req.GetTaskId(),
		utils.Int64ToStr(req.GetMemberId()),
		req.GetConversationId(),
		req.GetUserMessage(),
		lo.MapValues(req.Custom, func(value *structpb.Value, _ string) any {
			return value.AsInterface()
		}),
		&model.RequestEnv{
			Headers: lo.MapValues(req.GetRequestEnv().GetHeaders(), func(entry *proto.CreateDialogueRequest_RequestEnv_HeaderEntry, _ string) []string {
				return entry.GetValue()
			}),
		},
	)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "create dialogue failed")
		return nil, Wrap(err)
	}
	return &proto.Dialogue{
		Id:             dialogue.ID,
		ConversationId: dialogue.ConversationID,
		State:          proto.Dialogue_State(proto.Dialogue_State_value[string(dialogue.State)]),
		AuditState:     proto.Dialogue_AuditState(proto.Dialogue_AuditState_value[string(dialogue.AuditState)]),
		UserMessage:    dialogue.UserMessage,
		AiMessage:      dialogue.AIMessage,
	}, nil
}

func (s *AISPCoreService) CreateDialogueStream(req *proto.CreateDialogueRequest, stream proto.AispCoreService_CreateDialogueStreamServer) error {
	ctx := stream.Context()
	logger := log.WithField(ctx, "req", req)

	if req.GetUserMessage() == "" {
		logger.Warn(ctx, "user message is empty")
		return UserMessageNotSet
	}

	if req.GetTenantId() == 0 {
		logger.Warn(ctx, "tenant id is empty")
		return TenantIDNotSet
	}

	if req.GetTaskId() == 0 {
		logger.Warn(ctx, "task id is empty")
		return TaskIDNotSet
	}

	resultStream := s.chatBiz.CreateDialogueStream(
		ctx,
		req.GetTenantId(),
		req.GetTaskId(),
		utils.Int64ToStr(req.GetMemberId()),
		req.GetConversationId(),
		req.GetUserMessage(),
		lo.MapValues(req.Custom, func(value *structpb.Value, _ string) any {
			return value.AsInterface()
		}),
		&model.RequestEnv{
			Headers: lo.MapValues(req.GetRequestEnv().GetHeaders(), func(entry *proto.CreateDialogueRequest_RequestEnv_HeaderEntry, _ string) []string {
				return entry.GetValue()
			}),
		},
	)
	for progress := range resultStream {
		if progress.E != nil {
			return Wrap(progress.E)
		}
		dialogue := progress.V
		err := stream.Send(&proto.Dialogue{
			Id:             dialogue.ID,
			ConversationId: dialogue.ConversationID,
			State:          proto.Dialogue_State(proto.Dialogue_State_value[string(dialogue.State)]),
			AuditState:     proto.Dialogue_AuditState(proto.Dialogue_AuditState_value[string(dialogue.AuditState)]),
			UserMessage:    dialogue.UserMessage,
			AiMessage:      dialogue.AIMessage,
		})
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "send dialogue failed")
			return err
		}
	}
	return nil
}

type AdminService struct {
	proto.UnimplementedAdminServiceServer
	tenantDao dao.TenantDAO
}

var _ proto.AdminServiceServer = &AdminService{}

func NewAdminService() *AdminService {
	return &AdminService{
		tenantDao: dao.DefaultTenantDAO,
	}
}

func (a *AdminService) CreateTenant(ctx context.Context, request *proto.CreateTenantRequest) (*proto.Tenant, error) {
	// TODO (chendong01): move to biz
	logger := log.WithField(ctx, "req", request)
	ownerID := strconv.FormatInt(request.Owner, 10)
	id, err := a.tenantDao.CreateTenant(ctx, &model.Tenant{
		Owner:       ownerID,
		Name:        request.Name,
		Description: request.Description,
		State:       model.TenantStateNormal,
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "create tenant failed")
		return nil, Wrap(err)
	}
	tenant, err := a.tenantDao.GetTenantByID(ctx, id)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "get tenant failed")
		return nil, Wrap(err)
	}
	if tenant == nil {
		logger.Error(ctx, "tenant not found")
		return nil, exception.ErrInternal.Wrap(exception.ErrTenantNotFound)
	}
	// TODO (chendong01): use transaction
	logger.Info(ctx, "tenant created")
	return &proto.Tenant{
		Id:          tenant.ID,
		Creator:     lo.Must(utils.ParseInt64(tenant.Owner)),
		Name:        tenant.Name,
		Description: tenant.Description,
		State:       string(tenant.State),
		CreatedAt:   tenant.CreatedAt.Unix(),
		UpdatedAt:   tenant.UpdatedAt.Unix(),
	}, nil
}

func (a *AdminService) GetTenant(ctx context.Context, request *proto.GetTenantRequest) (*proto.Tenant, error) {
	logger := log.WithField(ctx, "req", request)
	tenant, err := a.tenantDao.GetTenantByID(ctx, request.Id)
	if err != nil || tenant == nil {
		logger.WithError(ctx, err).Error(ctx, "get tenant failed")
		return nil, Wrap(err)
	}
	return &proto.Tenant{
		Id:          tenant.ID,
		Creator:     lo.Must(utils.ParseInt64(tenant.Owner)),
		Name:        tenant.Name,
		Description: tenant.Description,
		State:       string(tenant.State),
		CreatedAt:   tenant.CreatedAt.Unix(),
		UpdatedAt:   tenant.UpdatedAt.Unix(),
	}, nil
}

func init() {
	RegisterAispCoreServiceServer = func(registrar grpc.ServiceRegistrar) {
		proto.RegisterAispCoreServiceServer(registrar, NewAISPCoreService())
		proto.RegisterAdminServiceServer(registrar, NewAdminService())
	}

	RegisterAispCoreServieHTTPServer = func(mux *runtime.ServeMux) {
		utils.PanicIf(proto.RegisterAispCoreServiceHandlerServer(context.Background(), mux, NewAISPCoreService()))
	}
}
