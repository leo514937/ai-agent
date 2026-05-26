package handler_zhihu

import (
	"bytes"
	"context"
	"errors"
	"io"
	"mime"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	md "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	"github.com/samber/lo"
)

// KnowledgeBasesHandler 知识库处理
type KnowledgeBasesHandler struct {
	rest.BaseHandler
	knowledgeBaseService    knowledge_base.KnowledgeBaseService
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesHandler() rest.Handler {
	return &KnowledgeBasesHandler{
		knowledgeBaseService:    knowledge_base.DefaultKnowledgeBaseService,
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

type KnowledgeBaseReqDTO struct {
	Name string `json:"name"`
}

func (k *KnowledgeBasesHandler) Post(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	req := KnowledgeBaseReqDTO{}
	err := ctx.JSONArgs(&req)
	if err != nil {
		return nil, err
	}
	if req.Name == "" {
		return nil, errors.New("知识库名称不能为空")
	}
	uniqueId, err := k.knowledgeBaseService.CreateKnowLedgeBase(ctx, req.Name, userId, false)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(map[string]string{"unique_id": uniqueId})
}

func (k *KnowledgeBasesHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBases, err := k.knowledgeBaseService.FindByCreatorUserId(ctx, userId)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(knowledgeBases)
}

// SingleKnowledgeBasesHandler 单个知识库知识库处理
type SingleKnowledgeBasesHandler struct {
	rest.BaseHandler
	knowledgeBaseService    knowledge_base.KnowledgeBaseService
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewSingleKnowledgeBasesHandler() rest.Handler {
	return &SingleKnowledgeBasesHandler{
		knowledgeBaseService:    knowledge_base.DefaultKnowledgeBaseService,
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

func (k *SingleKnowledgeBasesHandler) Patch(ctx *rest.Context) (rest.Response, error) {
	knowledgeBaseId := ctx.URLParam("id")
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	req := KnowledgeBaseReqDTO{}
	err := ctx.JSONArgs(&req)
	if req.Name == "" {
		return nil, errors.New("知识库名称不能为空")
	}

	knowledgeBase, err := k.knowledgeBaseService.FindById(ctx, knowledgeBaseId)
	if knowledgeBase.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	knowledgeBase = &model.KnowledgeBase{
		UniqueId:          knowledgeBase.UniqueId,
		KnowledgeBaseName: req.Name,
	}

	err = k.knowledgeBaseService.UpdateKnowLedgeBase(ctx, knowledgeBase)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(nil)
}

func (k *SingleKnowledgeBasesHandler) Delete(ctx *rest.Context) (rest.Response, error) {
	knowledgeBaseId := ctx.URLParam("id")
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBase, err := k.knowledgeBaseService.FindById(ctx, knowledgeBaseId)
	if knowledgeBase.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	knowledgeBase = &model.KnowledgeBase{
		UniqueId: knowledgeBase.UniqueId,
		State:    model.KnowledgeBaseStateDeleted,
	}

	err = k.knowledgeBaseService.UpdateKnowLedgeBase(ctx, knowledgeBase)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(nil)
}

func (k *SingleKnowledgeBasesHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBaseId := ctx.URLParam("id")

	knowledgeBase, err := k.knowledgeBaseService.FindByIdWithDocs(ctx, knowledgeBaseId)
	if err != nil {
		return nil, err
	}
	if knowledgeBase.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	return ResponseSuccess(knowledgeBase)
}

// KnowledgeBasesDocumentHandler 知识库文件处理
type KnowledgeBasesDocumentHandler struct {
	rest.BaseHandler
	knowledgeBaseService    knowledge_base.KnowledgeBaseService
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesDocHandler() rest.Handler {
	return &KnowledgeBasesDocumentHandler{
		knowledgeBaseService:    knowledge_base.DefaultKnowledgeBaseService,
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

func getContentByUrlToken(ctx context.Context, docType content.DocType_Type, urlToken string) *base.ContentInfo {
	content := model.Content{
		URLToken:    urlToken,
		ContentType: docType,
	}
	contents := []model.Content{
		content,
	}
	contentResultMap := rpcImpl.DefaultContentCoreRPCImpl.BatchGetContent(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody)

	return contentResultMap[content]

}

type KnowledgeBaseDocReqDTO struct {
	UploadUrl             string `json:"upload_url"`
	KnowledgeBaseUniqueId string `json:"knowledge_base_unique_id"`
	Name                  string `json:"name"`
}

// Post 上传文档或链接
func (k *KnowledgeBasesDocumentHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var rawDocs []*model.KnowledgeBaseDocRaw
	var knowledgeBaseId string
	var err error
	var docType model.KnowledgeBaseDocSourceType
	contentType := ctx.Request.Header.Get("Content-Type")
	mediaType, _, _ := mime.ParseMediaType(contentType)
	if mediaType == "multipart/form-data" {
		err = ctx.Request.ParseMultipartForm(32 << 20)
		if err != nil {
			return nil, err
		}
		fileHeaders := lo.Flatten(lo.Values(ctx.Request.MultipartForm.File))
		if len(fileHeaders) > 5 {
			return nil, errors.New("文件数量不能超过5个")
		}

		if len(fileHeaders) != 0 {
			for _, fileHeader := range fileHeaders {
				file, err := fileHeader.Open()
				if err != nil {
					log.Errorf(ctx, "read file error. err=%v", err)
					continue
				}

				var buffer bytes.Buffer
				_, err = io.Copy(&buffer, file)
				if err != nil {
					log.Errorf(ctx, "read file error. err=%v", err)
					return nil, err
				}
				fileContent := buffer.Bytes()
				rawDocs = append(rawDocs, &model.KnowledgeBaseDocRaw{
					FileContent: fileContent,
					FileName:    fileHeader.Filename,
					DocType:     model.KnowledgeBaseDocSourcePdf,
				})
			}
		}

		knowledgeBaseId = ctx.Request.Form.Get("knowledge_base_unique_id")
	} else {
		req := KnowledgeBaseDocReqDTO{}
		err := ctx.JSONArgs(&req)
		if err != nil {
			return nil, err
		}

		var fileContent []byte
		var fileName string
		linkType, subType, token := util.ParseLinkInfo(req.UploadUrl)
		if linkType == util.LinkTypeZhihu {
			content := getContentByUrlToken(ctx, model.GetDocType(subType), token)
			if content == nil {
				return nil, errors.New("链接不存在")
			}

			fileContent = []byte(content.GetContentBody().GetBody())
			fileName = content.GetTitle()
			docType = model.KnowledgeBaseDocSourceUrlZhihu
		} else {
			pageContent, err := rpcImpl.DefaultCrawlerRpc.RealTimeCrawler(ctx, req.UploadUrl)
			if err != nil {
				return nil, err
			}

			if pageContent == nil || pageContent.Content == "" || pageContent.Title == "" {
				return nil, errors.New("链接解析错误")
			}

			fileContent = []byte(pageContent.Content)
			fileName = pageContent.Title
			docType = model.KnowledgeBaseDocSourceUrlOutSite
		}

		rawDocs = append(rawDocs, &model.KnowledgeBaseDocRaw{
			FileContent: fileContent,
			FileName:    fileName,
			DocType:     docType,
		})
		knowledgeBaseId = req.KnowledgeBaseUniqueId
	}

	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	// 没有指定知识库，需要创建一个临时的，用于精读场景
	if knowledgeBaseId == "" {
		knowledgeBaseId, err = k.knowledgeBaseService.CreateKnowLedgeBase(ctx, "default", userId, true)
		if err != nil {
			return nil, err
		}
	}

	knowledgeBase, err := k.knowledgeBaseService.FindById(ctx, knowledgeBaseId)
	if knowledgeBase.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	docs, err := k.knowledgeBaseDocService.BatchCreateKnowLedgeBaseDoc(ctx, rawDocs, knowledgeBase, userId)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(docs)
}

// KnowledgeBasesSingleDocumentHandler 知识库单个文件处理
type KnowledgeBasesSingleDocumentHandler struct {
	rest.BaseHandler
	knowledgeBaseService    knowledge_base.KnowledgeBaseService
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesSingleDocHandler() rest.Handler {
	return &KnowledgeBasesSingleDocumentHandler{
		knowledgeBaseService:    knowledge_base.DefaultKnowledgeBaseService,
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

// Get 获取文件
func (k *KnowledgeBasesSingleDocumentHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBaseId := ctx.URLParam("id")

	knowledgeBaseDoc, err := k.knowledgeBaseDocService.FindByDocId(ctx, knowledgeBaseId, true)
	if err != nil {
		return nil, err
	}

	if knowledgeBaseDoc.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	return ResponseSuccess(knowledgeBaseDoc)
}

func (k *KnowledgeBasesSingleDocumentHandler) Delete(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBaseId := ctx.URLParam("id")

	knowledgeBaseDoc, err := k.knowledgeBaseDocService.FindByDocId(ctx, knowledgeBaseId, false)
	if err != nil {
		return nil, err
	}

	if knowledgeBaseDoc.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	err = k.knowledgeBaseDocService.DeleteByDocId(ctx, knowledgeBaseDoc.UniqueId)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(nil)
}

func (k *KnowledgeBasesSingleDocumentHandler) Patch(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	knowledgeBaseId := ctx.URLParam("id")

	knowledgeBaseDoc, err := k.knowledgeBaseDocService.FindByDocId(ctx, knowledgeBaseId, false)
	if err != nil {
		return nil, err
	}

	if knowledgeBaseDoc.CreatorUserId != userId {
		return nil, errors.New("无权限查看")
	}

	req := KnowledgeBaseDocReqDTO{}
	err = ctx.JSONArgs(&req)
	if err != nil {
		return nil, err
	}
	err = k.knowledgeBaseDocService.Update(ctx, knowledgeBaseDoc.UniqueId, req.Name)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(nil)
}

// KnowledgeBasesDocDetailHandler 文档详情
type KnowledgeBasesDocDetailHandler struct {
	rest.BaseHandler
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesDocDetailHandler() rest.Handler {
	return &KnowledgeBasesDocDetailHandler{
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

func (k *KnowledgeBasesDocDetailHandler) Get(ctx *rest.Context) (rest.Response, error) {
	docIdStr := ctx.QueryArgumentWithFallback("docId", "")

	if docIdStr == "" {
		return nil, errors.New("docId为空")
	}

	docDetail, err := k.knowledgeBaseDocService.GetDocDetail(ctx, docIdStr)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(map[string]string{
		"text": string(docDetail),
	})
}

// KnowledgeBasesDocParseStateHandler 文档解析状态
type KnowledgeBasesDocParseStateHandler struct {
	rest.BaseHandler
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesDocParseStateHandler() rest.Handler {
	return &KnowledgeBasesDocParseStateHandler{
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

func (k *KnowledgeBasesDocParseStateHandler) Get(ctx *rest.Context) (rest.Response, error) {
	docIdStr := ctx.QueryArgumentWithFallback("docId", "")

	if docIdStr == "" {
		return nil, errors.New("docId为空")
	}

	parseState, err := k.knowledgeBaseDocService.GetDocParseTaskState(ctx, docIdStr)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(map[string]int{
		"state": int(parseState),
	})
}

// KnowledgeBasesDocFindHandler 根据文件名找文件
type KnowledgeBasesDocFindHandler struct {
	rest.BaseHandler
	knowledgeBaseDocService knowledge_base.KnowledgeBaseDocService
}

func NewKnowledgeBasesDocFindHandler() rest.Handler {
	return &KnowledgeBasesDocFindHandler{
		knowledgeBaseDocService: knowledge_base.DefaultKnowledgebaseDocService,
	}
}

// Get 文件名查找知识库文档
func (k *KnowledgeBasesDocFindHandler) Get(ctx *rest.Context) (rest.Response, error) {
	query := ctx.QueryArgumentWithFallback("query", "")

	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	docs, err := k.knowledgeBaseDocService.FindByDocNameAndUserId(ctx, query, userId)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(docs)
}
