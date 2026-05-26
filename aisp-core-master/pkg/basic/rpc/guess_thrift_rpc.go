package rpc

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type GuessThriftRpcService interface {
	GetGuessQueries(ctx context.Context, wordType int32, req *proto.SuggestQueriesRequest) (
		[]*model.WordMapperCreateDto, error)

	GetUserGuessQueries(ctx context.Context, wordType int32, memberId int64, messageId string) (
		[]*model.WordMapperCreateDto, error)
}
