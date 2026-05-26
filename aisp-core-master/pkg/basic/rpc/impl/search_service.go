package impl

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/go/base/tzone"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const defaultToken = "aisp_core"

type SearchServiceRpcImpl struct {
	token                       string
	SearchServiceClient         *searchThrift.SearchServiceClient
	RealTimeSearchServiceClient *searchThrift.SearchServiceClient
}

var DefaultSearchServiceRpcImpl rpc.SearchServiceRPC

func init() {
	DefaultSearchServiceRpcImpl = NewSearchServiceRpcImpl(defaultToken)
}

func NewSearchServiceRpcImpl(token string) *SearchServiceRpcImpl {
	searchServiceClient := tzone.NewClient(
		"SearchService",
		tzone.TargetName("search-service-new"),
		tzone.Timeout(2*time.Second),
	)
	realTimeSearchServiceClient := tzone.NewClient(
		"SearchService",
		tzone.TargetName("search-service-new-realtime"),
		tzone.Timeout(400*time.Millisecond),
	)

	return &SearchServiceRpcImpl{
		token:                       token,
		SearchServiceClient:         searchThrift.NewSearchServiceClient(searchServiceClient),
		RealTimeSearchServiceClient: searchThrift.NewSearchServiceClient(realTimeSearchServiceClient),
	}
}

func (s *SearchServiceRpcImpl) Search(ctx context.Context, request rpc.SearchServiceRequest) []*rpc.SearchHit {
	var result []*rpc.SearchHit

	// 默认请求 content 类型，即文章回答
	if len(request.Vertical) == 0 {
		request.Vertical = []searchThrift.Vertical{searchThrift.Vertical_CONTENT}
	}
	runFunc := func(ctx context.Context) error {
		searchOption := searchThrift.NewSearchOption()
		searchOption.Offset = request.Offset
		searchOption.Limit = request.Limit
		searchOption.RestrictedScope = request.RestrictedScope
		searchOption.TimeAfter = request.TimeAfter
		searchOption.TimeBefore = request.TimeBefore
		searchOption.MemberID = request.MemberID
		searchOption.FilterOption = request.SearchFilterOption
		// 用户实验
		if len(request.AbParams) > 0 {
			abParamsArr := make([]string, 0)
			for k, v := range request.AbParams {
				abParamsArr = append(abParamsArr, fmt.Sprintf("%s=%s", k, v))
			}
			searchOption.AbParams = strings.Join(abParamsArr, ",")
		}

		// 查询校正
		searchOption.NeedQueryCorrection = request.NeedQueryCorrection
		// 按照 score 排序
		searchOption.UseRescore = thrift.BoolPtr(true)
		response, err := s.SearchServiceClient.Search(ctx, request.Query, request.Vertical, searchOption, s.token)
		if err == nil {
			for _, res := range response {
				if res != nil {
					result = append(result, res.GetHits()...)
				}
			}
			log.Infof(ctx, "zhihu search params:%s, result: %v", util.GetJSONIgnoreError(searchOption), result)
		} else {
			log.Infof(ctx, "zhihu search result is nil, params:%s, err:%v", util.GetJSONIgnoreError(searchOption), err)
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return result
}

func (s *SearchServiceRpcImpl) RealTimeSearch(ctx context.Context, request rpc.SearchServiceRequest) []*rpc.SearchHit {
	var result []*rpc.SearchHit

	runFunc := func(ctx context.Context) error {
		searchOption := searchThrift.NewRealtimeOption()
		searchOption.Size = request.Limit
		response, err := s.RealTimeSearchServiceClient.RealtimeSearch(ctx, request.Query, request.Vertical, searchOption)

		if err == nil {
			for _, res := range response {
				if res != nil {
					result = append(result, res.GetHits()...)
				}
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

var _ rpc.SearchServiceRPC = (*SearchServiceRpcImpl)(nil)
