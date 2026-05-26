package impl

import (
	"context"
	"sort"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

var (
	_                      rpc.SimilarGRPC = (*SimilarGrpcImpl)(nil)
	DefaultSimilarGrpcImpl rpc.SimilarGRPC
)

func newSimilarGrpcImpl() *SimilarGrpcImpl {
	similarSearch, err := grpc.DialContext(context.Background(), "zai-match-search")
	if err != nil {
		log.Errorf(context.Background(), "dial zai-match-search failed. err: %+v", err)

		panic(err)
	}

	similarV2aConn, err := grpc.DialContext(context.Background(), "zai-match-similar-v2a")
	if err != nil {
		log.Errorf(context.Background(), "dial zai-match-similar-v2a failed. err: %+v", err)

		panic(err)
	}

	return &SimilarGrpcImpl{
		similarSearchClient: content_grpc.NewSimilarServiceClient(similarSearch),
		similarV2aClient:    content_grpc.NewSimilarServiceClient(similarV2aConn),
		timeout:             1000 * time.Millisecond,
	}
}

type SimilarGrpcImpl struct {
	timeout             time.Duration
	similarSearchClient content_grpc.SimilarServiceClient
	similarV2aClient    content_grpc.SimilarServiceClient
}

func init() {
	DefaultSimilarGrpcImpl = newSimilarGrpcImpl()
}

func (s SimilarGrpcImpl) GetSearchV2(ctx context.Context, query string, sourceCode rpc.SourceCode, topK int32) []*lo.Tuple2[*content_grpc.ContentItem, float64] {
	var resArr []*lo.Tuple2[*content_grpc.ContentItem, float64]
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, s.timeout)
		defer cancel()

		request := &content_grpc.SearchV2Request{
			Target: &content_grpc.ContentItem{
				Content: query,
				DocType: content.DocType_Text,
			},
			SourceCode: string(sourceCode),
			Max:        topK,
		}
		searchRes, err := s.similarSearchClient.SearchV2(newCtx, request)
		if err != nil {
			return err
		}

		// Map 操作 转换 为 Tuple 数组
		resArr = lo.Map(searchRes.GetItems(),
			func(item *content_grpc.SimilarItem, i int) *lo.Tuple2[*content_grpc.ContentItem, float64] {
				return &lo.Tuple2[*content_grpc.ContentItem, float64]{
					A: item.Candidate,
					B: item.Score,
				}
			})
		// Score 倒序排序
		sort.Slice(resArr, func(i, j int) bool {
			return resArr[i].B > resArr[j].B
		})
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return resArr
}

func (s SimilarGrpcImpl) GetSimilarV2(ctx context.Context, queryTexts []string, dstTexts []string, sourceCode rpc.SourceCode) (*content_grpc.SimilarResponse, error) {
	var resp *content_grpc.SimilarResponse
	var err error
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, s.timeout)
		defer cancel()

		var targetItems []*content_grpc.ContentItem
		var candidateItems []*content_grpc.ContentItem

		for _, queryText := range queryTexts {
			targetItems = append(targetItems, &content_grpc.ContentItem{
				DocType: content.DocType_Text,
				Content: queryText,
			})
		}

		for _, dstText := range dstTexts {
			candidateItems = append(candidateItems, &content_grpc.ContentItem{
				DocType: content.DocType_Text,
				Content: dstText,
			})
		}

		request := &content_grpc.SimilarV2Request{
			Targets:    targetItems,
			Candidates: candidateItems,
			SourceCode: string(sourceCode),
		}

		resp, err = s.similarV2aClient.SimilarV2(newCtx, request)
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return resp, err
}
