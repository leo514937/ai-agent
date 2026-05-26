package grpc

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/exception"
	"github.com/samber/lo"
	epb "google.golang.org/genproto/googleapis/rpc/errdetails"
	spb "google.golang.org/genproto/googleapis/rpc/status"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/anypb"
)

var (
	TenantIDNotSet       = status.Error(codes.InvalidArgument, "tenant_id not set")
	TaskIDNotSet         = status.Error(codes.InvalidArgument, "task_id not set")
	MemberIDNotSet       = status.Error(codes.InvalidArgument, "member_id not set")
	ConversationIDNotSet = status.Error(codes.InvalidArgument, "conversation_id not set")
	UserMessageNotSet    = status.Error(codes.InvalidArgument, "user_message not set")
	ConversationNotFound = status.Error(codes.NotFound, "conversation not found")
	PermissionDenied     = status.Error(codes.PermissionDenied, "permission denied")
)

func Wrap(err error) error {
	coreErr, ok := err.(*exception.Error)
	if !ok {
		return status.New(codes.Internal, err.Error()).Err()
	}
	return (status.FromProto(&spb.Status{
		Code:    int32(codes.Unknown),
		Message: err.Error(),
		Details: []*anypb.Any{
			lo.Must(anypb.New(&epb.ErrorInfo{
				Reason: coreErr.Code(),
				Domain: "core.aisp.zhihu.com",
				Metadata: map[string]string{
					"name": coreErr.Name(),
				},
			})),
		},
	})).Err()
}
