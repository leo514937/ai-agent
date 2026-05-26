package grpc

import (
	"context"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service2 "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/personal_knowledge_base"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal"
	"github.com/samber/lo"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

var RegisterAispBizServiceServer = func(registrar grpc.ServiceRegistrar) {
	proto.RegisterAispBizServiceServer(registrar, NewAispBizService())
}

type AispBizService struct {
	proto.UnimplementedAispBizServiceServer
	serviceName                  string
	documentParseService         service2.DocumentParseService
	personalKnowledgeBaseService service.PersonalKnowledgeBaseService
	internalKnowledgeBaseService service.InternalKnowledgeBaseService
	klaraModelService            klara_model.KlaraModelService
}

var _ proto.AispBizServiceServer = &AispBizService{}

func NewAispBizService() *AispBizService {
	return &AispBizService{
		serviceName:                  "AispBizService",
		documentParseService:         service2.DefaultDocumentParseService,
		personalKnowledgeBaseService: service.NewPersonalKnowledgeBaseServiceImpl(),
		internalKnowledgeBaseService: service.NewInternalKnowledgeBaseServiceImpl(),
		klaraModelService:            klara_model.NewKlaraModelServiceImpl(),
	}
}

func (s *AispBizService) UpsertKnowledgeBaseDocument(ctx context.Context, req *proto.UpsertKnowledgeBaseDocumentRequest) (*proto.UpsertKnowledgeBaseDocumentResponse, error) {
	methodName := "UpsertKnowledgeBaseDocument"
	logger := log.WithFields(ctx, map[string]interface{}{
		"service": s.serviceName,
		"s":       methodName,
		"request": req,
	})
	logger.Info(ctx, "do request")
	haloSpan := halo.NewHalo(ctx, fmt.Sprintf("%s_%s", "AISP", s.serviceName), methodName)
	nowTime := time.Now()
	defer func() {
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		// response 打点
		s.statsResponseWithAb(ctx, methodName, nowTime)
	}()

	var err error
	result := &proto.UpsertKnowledgeBaseDocumentResponse{}

	err = s.checkRequestDocParam(req)
	if err != nil {
		result.Status = macro.SERVICE_ILLEGAL_PARAM.Code()
		result.Message = err.Error()
		return result, nil
	}

	url := lo.Ternary(req.GetDocMeta().GetUrl() != "", req.GetDocMeta().GetUrl(), req.GetDocMeta().GetFileOssUrl())

	// 如果是新文档，生成文档 id
	docId := req.GetDocIdentity().GetDocId()
	if docId == 0 {
		docId, err = s.internalKnowledgeBaseService.GenDocId(ctx, url)
		if err != nil {
			result.Status = macro.SERVICE_CODE_DB_ERR.Code()
			result.Message = err.Error()
			return result, err
		}
	}

	docInfo := &model.DocumentInfo{
		DocId: docId,
		DocType: util.ContentType2DocType(lo.Ternary(req.GetDocIdentity().GetDocType() != proto.DocType_UNKNOWN_DOCTYPE,
			req.GetDocIdentity().GetDocType(), proto.DocType_INTERNAL_DOC)).String(),
		Title:           req.GetDocMeta().GetTitle(),
		Content:         req.GetDocMeta().GetContent(),
		Abstract:        req.GetDocMeta().GetAbstract(),
		LastUpdatedTime: req.GetDocMeta().GetLastUpdatedTime(),
		Url:             url,
		OssPath:         req.GetDocMeta().GetFileOssPath(),
		Tags:            strings.Join(req.GetDocMeta().GetTags(), ","),
		AuthorityLevel:  req.GetDocMeta().GetAuthorityLevel().String(),
		DocSource:       req.GetDocMeta().GetSource(),
		BizGroup:        req.GetBizGroup().String(),
		Operator:        req.GetOperator(),
	}
	docInfo.FillDocSubtype()

	// 如果是文件类型的文档，进行文件解析
	if req.GetDocMeta().GetFileOssPath() != "" || req.GetDocMeta().GetFileOssUrl() != "" {
		// 读文件
		fileBytes, err := s.documentParseService.ReadContentFromOss(ctx, req.GetDocMeta().GetFileOssUrl(), req.GetDocMeta().GetFileOssPath())
		if err != nil {
			result.Status = macro.SERVICE_FILE_PARSE_ERR.Code()
			result.Message = err.Error()
			return result, err
		}

		// 目前只支持 pdf、markdown、txt 三种类型的文件
		if docInfo.DocSubtype == "" {
			result.Status = macro.SERVICE_FILE_PARSE_ERR.Code()
			result.Message = "unsupported file type"
			return result, status.Errorf(codes.InvalidArgument, "unsupported file type")
		}

		// markdown、txt 直接读取内容正文
		if docInfo.DocSubtype == model.DocSubtypeMarkdown || docInfo.DocSubtype == model.DocSubtypeText {
			docInfo.Content = string(fileBytes)
		}

		// pdf 解析后，存储到 document_parsing_base 表
		if docInfo.DocSubtype == model.DocSubtypePdf {
			err := s.documentParseService.ParsePdfAndSave(ctx, fileBytes, docInfo.DocId, docInfo.DocType)
			if err != nil {
				result.Status = macro.SERVICE_FILE_PARSE_ERR.Code()
				result.Message = err.Error()
				return result, err
			}
		}
	}

	err = s.internalKnowledgeBaseService.UpsertDocumentInfo(ctx, docInfo)
	if err != nil {
		result.Status = macro.SERVICE_CODE_DB_ERR.Code()
		result.Message = err.Error()
		return result, err
	}

	result.DocIdentity = &proto.DocIdentity{
		DocId:   docInfo.DocId,
		DocType: util.DocType2ContentType(content.DocType_Type(content.DocType_Type_value[docInfo.DocType])),
	}
	result.Status = macro.SERVICE_CODE_SUCCESS.Code()
	result.Message = macro.SERVICE_CODE_SUCCESS.Message()
	return result, err
}

func (s *AispBizService) KbRecallSearch(ctx context.Context, req *proto.KbRecallSearchRequest) (*proto.KbRecallSearchResponse, error) {
	methodName := "KbRecallSearch"
	logger := log.WithFields(ctx, map[string]interface{}{
		"service": s.serviceName,
		"s":       methodName,
		"request": req,
	})
	logger.Info(ctx, "do request")
	haloSpan := halo.NewHalo(ctx, fmt.Sprintf("%s_%s", "AISP", s.serviceName), methodName)
	nowTime := time.Now()
	defer func() {
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		// response 打点
		s.statsResponseWithAb(ctx, methodName, nowTime)
	}()

	var resultItems []*proto.KbRecallSearchRelevantSource

	if req.GetRecallSearchType() == proto.KbRecallSearchType_RST_DOC {
		docs := s.personalKnowledgeBaseService.SearchPersonalKnowledgeDoc(ctx, req)
		for _, doc := range docs {
			resultItems = append(resultItems, &proto.KbRecallSearchRelevantSource{
				DocId:             doc.DocId,
				DocType:           util.DocType2ContentType(doc.DocType),
				KnowledgeBaseId:   doc.PersonalKnowledgeBaseId,
				KnowledgeBaseType: doc.PersonalKnowledgeBaseType,
				Title:             doc.Title,
				Content:           doc.Content,
				Abstract:          doc.Abstract,
			})
		}
	}
	if req.GetRecallSearchType() == proto.KbRecallSearchType_RST_FOLDER {
		bases := s.personalKnowledgeBaseService.SearchPersonalKnowledgeBase(ctx, req)
		for _, base := range bases {
			resultItems = append(resultItems, &proto.KbRecallSearchRelevantSource{
				MemberId:          base.MemberId,
				KnowledgeBaseId:   base.KnowledgeBaseId,
				KnowledgeBaseType: base.KnowledgeBaseType,
				Title:             base.KnowledgeBaseName,
				Description:       base.KnowledgeBaseDescription,
			})
		}
	}

	logger.Infof(ctx, "kb recall result: %s", util.GetJSONIgnoreError(resultItems))

	return &proto.KbRecallSearchResponse{
		RelevantSource: resultItems,
	}, nil
}

func (s *AispBizService) BuildPersonalKnowledgeBaseIndex(ctx context.Context, req *proto.BuildPersonalKnowledgeBaseIndexRequest) (*proto.UpsertCommonResponse, error) {
	methodName := "BuildPersonalKnowledgeBaseIndex"
	logger := log.WithFields(ctx, map[string]interface{}{
		"service": s.serviceName,
		"s":       methodName,
		"request": req,
	})
	logger.Info(ctx, "do request")
	haloSpan := halo.NewHalo(ctx, fmt.Sprintf("%s_%s", "AISP", s.serviceName), methodName)
	nowTime := time.Now()
	defer func() {
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		// response 打点
		s.statsResponseWithAb(ctx, methodName, nowTime)
	}()

	var err error
	result := &proto.UpsertCommonResponse{}

	err = s.checkRequestParam(req)
	if err != nil {
		result.Status = macro.SERVICE_ILLEGAL_PARAM.Code()
		result.Message = err.Error()
		return result, nil
	}

	// 新增个人知识库 doc
	if req.GetActionType() == proto.KbActionType_AT_INSERT && req.GetDocId() != 0 {
		err = s.personalKnowledgeBaseService.AddPersonalKnowledgeDoc(ctx, req)
	}
	// 新增个人知识库 base
	if req.GetActionType() == proto.KbActionType_AT_INSERT && req.GetDocId() == 0 {
		err = s.personalKnowledgeBaseService.UpsertPersonalKnowledgeBase(ctx, req)
	}
	// 删除个人知识库 doc
	if req.GetActionType() == proto.KbActionType_AT_DELETED && req.GetDocId() != 0 {
		err = s.personalKnowledgeBaseService.DelPersonalKnowledgeDoc(ctx, req)
	}
	// 删除个人知识库 base
	if req.GetActionType() == proto.KbActionType_AT_DELETED && req.GetDocId() == 0 {
		err = s.personalKnowledgeBaseService.DelPersonalKnowledgeBase(ctx, req)
	}
	// 个人知识库 base 更名、更描述、更可见性
	if req.GetActionType() == proto.KbActionType_AT_UPDATE {
		err = s.personalKnowledgeBaseService.UpsertPersonalKnowledgeBase(ctx, req)
	}

	if err != nil {
		result.Status = macro.SERVICE_CODE_DB_ERR.Code()
		result.Message = err.Error()
	} else {
		result.Status = macro.SERVICE_CODE_SUCCESS.Code()
		result.Message = macro.SERVICE_CODE_SUCCESS.Message()
	}

	return result, nil
}

func (s *AispBizService) checkRequestParam(req *proto.BuildPersonalKnowledgeBaseIndexRequest) error {
	if req.GetKnowledgeBaseId() == 0 || req.GetKnowledgeBaseType() == proto.PersonalKnowledgeBaseType_PKB_UNDEFINED {
		return status.Errorf(codes.InvalidArgument, "empty KnowledgeBaseId or KnowledgeBaseType")
	}
	if req.GetActionType() == proto.KbActionType_AT_UNDEFINED {
		return status.Errorf(codes.InvalidArgument, "empty ActionType")
	}
	if req.GetActionType() == proto.KbActionType_AT_UPDATE && req.GetDocId() != 0 {
		return status.Errorf(codes.InvalidArgument, "doc don't support update")
	}
	if req.GetActionType() == proto.KbActionType_AT_UPDATE && req.GetKnowledgeBaseName() == "" && req.GetKnowledgeBaseDescription() == "" {
		return status.Errorf(codes.InvalidArgument, "update method only support KnowledgeBaseName and KnowledgeBaseDescription")
	}
	if req.GetScene() == proto.KnowledgeBaseScene_INTERNAL_DOCUMENT && req.GetMemberId() != 0 {
		return status.Errorf(codes.InvalidArgument, "internal document don't support member id, member id should be 0")
	}
	return nil
}

func (s *AispBizService) checkRequestDocParam(req *proto.UpsertKnowledgeBaseDocumentRequest) error {
	if req.GetDocIdentity() != nil && req.GetDocIdentity().GetDocId() != 0 && req.GetDocIdentity().GetDocType() == proto.DocType_UNKNOWN_DOCTYPE {
		return status.Errorf(codes.InvalidArgument, "empty docType")
	}
	if req.GetDocMeta().GetTitle() == "" || (req.GetDocMeta().GetContent() == "" && req.GetDocMeta().GetAbstract() == "" && req.GetDocMeta().GetFileOssUrl() == "" && req.GetDocMeta().GetFileOssPath() == "") {
		return status.Errorf(codes.InvalidArgument, "empty title or content or oss")
	}
	return nil
}

func (s *AispBizService) statsResponseWithAb(ctx context.Context, api string, nowTime time.Time) {
	ctx = s.contextWithReq(ctx, api)
	// 记录耗时
	util.Timing(ctx, portal.BizResponseStatsByBizFmt, time.Since(nowTime), "api", api, "request_time")
	// 记录请求数
	util.Increment(ctx, portal.BizResponseStatsByBizFmt, "api", api, "count")
}

func (s *AispBizService) contextWithReq(ctx context.Context, api string) context.Context {
	ctx = log.ContextWithScene(ctx, fmt.Sprintf("%s.%s", api, "default"))
	return ctx
}
