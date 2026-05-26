package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-search_words/guess_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

var (
	_                            rpc.GuessThriftRpcService = (*GuessThriftRpcServiceImpl)(nil)
	DefaultGuessThriftRpcService rpc.GuessThriftRpcService
)

// init 初始化
func init() {
	DefaultGuessThriftRpcService = NewGuessThriftRpcServiceImpl()
}

type GuessThriftRpcServiceImpl struct {
	client *guess_thrift.GuessQueriesClient
}

func NewGuessThriftRpcServiceImpl() *GuessThriftRpcServiceImpl {
	return &GuessThriftRpcServiceImpl{
		client: guess_thrift.NewGuessQueriesClient(tzone.NewClient(
			"GuessQueries",
			tzone.TargetName("search-words-rpc"),
			tzone.Timeout(2*time.Second))),
	}
}

// GetGuessQueries 获取搜索推荐词
func (s *GuessThriftRpcServiceImpl) GetGuessQueries(ctx context.Context, wordType int32, req *proto.SuggestQueriesRequest) (
	[]*model.WordMapperCreateDto, error) {
	return s.GetUserGuessQueries(
		ctx, wordType, req.GetInfo().GetMemberId(), req.GetInfo().GetMessage().MessageId)
}

// GetUserGuessQueries 获取用户猜你想搜词
func (s *GuessThriftRpcServiceImpl) GetUserGuessQueries(
	ctx context.Context, wordType int32, memberId int64, messageId string) (
	[]*model.WordMapperCreateDto, error) {

	guessRequestP := &guess_thrift.GuessRequest{
		Scene:         guess_thrift.GuessScene_AI_TAB,
		MemberID:      memberId,
		Offset:        0,
		Limit:         30,
		RequestHashID: messageId,
	}

	var queries []*model.WordMapperCreateDto
	runFunc := func(ctx context.Context) (err error) {
		response, err := s.client.GetQueries(ctx, guessRequestP)
		if err != nil {
			return err
		}

		for _, v := range response.GetQueries() {
			queries = append(queries, &model.WordMapperCreateDto{
				Word:     v.DisplayQuery,
				SourceId: v.ID,
				WordType: wordType,
			})
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	if queries == nil {
		return []*model.WordMapperCreateDto{}, nil
	}
	return queries, nil
}
