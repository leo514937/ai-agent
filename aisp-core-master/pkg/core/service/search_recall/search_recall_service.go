package search_recall

import (
	"context"
	"math/rand"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/apollo"
)

type OutSiteSearchRecallType string

func (s *OutSiteSearchRecallType) String() string {
	return string(*s)
}

const (
	OutSiteSearchRecallTypeBing           OutSiteSearchRecallType = "bing"
	OutSiteSearchRecallTypeSougou         OutSiteSearchRecallType = "sougou"
	OutSiteSearchRecallTypeQuark          OutSiteSearchRecallType = "quark"
	OutSiteSearchRecallTypeBoCha          OutSiteSearchRecallType = "bocha"
	OutSiteSearchRecallTypeSerper         OutSiteSearchRecallType = "serper"
	OutSiteSearchRecallTypeBrave          OutSiteSearchRecallType = "brave"
	OutSiteSearchRecallTypeTavily         OutSiteSearchRecallType = "tavily"
	OutSiteSearchRecallTypeCloudSwayBing  OutSiteSearchRecallType = "cloud_sway_bing"
	OutSiteSearchRecallTypeCloudSwayQuark OutSiteSearchRecallType = "cloud_sway_quark"
	OutSiteSearchRecallTypeCloudSwaySerp  OutSiteSearchRecallType = "cloud_sway_serp"
	OutSiteSearchRecallTypeKexin          OutSiteSearchRecallType = "kexin"
)

type OutSiteSearchRecallService interface {
	// OutSiteSearchRecall 站外搜索召回
	OutSiteSearchRecall(ctx context.Context, searchType OutSiteSearchRecallType, query string, topK int32, traceId string, extParams map[string]string) []*rpc.OutSiteSearchRecallAnswerResult
}

type OutSiteSearchRecallServiceImpl struct {
	bingClient           rpc.BingClientRPC
	sougouClient         rpc.SougouClientHttp
	quarkClient          rpc.QuarkSearchRPC
	boChaClient          rpc.BoChaClientHTTP
	serperClient         rpc.OutSiteSearchApi
	braveClient          rpc.OutSiteSearchApi
	tavilyClient         rpc.OutSiteSearchApi
	cloudSwayBingClient  rpc.CloudSwayClientRPC
	cloudSwayQuarkClient rpc.CloudSwayClientRPC
	cloudSwaySerpClient  rpc.CloudSwayClientRPC
	kexinClient          rpc.KexinRPC
}

func NewOutSiteSearchRecallService() OutSiteSearchRecallService {
	return &OutSiteSearchRecallServiceImpl{
		bingClient:           impl.NewBingClientHttp(),
		sougouClient:         impl.NewSougouClientHttp(),
		quarkClient:          impl.NewQuarkSearchV2RPC(),
		boChaClient:          impl.NewBoChaClientHttp(),
		serperClient:         impl.NewSerperHttpClient(),
		braveClient:          impl.NewBraveSearchClient(),
		tavilyClient:         impl.NewTavilySearchClient(),
		cloudSwayBingClient:  impl.NewCloudSwayClientHttp(rpc.CloudSwayBingEndpointSearch),
		cloudSwayQuarkClient: impl.NewCloudSwayClientHttp(rpc.CloudSwayQuarkEndpointSearch),
		cloudSwaySerpClient:  impl.NewCloudSwayClientHttp(rpc.CloudSwaySerpEndpointSearch),
		kexinClient:          impl.NewKexinSearchRPC(),
	}
}

func (s *OutSiteSearchRecallServiceImpl) OutSiteSearchRecall(ctx context.Context, searchType OutSiteSearchRecallType, query string, topK int32, traceId string, extParams map[string]string) []*rpc.OutSiteSearchRecallAnswerResult {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "search_recall.OutSiteSearchRecall")
	defer span.Finish()
	logger := log.WithField(ctx, "OutSiteSearchRecall", map[string]any{
		"searchType": searchType,
		"query":      query,
	})
	switch searchType {
	case OutSiteSearchRecallTypeBing:
		searchRes, err := s.bingClient.BingSearch(ctx, query, topK, extParams)
		if err != nil {
			logger.Warnf(ctx, "bing search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeSougou:
		searchRes, err := s.sougouClient.SougouSearch(ctx, query, topK)
		if err != nil {
			logger.Errorf(ctx, "sougou search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeQuark:
		searchRes, err := s.quarkClient.Search(ctx, query, topK, traceId)
		if err != nil {
			logger.Errorf(ctx, "quark search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeKexin:
		if rand.Float64() >= apollo.GetFloat64(macro.KexinSwitchConfigName, 0.0) {
			return []*rpc.OutSiteSearchRecallAnswerResult{}
		}
		searchRes, err := s.kexinClient.Search(ctx, query, topK, traceId)
		if err != nil {
			logger.Errorf(ctx, "kexin search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeBoCha:
		// freshness 默认为无限制时间范围，具体可根据业务情况开启
		// isSummary 直接出summary 结果 这个根据情况看看是否要要开启
		searchRes, err := s.boChaClient.Search(ctx, query, topK, rpc.BoChaFreshnessNoLimit, true)
		if err != nil {
			logger.Errorf(ctx, "quark search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeSerper:
		searchRes, err := s.serperClient.Search(ctx, query, topK)
		if err != nil {
			logger.Errorf(ctx, "serper search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeBrave:
		searchRes, err := s.serperClient.Search(ctx, query, topK)
		if err != nil {
			logger.Errorf(ctx, "brave search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeTavily:
		searchRes, err := s.serperClient.Search(ctx, query, topK)
		if err != nil {
			logger.Errorf(ctx, "tavily search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeCloudSwayBing:
		searchRes, err := s.cloudSwayBingClient.Search(ctx, query, topK, extParams)
		if err != nil {
			logger.Errorf(ctx, "cloud sway bing search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeCloudSwayQuark:
		searchRes, err := s.cloudSwayQuarkClient.Search(ctx, query, topK, extParams)
		if err != nil {
			logger.Errorf(ctx, "cloud sway bing search error: %v", err)
		}
		return searchRes
	case OutSiteSearchRecallTypeCloudSwaySerp:
		searchRes, err := s.cloudSwaySerpClient.Search(ctx, query, topK, extParams)
		if err != nil {
			logger.Errorf(ctx, "cloud sway bing search error: %v", err)
		}
		return searchRes
	default:
	}
	return make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
}
