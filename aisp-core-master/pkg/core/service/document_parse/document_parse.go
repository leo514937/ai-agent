package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	impl2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

type DocumentParseService interface {
	// 内容平台结果 -> element
	PaperParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string)
	UserUploadParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string, string)
	RssParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string)

	// 上传 aisp 自维护的文件 -> 解析 -> 写入 db
	ConcurrentGetOssUrlFromPath(ctx context.Context, paths []string) map[string]string
	ReadContentFromOss(ctx context.Context, url string, path string) ([]byte, error)
	ParsePdfAndSave(ctx context.Context, fileBytes []byte, docId int64, docType string) error

	// 读取 db -> element
	GetDocumentParsingElement(ctx context.Context, docId int64, docType content.DocType_Type, processName rpc.ProcessorName) *model.Element

	// aisp-tools 的 html2markdown
	GetHtmlParsingElement(ctx context.Context, htmlBody string, processName rpc.ProcessorName, onlyText bool) *model.HtmpParseResponse
}

type DocumentParseServiceImpl struct {
	ossClient          rpc.Oss
	aispToolsClient    rpc.AispToolsClient
	documentParsingDao dao.DocumentParsingDao
}

var (
	DefaultDocumentParseService DocumentParseService
)

func init() {
	DefaultDocumentParseService = newtDocumentParseServiceImpl()
}

func newtDocumentParseServiceImpl() *DocumentParseServiceImpl {
	return &DocumentParseServiceImpl{
		ossClient:          impl.DefaultOssImpl,
		aispToolsClient:    impl.DefaultAispToolsClient,
		documentParsingDao: impl2.DefaultDocumentParsingDaoImpl,
	}
}

func (d *DocumentParseServiceImpl) PaperParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string) {
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
		// 复杂版
		if contentInfo.GetBizExtDetail().GetPaperBizExt().GetComplexURL() != "" {
			element := d.getElementFromOss(ctx, contentInfo.GetBizExtDetail().GetPaperBizExt().GetComplexURL())
			if element != nil {
				return element, element.Text
			}
		}
		// 简单版
		if contentInfo.GetBizExtDetail().GetPaperBizExt().GetEasyURL() != "" {
			element := d.getElementFromOss(ctx, contentInfo.GetBizExtDetail().GetPaperBizExt().GetEasyURL())
			if element != nil {
				return element, element.Text
			}
		}
		// 降级成 mediaDetail 的 pdfParsedText
		if contentInfo.GetMediaDetail() != nil {
			element := d.getElementFromPdfParsedText(ctx, contentInfo.GetMediaDetail().GetPdfParsedTxt())
			if element != nil {
				return element, element.Text
			}
		}
	}
	return nil, ""
}

func (d *DocumentParseServiceImpl) UserUploadParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string, string) {
	// 用户上传 pdf
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileSubType() == "pdf" {
		// 复杂版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL() != "" {
			element := d.getElementFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL())
			if element != nil {
				return element, element.Text, ""
			}
		}
		// 简单版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL() != "" {
			element := d.getElementFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL())
			if element != nil {
				return element, element.Text, ""
			}
		}
		// 降级成 mediaDetail 的 userUploadParsedContent
		if contentInfo.GetMediaDetail() != nil {
			element := d.getElementFromUserUploadParsedContent(ctx, contentInfo.GetMediaDetail().GetUserUploadParsedContent())
			if element != nil {
				return element, element.Text, ""
			}
		}
	}

	// 用户上传 text
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() == "text" && contentInfo.GetMediaDetail() != nil {
		return nil, contentInfo.GetMediaDetail().GetUserUploadParsedContent(), ""
	}

	// 用户上传 image
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() == "image" {
		// 复杂版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL() != "" {
			imageInfo := d.getImageFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL())
			if imageInfo != nil {
				return nil, imageInfo.Original, imageInfo.Summary
			}
		}
		// 简单版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL() != "" {
			imageInfo := d.getImageFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL())
			if imageInfo != nil {
				return nil, imageInfo.Original, imageInfo.Summary
			}
		}
	}

	// 2025年06月16日20:57:45 zpc
	// 其他-默认兜底处理
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() != "" {
		// 复杂版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL() != "" {
			resp := d.getMarkdownFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetComplexURL())
			if resp != nil && resp.Markdown != "" {
				return nil, resp.Markdown, ""
			}
		}
		// 简单版
		if contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL() != "" {
			resp := d.getMarkdownFromOss(ctx, contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetEasyURL())
			if resp != nil && resp.Markdown != "" {
				return nil, resp.Markdown, ""
			}
		}
	}
	return nil, "", ""
}

func (d *DocumentParseServiceImpl) RssParse(ctx context.Context, contentInfo *base.ContentInfo) (*model.Element, string) {
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetExternalWebpageBizExt() != nil {
		// s3 json
		markdownResp := &model.MarkdownResponse{}
		err := d.getObjectFromOss(ctx, contentInfo.GetBizExtDetail().GetExternalWebpageBizExt().GetModelParseS3Path(), markdownResp)
		if err == nil && markdownResp.Markdown != "" {
			return nil, markdownResp.Markdown
		}
		// 降级成 markdown
		mdPath := d.ossClient.GetOssFilePath(ctx, contentInfo.GetBizExtDetail().GetExternalWebpageBizExt().GetMdOssKey(), "aisp-core", "zhida", "community-assets")
		mdTxt, err := d.ossClient.GetFileBytes(ctx, mdPath)
		if err == nil {
			return nil, string(mdTxt)
		}
	}
	return nil, ""
}

func getObjectFromOssGeneric[T any](ossClient rpc.Oss, ctx context.Context, url string) *T {
	if url == "" {
		return nil
	}
	var resp T
	fileBytes, ossErr := ossClient.GetFileBytes(ctx, url)
	if ossErr == nil {
		unmarshalErr := json.Unmarshal(fileBytes, &resp)
		if unmarshalErr == nil {
			return &resp
		}
	}
	return nil
}

func (d *DocumentParseServiceImpl) getMarkdownFromOss(ctx context.Context, url string) *model.MarkdownResponse {
	return getObjectFromOssGeneric[model.MarkdownResponse](d.ossClient, ctx, url)
}

func (d *DocumentParseServiceImpl) getImageFromOss(ctx context.Context, url string) *model.ImageResponse {
	return getObjectFromOssGeneric[model.ImageResponse](d.ossClient, ctx, url)
}

func (d *DocumentParseServiceImpl) getElementFromOss(ctx context.Context, url string) *model.Element {
	complexResp := getObjectFromOssGeneric[model.ComplexResponse](d.ossClient, ctx, url)
	if complexResp != nil {
		for _, element := range complexResp.Elements {
			if element.Type == "main" && element.Text != "" {
				return element
			}
		}
	}
	return nil
}

func (d *DocumentParseServiceImpl) getElementFromPdfParsedText(ctx context.Context, pdfParsedText string) *model.Element {
	if pdfParsedText == "" {
		return nil
	}

	pdfParsedTextlines := strings.Split(pdfParsedText, "data:")
	var element *model.Element
	for _, line := range pdfParsedTextlines {
		if line == "" {
			continue
		}
		lineResp := &model.AispToolsResponse{}
		err := json.Unmarshal([]byte(line), lineResp)
		if err != nil {
			log.Warnf(ctx, "parse pdf result failed. err=%v", err)
			continue
		}
		if lineResp.Data != nil {
			for _, aispToolsItem := range lineResp.Data.Items {
				// 优先取 oss 里的
				if aispToolsItem.Name == "url" && aispToolsItem.Text != "" {
					element = d.getElementFromOss(ctx, aispToolsItem.Text)
					break
				}
				// 降级为直接取 pdf_element
				if aispToolsItem.Name == "pdf_element" && aispToolsItem.Element != nil && aispToolsItem.Element.Text != "" {
					element = aispToolsItem.Element
					break
				}
			}
		}
		if element != nil {
			return element
		}
	}
	return nil
}

func (d *DocumentParseServiceImpl) getObjectFromOss(ctx context.Context, url string, t interface{}) error {
	if url == "" {
		return nil
	}
	fileBytes, ossErr := d.ossClient.GetFileBytes(ctx, url)
	if ossErr == nil {
		unmarshalErr := json.Unmarshal(fileBytes, t)
		if unmarshalErr == nil {
			return nil
		}
	}
	return nil
}

func (d *DocumentParseServiceImpl) getElementFromUserUploadParsedContent(ctx context.Context, userUploadParsedContent string) *model.Element {
	if userUploadParsedContent == "" {
		return nil
	}

	aispToolsItem := &model.AispToolsItem{}
	err := json.Unmarshal([]byte(userUploadParsedContent), aispToolsItem)
	if err != nil {
		log.Warnf(ctx, "parse user_upload_parsed_content failed. err=%v", err)
		return nil
	}

	if aispToolsItem.Name == "url" && aispToolsItem.Text != "" {
		return d.getElementFromOss(ctx, aispToolsItem.Text)
	}
	return aispToolsItem.Element
}

func (d *DocumentParseServiceImpl) ParsePdfAndSave(ctx context.Context, fileBytes []byte, docId int64, docType string) error {
	// pdf 简单版解析
	easyParseUrl, easyVersion := d.parsePdf(ctx, fileBytes, rpc.ProcessorNameRulePdfParser)
	// pdf 复杂版解析
	complexParseUrl, complexVersion := d.parsePdf(ctx, fileBytes, rpc.ProcessorNameVisionPdfParser)

	if easyParseUrl == "" && complexParseUrl == "" {
		return errors.New("pdf parse empty")
	}

	// pdf 简单版解析结果写入数据库
	easyInsertErr := d.insertParsingResult(ctx, easyParseUrl, easyVersion, docId, docType, rpc.ProcessorNameRulePdfParser)
	// pdf 复杂版解析结果写入数据库
	complexInsertErr := d.insertParsingResult(ctx, complexParseUrl, complexVersion, docId, docType, rpc.ProcessorNameVisionPdfParser)

	if easyInsertErr != nil || complexInsertErr != nil {
		log.Errorf(ctx, "insert document parsing error. easyInsertErr=%v, complexInsertErr=%v", easyInsertErr, complexInsertErr)
		return errors.New("pdf parse insert error")
	}

	return nil
}

func (d *DocumentParseServiceImpl) parsePdf(ctx context.Context, fileBytes []byte, processorName rpc.ProcessorName) (parseUrl, version string) {
	pdfParseResult, parseErr := d.aispToolsClient.ParsePdf(ctx, processorName, fileBytes)
	if parseErr != nil {
		return "", ""
	}
	for _, item := range pdfParseResult {
		if item.Name == "url" {
			parseUrl = item.GetText()
		}
		if item.Name == "version" {
			version = item.GetText()
		}
	}
	return parseUrl, version
}

func (d *DocumentParseServiceImpl) insertParsingResult(ctx context.Context, parseUrl string, version string, docId int64, docType string, processorName rpc.ProcessorName) error {
	documentParsing := &model.DocumentParsingBase{
		DocId:            docId,
		DocType:          docType,
		ProcessorType:    rpc.ProcessorTypePdfParser.String(),
		ProcessorName:    processorName.String(),
		ProcessorVersion: version,
		ItemName:         "url",
		ContentUrl:       parseUrl,
	}
	// 判断是否存在，避免重复写入
	existDoc, selectErr := d.documentParsingDao.GetDocumentParsing(ctx, docId, content.DocType_Type(content.DocType_Type_value[docType]), documentParsing.ProcessorName)
	if selectErr != nil || existDoc == nil {
		return d.documentParsingDao.InsertDocumentParsing(ctx, documentParsing)
	} else {
		return d.documentParsingDao.UpdateDocumentParsing(ctx, documentParsing)
	}
}

func (d *DocumentParseServiceImpl) ConcurrentGetOssUrlFromPath(ctx context.Context, paths []string) map[string]string {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetOssUrlFromPath", 2000).SetLimit(10)
	for _, path := range paths {
		path := path
		group.Go(func() error {
			resultMap.Store(path, d.GetOssUrlFromPath(ctx, path))
			return nil
		})
	}
	_ = group.Wait()

	result := map[string]string{}
	for _, path := range paths {
		if res, ok := resultMap.Load(path); ok {
			result[path] = res.(string)
		} else {
			result[path] = ""
		}
	}

	return result
}

func (d *DocumentParseServiceImpl) GetOssUrlFromPath(ctx context.Context, path string) string {
	return d.ossClient.GetOssFilePath(ctx, path, "aisp-core", "zhida", "community-assets")
}

func (d *DocumentParseServiceImpl) ReadContentFromOss(ctx context.Context, url string, path string) ([]byte, error) {
	if path != "" {
		url = d.GetOssUrlFromPath(ctx, path)
	}
	return d.ossClient.GetFileBytes(ctx, url)
}

func (d *DocumentParseServiceImpl) GetDocumentParsingElement(ctx context.Context, docId int64, docType content.DocType_Type, processName rpc.ProcessorName) *model.Element {
	documentParsing, err := d.documentParsingDao.GetDocumentParsing(ctx, docId, docType, processName.String())
	if err != nil || documentParsing == nil {
		log.Errorf(ctx, "GetDocumentParsing error: %v", err)
		return nil
	}

	// 对于 url 类型的结果，从 oss url 里获取解析内容
	if documentParsing.ItemName == "url" && documentParsing.ContentUrl != "" {
		return d.getElementFromOss(ctx, documentParsing.ContentUrl)
	}
	return nil
}

func (d *DocumentParseServiceImpl) GetHtmlParsingElement(ctx context.Context, htmlBody string, processName rpc.ProcessorName, onlyText bool) *model.HtmpParseResponse {
	aispToolItems, err := d.aispToolsClient.ParseHtml(ctx, processName, []byte(htmlBody), "GetHtmlParsingElement", "")
	if err != nil {
		return nil
	}

	var aispToolUrlItem *model.AispToolsItem
	for _, aispToolItem := range aispToolItems {
		if aispToolItem.Name == "url" {
			aispToolUrlItem = aispToolItem
			break
		}
	}
	if aispToolUrlItem == nil {
		return nil
	}

	htmlResp := &model.HtmpParseResponse{}
	err = d.getObjectFromOss(ctx, aispToolUrlItem.GetText(), htmlResp)

	if err != nil {
		return nil
	}

	// 纯文本模式，过滤掉图片
	if onlyText {
		d.filterImagesFromBlocks(htmlResp)
	}

	return htmlResp
}

// filterImagesFromBlocks 过滤掉包含图片的块，如果过滤后内容为空则删除该块
func (d *DocumentParseServiceImpl) filterImagesFromBlocks(htmlResp *model.HtmpParseResponse) {
	if htmlResp == nil || len(htmlResp.Blocks) == 0 {
		return
	}

	var filteredBlocks []*model.ContentBlock

	for _, block := range htmlResp.Blocks {
		// 检查该块是否包含图片
		if imageRefs, exists := htmlResp.Images[block.ID]; exists && len(imageRefs) > 0 {
			// 从内容中移除所有图片标记
			content := block.Content
			for _, imageRef := range imageRefs {
				content = strings.ReplaceAll(content, imageRef.Marker, "")
			}

			// 清理多余的空格和换行
			content = strings.TrimSpace(content)

			// 如果内容不为空，保留该块
			if content != "" {
				block.Content = content
				filteredBlocks = append(filteredBlocks, block)
			}
		} else {
			// 不包含图片的块直接保留
			filteredBlocks = append(filteredBlocks, block)
		}
	}

	// 更新过滤后的块列表
	htmlResp.Blocks = filteredBlocks
}
