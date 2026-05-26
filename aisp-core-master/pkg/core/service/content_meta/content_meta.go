package content_meta

import (
	"context"

	tag_core "git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	content3 "git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

type ContentMetaService interface {
	BatchGetContentMeta(ctx context.Context, contents []model.Content) []*ContentCoreResponseDTO
}

// 响应结构体
type ContentCoreResponseDTO struct {
	ContentID        int64                      `json:"content_id"`
	DocType          content2.DocType_Type      `json:"doc_type"`
	URLToken         string                     `json:"url_token,omitempty"`
	ContentInfo      *base.ContentInfo          `json:"content_info,omitempty"`
	ContentStatistic *content.ContentStatistics `json:"content_statistic,omitempty"`
	Text             string                     `json:"text"`
	Element          *model.Element             `json:"element"`
	ContentLevel     int                        `json:"content_level"` // 内容等级
	AuthorLevel      int                        `json:"author_level"`
	PdfUrl           string                     `json:"pdf_url,omitempty"`
}

type ContentMetaServiceImpl struct {
	contentCoreRPC       rpc.ContentCoreRPC
	contentProdRpc       rpc.ContentProdRPC
	tagCoreRpc           rpc.TagCoreGRPC
	documentParseService service.DocumentParseService
}

var (
	DefaultContentMetaService ContentMetaService
)

func init() {
	DefaultContentMetaService = newContentMetaService()
}

func newContentMetaService() *ContentMetaServiceImpl {
	return &ContentMetaServiceImpl{
		contentCoreRPC:       impl.DefaultContentCoreRPCImpl,
		contentProdRpc:       impl.NewContentProdRPCImpl(),
		tagCoreRpc:           impl.DefaultTagGrpcImpl,
		documentParseService: service.DefaultDocumentParseService,
	}
}

func (c *ContentMetaServiceImpl) BatchGetContentMeta(ctx context.Context, contents []model.Content) []*ContentCoreResponseDTO {
	logger := log.WithField(ctx, "fetchContentInfo", "start")

	fields := []string{
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary,
	}

	// 调用内容平台服务 - 使用 safe_group 并发执行三个互相不依赖的调用
	var contentMetaMap map[model.Content]*base.ContentInfo
	var contentStatisticMap map[model.Content]*content3.Content
	var contentTagMap map[model.Content]*tag_core.ObjectProfile
	var authorTagMap map[model.Content]*tag_core.ObjectProfile
	var pdfPathUrlMap map[string]string

	// 创建并发组，设置超时时间和并发限制
	group := safe_group.NewGroupWithTimeout("ContentCoreHandler", 5000).SetLimit(3)

	// 并发获取内容元数据
	group.Go(func() error {
		contentMetaMap = c.contentCoreRPC.BatchGetContent(ctx, contents, fields...)
		// 获取作者标签
		var authorContents []model.Content
		for _, contentInfo := range contentMetaMap {
			authorContents = append(authorContents, model.Content{
				ContentID:   contentInfo.GetAuthorID(),
				ContentType: content2.DocType_Member,
			})
		}
		authorTagMap = c.tagCoreRpc.BatchGetTag(ctx, rpc.SceneCode_AiUserInterest, rpc.AppGroupCode_AiUserRecall, authorContents)
		// 获取 pdf oss 链接
		var pdfPaths []string
		for _, contentInfo := range contentMetaMap {
			if contentInfo.GetBizExtDetail() != nil &&
				contentInfo.GetBizExtDetail().GetPaperBizExt() != nil &&
				contentInfo.GetBizExtDetail().GetPaperBizExt().GetPdfPath() != "" {
				pdfPaths = append(pdfPaths, contentInfo.GetBizExtDetail().GetPaperBizExt().GetPdfPath())
			}
		}

		if len(pdfPaths) > 0 {
			pdfPathUrlMap = c.documentParseService.ConcurrentGetOssUrlFromPath(ctx, pdfPaths)
		}
		return nil
	})

	// 并发获取内容统计信息
	group.Go(func() error {
		contentStatisticMap = c.contentProdRpc.BatchGetContent(ctx, contents, &content.WithFieds{
			StatisticsFields: &content.StatisticsFields{
				AllStatistics: lo.ToPtr(true),
			},
		})
		return nil
	})

	// 并发获取内容标签
	group.Go(func() error {
		contentTagMap = c.tagCoreRpc.BatchGetTag(ctx, rpc.SceneCode_AiUserInterest, rpc.AppGroupCode_AiUserRecall, contents)
		return nil
	})

	// 等待所有并发调用完成
	if err := group.Wait(); err != nil {
		logger.Errorf(ctx, "ContentCoreHandler concurrent calls failed: %v", err)
		return nil
	}

	// 转换为响应格式
	var responseList []*ContentCoreResponseDTO
	for key, contentInfo := range contentMetaMap {
		var element *model.Element
		var text string

		// 维普 arxiv 的 pdf
		if key.ContentType == content2.DocType_Paper {
			element, text = c.documentParseService.PaperParse(ctx, contentInfo)
		}

		// 用户上传
		if key.ContentType == content2.DocType_ZhiDaUserUpload {
			element, text, _ = c.documentParseService.UserUploadParse(ctx, contentInfo)
		}

		// 个人知识库订阅流
		if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetExternalWebpageBizExt() != nil {
			_, text = c.documentParseService.RssParse(ctx, contentInfo)
		}

		// 图文类型
		if contentInfo.GetContentBody() != nil {
			// 清洗正文
			body := contentInfo.GetContentBody().GetBody()
			filteredBody, err := util.ContentHtml2Markdown(ctx, body)
			if err == nil {
				text = filteredBody
			}
		}

		// 内容统计信息
		var contentStatistic *content.ContentStatistics
		if statistic, exist := contentStatisticMap[key]; exist && statistic != nil {
			contentStatistic = statistic.GetContentStatistics()
		}

		// 内容等级 & 作者等级
		var contentLevel string
		var authorLevel int
		if level, exist := contentTagMap[key]; exist && level != nil {
			contentLevel = util2.GetContentSubjectiveLevelTagValue(level.GetTags())
		}
		if level, exist := authorTagMap[model.NewContentWithDocType(contentInfo.GetAuthorID(), content2.DocType_Member)]; exist && level != nil {
			authorLevel = util2.GetCreatorDocLevelTagValue(level.GetTags())
		}

		// pdf oss url
		var pdfOssUrl string
		if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
			if url, exist := pdfPathUrlMap[contentInfo.GetBizExtDetail().GetPaperBizExt().GetPdfPath()]; exist && url != "" {
				pdfOssUrl = url
			}
		}

		responseDTO := &ContentCoreResponseDTO{
			ContentID:        key.ContentID,
			DocType:          key.ContentType,
			URLToken:         key.URLToken,
			ContentInfo:      contentInfo,
			ContentStatistic: contentStatistic,
			Text:             text,
			Element:          element,
			ContentLevel:     int(util.SafeString2Int64(contentLevel, 0)),
			AuthorLevel:      authorLevel,
			PdfUrl:           pdfOssUrl,
		}
		responseList = append(responseList, responseDTO)
	}

	return responseList
}
