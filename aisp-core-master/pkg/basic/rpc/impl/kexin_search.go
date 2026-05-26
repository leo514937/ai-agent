package impl

import (
	"context"
	"time"

	cafegrpc "git.in.zhihu.com/go/base/grpc"
	"git.in.zhihu.com/pb-go/zsearch-proto/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const (
	timeoutMillSecondsKexin = 2000
	targetNameKexin         = "zsearch-root-service"
	tenantCode              = "ai_card"
)

// KexinSearchRPCImpl 基于 ZSearch RootService 的实现
type KexinSearchRPCImpl struct {
	client root.ZSearchRootServiceClient
}

func NewKexinSearchRPC() rpc.KexinRPC {
	conn, err := cafegrpc.DialContext(context.Background(), targetNameKexin)
	if err != nil {
		// 记录错误日志，并返回nil，防止panic
		log.Errorf(context.Background(), "failed to dial zsearch-root-service: %v", err)
		return nil
	}
	return &KexinSearchRPCImpl{client: root.NewZSearchRootServiceClient(conn)}
}

func (k *KexinSearchRPCImpl) Search(ctx context.Context, query string, topK int32, traceId string) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "KexinSearch", map[string]any{"query": query, "topK": topK})

	ctxWithTimeout, cancel := context.WithTimeout(ctx, timeoutMillSecondsKexin*time.Millisecond)
	defer cancel()

	req := &root.RootSearchRequest{
		ContextInfo: &root.ContextInfo{
			SearchHashId: traceId,
		},
		QueryInfo:  &root.QueryInfo{Query: query},
		Limit:      int64(topK),
		TenantCode: tenantCode,
	}

	var resp *root.RootSearchResponse
	var err error
	runFunc := func(ctx context.Context) error {
		resp, err = k.client.Search(ctxWithTimeout, req)
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctxWithTimeout, runFunc)
	if err != nil {
		logger.Errorf(ctx, "kexin root search error: %v", err)
		return []*rpc.OutSiteSearchRecallAnswerResult{}, err
	}
	if resp == nil {
		return []*rpc.OutSiteSearchRecallAnswerResult{}, nil
	}

	results := make([]*rpc.OutSiteSearchRecallAnswerResult, 0, len(resp.Items))
	for _, item := range resp.Items {
		if item == nil || item.DocInfo == nil {
			continue
		}
		// 将 Root 返回的字段映射到统一的站外召回结构
		r := &rpc.OutSiteSearchRecallAnswerResult{
			Url:           item.DocInfo.Url,
			Name:          item.DocInfo.Title,
			Snippet:       item.DocInfo.Snippet,
			MainText:      item.DocInfo.Content,
			PublishedTime: int64(item.DocInfo.PublishTime),
		}
		multiScore := item.GetScoreInfo().GetMultiScore()
		if multiScore != nil {
			r.ExtraInfo = &model.ExtraInfo{
				RelevanceScore:  multiScore["rel_score"],
				TimelinessScore: multiScore["recency_score"],
				AuthorityScore:  multiScore["authority_score"],
				AuthorityLevel:  multiScore["authority_level"],
				RelevanceLevel:  multiScore["rel_level"],
			}
		}
		results = append(results, r)
	}
	return results, nil
}
