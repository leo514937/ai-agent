package handler_zhihu

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	content2 "git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/content_meta"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

// ContentCoreHandler 内容平台服务HTTP处理器
type ContentCoreHandler struct {
	rest.BaseHandler
	contentMetaService content_meta.ContentMetaService
}

// NewContentCoreHandler 创建内容平台服务处理器
func NewContentCoreHandler() rest.Handler {
	return &ContentCoreHandler{
		contentMetaService: content_meta.DefaultContentMetaService,
	}
}

// 请求结构体
type ContentCoreRequestDTO struct {
	Contents []ContentDTO `json:"contents"`
	Fields   []string     `json:"fields"`
}

type ContentDTO struct {
	OutID    int64  `json:"out_id"`
	DocType  int64  `json:"doc_type"`
	URLToken string `json:"url_token,omitempty"`
}

// 响应结构体
type ContentCoreResponseDTO struct {
	ContentID        int64                       `json:"content_id"`
	DocType          int64                       `json:"doc_type"`
	URLToken         string                      `json:"url_token,omitempty"`
	ContentInfo      *base.ContentInfo           `json:"content_info,omitempty"`
	ContentStatistic *content2.ContentStatistics `json:"content_statistic,omitempty"`
	Text             string                      `json:"text"`
	Element          *model.Element              `json:"element"`
	ContentLevel     int                         `json:"content_level"` // 内容等级
	AuthorLevel      int                         `json:"author_level"`
}

// Post 处理POST请求，调用内容平台服务
func (h *ContentCoreHandler) Post(ctx *rest.Context) (rest.Response, error) {
	logger := log.WithField(ctx, "ContentCoreHandler.Post", "start")

	// 解析请求参数
	var requestDTO ContentCoreRequestDTO
	err := ctx.JSONArgs(&requestDTO)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to parse request")
		return nil, err
	}

	logger.Infof(ctx, "RequestParams:%v", requestDTO)

	var contents []model.Content
	for _, contentDTO := range requestDTO.Contents {
		docType := content.DocType_Type(contentDTO.DocType)

		var content model.Content
		if contentDTO.OutID != 0 {
			content = model.NewContentWithDocType(contentDTO.OutID, docType)
		} else if contentDTO.URLToken != "" {
			content = model.NewContentWithToken(contentDTO.URLToken, docType.String())
		} else {
			logger.Warnf(ctx, "invalid content: out_id=%d, url_token=%s", contentDTO.OutID, contentDTO.URLToken)
			continue
		}
		contents = append(contents, content)
	}

	responseList := h.contentMetaService.BatchGetContentMeta(ctx, contents)

	logger.Infof(ctx, "Response count: %d", len(responseList))

	return ResponseSuccess(responseList)
}
