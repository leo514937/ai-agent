package rpc

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/structured_doc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type ContentCoreRPC interface {
	BatchGetContent(ctx context.Context, items []model.Content, withFields ...string) map[model.Content]*base.ContentInfo
	BatchGetContentByContentID(ctx context.Context, contentIds []string, withFields ...string) map[string]*base.ContentInfo
	// BatchGetStructuredSegmentsByContentIDs 根据id批量获取结构化片段
	BatchGetStructuredSegmentsByContentIDs(ctx context.Context, contentId model.Content, paragraphs []*proto.DocQaExtraParagraphInfo, withFields ...string) []*ParagraphExpansionWord
	// BatchGetContentPaperByOutSiteTypeId 批量站外Arxiv和WeiPu 信息转Content Paper
	BatchGetContentPaperByOutSiteTypeId(ctx context.Context, papers []OutSitePaper) map[OutSitePaper]*model.Content
}

type OutSitePaperType string

const (
	OutSitePaperTypeArxiv OutSitePaperType = "Arxiv"
	OutSitePaperTypeWeiPu OutSitePaperType = "WeiPu"
)

type OutSitePaper struct {
	PaperType OutSitePaperType
	OutId     string
}

type ParagraphExpansionWord structured_doc.ParagraphExpansionWord
