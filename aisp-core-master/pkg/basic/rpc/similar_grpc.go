package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content_grpc"
	"github.com/samber/lo"
)

type SimilarGRPC interface {
	GetSimilarV2(ctx context.Context, queryTexts []string, dstTexts []string, sourceCode SourceCode) (*content_grpc.SimilarResponse, error)

	GetSearchV2(ctx context.Context, query string, sourceCode SourceCode, topK int32) []*lo.Tuple2[*content_grpc.ContentItem, float64]
}

// SourceCode 场景码
type SourceCode string

const (
	// SimilarSourceCodeV2Code 领域bot
	SimilarSourceCodeV2Code SourceCode = "domain-bot-similar"
	// SimilarSourceCodeParagraphKeyword 段落拓展词
	SimilarSourceCodeParagraphKeyword SourceCode = "paragraph-keyword-theme"
	// SimilarSourceCodeInterestKeyword 兴趣词
	SimilarSourceCodeInterestKeyword SourceCode = "interest-keyword-theme"
	SimilarSourceCodeBgeSimilar      SourceCode = "bge-similar-zhi-news"
)
