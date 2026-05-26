package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/utils"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"github.com/cespare/xxhash/v2"
	"github.com/samber/lo"
)

type PersonalKnowledgeBaseService interface {
	// AddPersonalKnowledgeDoc 【doc】增加个人知识库文档
	AddPersonalKnowledgeDoc(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error
	// DelPersonalKnowledgeDoc 【doc】删除个人知识库文档
	DelPersonalKnowledgeDoc(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error
	// SearchPersonalKnowledgeDoc 【doc】检索个人知识库内容
	SearchPersonalKnowledgeDoc(ctx context.Context, params *proto.KbRecallSearchRequest) []*model.PersonalKnowledgeDoc

	// AddPersonalKnowledgeBase 【base】增加个人知识库
	UpsertPersonalKnowledgeBase(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error
	// DelPersonalKnowledgeBase 【base】删除个人知识库
	DelPersonalKnowledgeBase(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error
	// SearchPersonalKnowledgeBase 【base】检索个人知识库名称
	SearchPersonalKnowledgeBase(ctx context.Context, params *proto.KbRecallSearchRequest) []*model.CommonKnowledgeBase
	// GetRelateQueryAndSave 只获得相关词 不更新rum
	GetRelateQueryAndSave(ctx context.Context, input *model.PersonalKnowledgeDoc, maxLength int) []string
}

const m3EmbeddingDim = 1024

type PersonalKnowledgeBaseServiceImpl struct {
	documentParseService service.DocumentParseService
	redisDao             dao.DocRelateQueryDao
	knowledgebaseDao     dao.KnowledgeBaseV2Dao
	contentCoreRpc       rpc.ContentCoreRPC
	ruceneRpc            rpc.RuceneServiceRPC
	rumClient            rpc.RumClient[float32]
	segmentRpc           rpc.SegmentRPC
	klaraModelService    klara_model.KlaraModelService
	klaraEmbeddingClient rpc.KlaraRpcClient
	defaultMaxLength     int
}

func NewPersonalKnowledgeBaseServiceImpl() PersonalKnowledgeBaseService {
	return &PersonalKnowledgeBaseServiceImpl{
		documentParseService: service.DefaultDocumentParseService,
		redisDao:             daoImpl.DefaultDocRelateQueryDaoImpl,
		knowledgebaseDao:     daoImpl.DefaultKnowledgeBaseV2DaoImpl,
		contentCoreRpc:       rpcImpl.DefaultContentCoreRPCImpl,
		ruceneRpc:            rpc.DefaultRuceneServiceRPC,
		rumClient:            rpcImpl.DefaultFloat32RumClientImpl,
		segmentRpc:           rpcImpl.DefaultSegmentImpl,
		klaraModelService:    klara_model.NewKlaraModelServiceImpl(),
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("bge-m3-common-for-zhida"),
		defaultMaxLength:     10000,
	}
}

func (p *PersonalKnowledgeBaseServiceImpl) AddPersonalKnowledgeDoc(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error {
	logger := log.WithField(ctx, "AddPersonalKnowledgeDoc", params)

	docType := util.ContentType2DocType(params.GetDocType())
	title, abstract, text, tags := p.getDocMeta(ctx, params.GetDocId(), docType)

	// 正文为空，用摘要做降级
	if text == "" {
		text = abstract
	}

	if title == "" || text == "" {
		logger.Errorf(ctx, "empty doc meta. title:%s, text:%s", title, text)
		errDesc := "empty doc meta : title"
		if text == "" {
			errDesc = "empty doc meta : content"
		}
		return errors.New(errDesc)
	}

	personalKnowledgeDoc := &model.PersonalKnowledgeDoc{
		Id:                        getIndexId(params.GetMemberId(), params.GetDocId(), docType, params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType()),
		MemberId:                  params.GetMemberId(),
		DocId:                     params.GetDocId(),
		DocType:                   docType,
		PersonalKnowledgeBaseId:   params.GetKnowledgeBaseId(),
		PersonalKnowledgeBaseType: params.GetKnowledgeBaseType(),
		Visibility:                params.GetVisibility(),
		Title:                     title,
		Content:                   text,
		Abstract:                  abstract,
		Tags:                      lo.Ternary(tags == nil, []string{}, tags),
		Scene:                     params.GetScene(),
	}

	ruceneErr := p.syncRuceneDoc(ctx, personalKnowledgeDoc)
	var rumTitleErr, rumQueryErr, rumDocContentErr error

	// 直答使用 rum 表： content索引
	if params.GetScene() == proto.KnowledgeBaseScene_PERSONAL_ZHIDA {
		rumDocContentErr = p.syncRumContentIndex(ctx, personalKnowledgeDoc)
	}

	// 内部使用 rum 表： title+query索引
	if params.GetScene() == proto.KnowledgeBaseScene_INTERNAL_DOCUMENT {
		rumTitleErr = p.syncRumDocIndex(ctx, personalKnowledgeDoc)
		rumQueryErr = p.syncRumRelateQueryIndex(ctx, personalKnowledgeDoc)
	}

	if ruceneErr != nil || rumTitleErr != nil || rumQueryErr != nil || rumDocContentErr != nil {
		logger.Errorf(ctx, "sync rucene or rumDoc or rumQuery failed. ruceneErr:%v, rumDocErr:%v, rumQueryErr:%v, rumDocContentErr:%v", ruceneErr, rumTitleErr, rumQueryErr, rumDocContentErr)
		return errors.New("sync rucene or rumDoc failed")
	}
	// 存入 tidb 正排记录
	insertRecordErr := p.knowledgebaseDao.AddKnowledgeBaseDocument(ctx, &model.KnowledgeBaseDocV2{
		KnowledgeBaseId:   params.GetKnowledgeBaseId(),
		KnowledgeBaseType: params.GetKnowledgeBaseType(),
		DocId:             params.GetDocId(),
		DocType:           docType.String(),
		Operator:          util.Int64String(params.GetMemberId()),
		Visibility:        params.GetVisibility(),
	})

	if insertRecordErr != nil {
		logger.Errorf(ctx, "add knowledge base doc record failed. err:%v", insertRecordErr)
	}
	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) DelPersonalKnowledgeDoc(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error {
	logger := log.WithField(ctx, "DelPersonalKnowledgeDoc", params)

	docType := util.ContentType2DocType(params.GetDocType())
	indexId := getIndexId(params.GetMemberId(), params.GetDocId(), docType, params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType())

	ruceneErr := p.delRuceneDoc(ctx, util.Int64String(indexId), params.GetScene())

	var rumTitleErr, rumQueryErr, rumContentErr error
	if params.GetScene() == proto.KnowledgeBaseScene_PERSONAL_ZHIDA {
		rumContentErr = p.delRumContent(ctx, indexId)
	}

	if params.GetScene() == proto.KnowledgeBaseScene_INTERNAL_DOCUMENT {
		rumTitleErr = p.delRumTitle(ctx, indexId)
		rumQueryErr = p.delRumQuery(ctx, indexId)
	}

	if ruceneErr != nil || rumTitleErr != nil || rumQueryErr != nil || rumContentErr != nil {
		logger.Errorf(ctx, "del rucene or rumDoc or rumQuery failed. ruceneErr:%v, rumTitleErr:%v, rumQueryErr:%v, rumContentErr:%v", ruceneErr, rumTitleErr, rumQueryErr, rumContentErr)
		return errors.New("del rucene or rumDoc failed")
	}
	delRecordErr := p.knowledgebaseDao.DeleteKnowledgeBaseDocument(ctx, &model.KnowledgeBaseDocV2{
		KnowledgeBaseId:   params.GetKnowledgeBaseId(),
		KnowledgeBaseType: params.GetKnowledgeBaseType(),
		DocId:             params.GetDocId(),
		DocType:           docType.String(),
	})
	if delRecordErr != nil {
		logger.Errorf(ctx, "del knowledge base doc record failed. err:%v", delRecordErr)
	}
	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) SearchPersonalKnowledgeDoc(ctx context.Context, params *proto.KbRecallSearchRequest) []*model.PersonalKnowledgeDoc {
	logger := log.WithField(ctx, "SearchPersonalKnowledgeDoc", params)

	condition := p.getSearchDocCondition(ctx, params)
	if len(condition.Musts) == 0 {
		logger.Errorf(ctx, "empty condition")
		return []*model.PersonalKnowledgeDoc{}
	}

	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, model.PersonalKnowledgeDocPath, model.PersonalKnowledgeDocIndex, macro.PersonalKnowledgeBaseDocStoreFields)
	result, err := p.searchRuceneDoc(ctx, ruceneQueryRequest, utils.MaxInt64(params.GetLimit(), 1))

	if err != nil {
		logger.Errorf(ctx, "search rucene failed. err:%v", err)
		return []*model.PersonalKnowledgeDoc{}
	}

	return result
}

func (p *PersonalKnowledgeBaseServiceImpl) searchRuceneDoc(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest, limit int64) ([]*model.PersonalKnowledgeDoc, error) {
	var result = make([]*model.PersonalKnowledgeDoc, 0)
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               int(limit),
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        macro.PersonalKnowledgeBaseDocStoreFields,
		TransportTimeoutMs: 8000,
		EarlyTerminate:     1000000,
		Highlight: []*client.HighlightField{{
			Field:             macro.PersonalKnowledgeBaseTitleFieldName,
			FragmentSize:      100,
			NumberOfFragments: 1,
		}, {
			Field:             macro.PersonalKnowledgeBaseAbstractFieldName,
			FragmentSize:      100,
			NumberOfFragments: 1,
		}, {
			Field:             macro.PersonalKnowledgeBaseContentFieldName,
			FragmentSize:      100,
			NumberOfFragments: 1,
		}},
	}

	resp, err := p.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), ruceneQueryRequest.RucenePath, ruceneQueryRequest.Index, queryRequest)
	if err != nil || resp == nil {
		return result, err
	}

	for _, item := range resp.Hits {
		var title string
		titleHighlights := item.Highlights[macro.PersonalKnowledgeBaseTitleFieldName]
		if len(titleHighlights) > 0 {
			title = titleHighlights[0]
		}

		var abstract string
		abstractHighlights := item.Highlights[macro.PersonalKnowledgeBaseAbstractFieldName]
		if len(abstractHighlights) > 0 {
			abstract = abstractHighlights[0]
		}

		var contents string
		contentHighlights := item.Highlights[macro.PersonalKnowledgeBaseContentFieldName]
		if len(contentHighlights) > 0 {
			contents = contentHighlights[0]
		}

		if !strings.Contains(title, "<em>") && !strings.Contains(abstract, "<em>") && !strings.Contains(contents, "<em>") {
			log.Errorf(ctx, "searchRuceneDoc: no highlight, item:%s", util.GetJSONIgnoreError(item))
			continue
		}

		result = append(result, &model.PersonalKnowledgeDoc{
			MemberId:                  item.StoreFields.GetInt64(macro.PersonalKnowledgeBaseMemberIdFieldName),
			DocId:                     item.StoreFields.GetInt64(macro.PersonalKnowledgeBaseDocIdFieldName),
			DocType:                   content.DocType_Type(content.DocType_Type_value[item.StoreFields.GetString(macro.PersonalKnowledgeBaseDocTypeFieldName)]),
			PersonalKnowledgeBaseId:   item.StoreFields.GetInt64(macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName),
			PersonalKnowledgeBaseType: proto.PersonalKnowledgeBaseType(proto.PersonalKnowledgeBaseType_value[item.StoreFields.GetString(macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName)]),
			Title:                     title,
			Abstract:                  abstract,
			Content:                   contents,
		})
	}

	return result, nil
}

func (p *PersonalKnowledgeBaseServiceImpl) searchRuceneBase(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest, limit int64) ([]*model.CommonKnowledgeBase, error) {
	var result = make([]*model.CommonKnowledgeBase, 0)
	queryRequest := &client.SearchQueryRequest{
		From:        0,
		Size:        int(limit),
		QueryDef:    ruceneQueryRequest.QueryDef,
		StoreFields: ruceneQueryRequest.QueryFields,
		Highlight: []*client.HighlightField{{
			Field:             macro.PersonalKnowledgeBaseKnowledgeBaseNameFieldName,
			FragmentSize:      100,
			NumberOfFragments: 1,
		}, {
			Field:             macro.PersonalKnowledgeBaseKnowledgeBaseDescriptionFieldName,
			FragmentSize:      100,
			NumberOfFragments: 1,
		}},
	}

	resp, err := p.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), ruceneQueryRequest.RucenePath, ruceneQueryRequest.Index, queryRequest)
	if err != nil || resp == nil {
		return result, err
	}

	for _, item := range resp.Hits {
		var knowledgeBaseName, knowledgeBaseDescription string
		kbNameHighlights := item.Highlights[macro.PersonalKnowledgeBaseKnowledgeBaseNameFieldName]
		kbDescriptionHighlights := item.Highlights[macro.PersonalKnowledgeBaseKnowledgeBaseDescriptionFieldName]
		if len(kbNameHighlights) > 0 {
			knowledgeBaseName = kbNameHighlights[0]
		}
		if len(kbDescriptionHighlights) > 0 {
			knowledgeBaseDescription = kbDescriptionHighlights[0]
		}

		result = append(result, &model.CommonKnowledgeBase{
			MemberId:                 item.StoreFields.GetInt64(macro.PersonalKnowledgeBaseMemberIdFieldName),
			KnowledgeBaseId:          item.StoreFields.GetInt64(macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName),
			KnowledgeBaseType:        proto.PersonalKnowledgeBaseType(proto.PersonalKnowledgeBaseType_value[item.StoreFields.GetString(macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName)]),
			KnowledgeBaseName:        knowledgeBaseName,
			KnowledgeBaseDescription: knowledgeBaseDescription,
		})
	}

	return result, nil
}

func (p *PersonalKnowledgeBaseServiceImpl) searchRuceneBaseAllDocIndex(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest) ([]int64, error) {
	var result = make([]int64, 0)
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               100000, // 最多返回10w条
		QueryDef:           ruceneQueryRequest.QueryDef,
		TransportTimeoutMs: 8000,
		EarlyTerminate:     1000000,
	}

	resp, err := p.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), ruceneQueryRequest.RucenePath, ruceneQueryRequest.Index, queryRequest)
	if err != nil || resp == nil {
		return result, err
	}

	for _, item := range resp.Hits {
		id, err := item.GetInt64Id()
		if err == nil {
			result = append(result, id)
		}
	}

	return result, nil
}

func (p *PersonalKnowledgeBaseServiceImpl) UpsertPersonalKnowledgeBase(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error {
	logger := log.WithField(ctx, "UpsertPersonalKnowledgeBase", params)

	indexId := getIndexId(params.GetMemberId(), 0, content.DocType_Unknown, params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType())
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)

	var ruceneErr error
	if params.GetVisibility() == proto.KnowledgeBaseVisibility_UNDEFINED_VISIBILITY || params.GetVisibility() == proto.KnowledgeBaseVisibility_PRIVATE {
		// 删掉公开索引，写入私密索引
		p.ruceneRpc.Delete(ctx, ruceneHost, model.PublicKnowledgeBasePath, model.PublicKnowledgeBaseIndex, &model.PublicKnowledgeBaseRucene{Id: util.Int64String(indexId)}, util.Int64String(indexId))
		personalKnowledgeBase := &model.PersonalKnowledgeBase{
			Id:                        indexId,
			MemberId:                  params.GetMemberId(),
			PersonalKnowledgeBaseId:   params.GetKnowledgeBaseId(),
			PersonalKnowledgeBaseType: params.GetKnowledgeBaseType(),
			PersonalKnowledgeBaseName: params.GetKnowledgeBaseName(),
		}
		ruceneErr = p.syncRuceneBasePersonal(ctx, personalKnowledgeBase)
	} else {
		// 删掉私密索引，写入公开索引
		p.ruceneRpc.Delete(ctx, ruceneHost, model.PersonalKnowledgeBasePath, model.PersonalKnowledgeBaseIndex, &model.PublicKnowledgeBaseRucene{Id: util.Int64String(indexId)}, util.Int64String(indexId))
		publicKnowledgeBase := &model.CommonKnowledgeBase{
			Id:                       indexId,
			MemberId:                 params.GetMemberId(),
			KnowledgeBaseId:          params.GetKnowledgeBaseId(),
			KnowledgeBaseType:        params.GetKnowledgeBaseType(),
			KnowledgeBaseName:        params.GetKnowledgeBaseName(),
			KnowledgeBaseDescription: params.GetKnowledgeBaseDescription(),
			KnowledgeBaseVisibility:  params.GetVisibility().String(),
		}
		ruceneErr = p.syncRuceneBasePublic(ctx, publicKnowledgeBase)
	}

	if ruceneErr != nil {
		logger.Errorf(ctx, "sync rucene failed. ruceneErr:%v", ruceneErr)
		return errors.New("sync rucene failed")
	}

	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) DelPersonalKnowledgeBase(ctx context.Context, params *proto.BuildPersonalKnowledgeBaseIndexRequest) error {
	logger := log.WithField(ctx, "DelPersonalKnowledgeBase", params)

	indexId := getIndexId(params.GetMemberId(), 0, content.DocType_Unknown, params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType())

	// 删除知识库
	ruceneBaseErr := p.delRuceneBase(ctx, util.Int64String(indexId), params.GetVisibility())
	// 删除知识库下的所有文档，包含一个 rucene 索引和两个 rum 索引
	docIndexes := p.getPersonalKnowledgeBaseAllDoc(ctx, params.GetMemberId(), params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType(), params.GetScene())
	ruceneDocErr := p.delRuceneBaseAllDoc(ctx, params.GetMemberId(), params.GetKnowledgeBaseId(), params.GetKnowledgeBaseType(), params.GetScene())
	var rumTitleErr, rumQueryErr, rumContentErr error
	for _, docIndex := range docIndexes {
		if params.GetScene() == proto.KnowledgeBaseScene_PERSONAL_ZHIDA {
			rumContentErr = p.delRumContent(ctx, docIndex)
		}

		if params.GetScene() == proto.KnowledgeBaseScene_INTERNAL_DOCUMENT {
			rumTitleErr = p.delRumTitle(ctx, docIndex)
			rumQueryErr = p.delRumQuery(ctx, docIndex)
		}
		if rumTitleErr != nil || rumQueryErr != nil || rumContentErr != nil {
			break
		}
	}

	if ruceneBaseErr != nil || ruceneDocErr != nil || rumTitleErr != nil || rumQueryErr != nil || rumContentErr != nil {
		logger.Errorf(ctx, "del rucene or rumDoc or rumQuery failed. ruceneBaseErr:%v, rumTitleErr:%v, rumDocErr:%v, rumQueryErr:%v, rumContentErr:%v", ruceneBaseErr, ruceneDocErr, rumTitleErr, rumQueryErr, rumContentErr)
		return errors.New("del rucene or rumDoc failed")
	}
	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) getPersonalKnowledgeBaseAllDoc(ctx context.Context, memberId int64, knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType, scene proto.KnowledgeBaseScene) []int64 {
	condition := p.getBaseAllDocCondition(memberId, knowledgeBaseId, knowledgeBaseType)
	rucenePath, ruceneIndex := getRuceneDocPathAndIndex(scene)
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, rucenePath, ruceneIndex, []string{})
	result, err := p.searchRuceneBaseAllDocIndex(ctx, ruceneQueryRequest)
	if err != nil {
		log.Errorf(ctx, "getPersonalKnowledgeBaseAllDoc failed. err:%v", err)
		return []int64{}
	}
	return result
}

func (p *PersonalKnowledgeBaseServiceImpl) SearchPersonalKnowledgeBase(ctx context.Context, params *proto.KbRecallSearchRequest) []*model.CommonKnowledgeBase {
	logger := log.WithField(ctx, "SearchPersonalKnowledgeBase", params)

	condition := p.getSearchBaseCondition(ctx, params)
	if len(condition.Musts) == 0 {
		logger.Errorf(ctx, "empty condition")
		return []*model.CommonKnowledgeBase{}
	}

	var path, index, fields = model.PersonalKnowledgeBasePath, model.PersonalKnowledgeBaseIndex, macro.PersonalKnowledgeBaseStoreFields
	if params.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_FEATURE || params.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_ONLY {
		path, index, fields = model.PublicKnowledgeBasePath, model.PublicKnowledgeBaseIndex, macro.PublicKnowledgeBaseStoreFields
	}
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, path, index, fields)
	result, err := p.searchRuceneBase(ctx, ruceneQueryRequest, utils.MaxInt64(params.GetLimit(), 1))

	if err != nil {
		logger.Errorf(ctx, "search rucene failed. err:%v", err)
		return []*model.CommonKnowledgeBase{}
	}

	return result
}

func (p *PersonalKnowledgeBaseServiceImpl) getContentCoreDocMeta(ctx context.Context, docId int64, docType content.DocType_Type) (title string, abstract string, text string) {
	doc := model.NewContentWithDocType(docId, docType)
	response := p.contentCoreRpc.BatchGetContent(ctx, []model.Content{doc},
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)

	contentInfo := response[doc]
	if contentInfo == nil {
		return
	}

	title = contentInfo.GetTitle()
	abstract = contentInfo.GetSummary()

	var summary string
	if docType == content.DocType_Paper { // 维普 arxiv 的 pdf
		_, text = p.documentParseService.PaperParse(ctx, contentInfo)
	} else if docType == content.DocType_ZhiDaUserUpload { // 用户上传
		_, text, summary = p.documentParseService.UserUploadParse(ctx, contentInfo)
	} else if docType == content.DocType_Webpage { // rss 流
		_, text = p.documentParseService.RssParse(ctx, contentInfo)
	} else if contentInfo.GetContentBody() != nil { // 其他类型
		body := contentInfo.GetContentBody().GetBody()
		text, _ = util.ContentHtml2Markdown(ctx, body)
	}

	// 如果内层解析出来了 summary，但是外层没有，则使用内层的 summary
	if abstract == "" && summary != "" {
		abstract = summary
	}

	// 如果 title 为空，则尝试从 parentInfo 中获取
	parentContentInfo := p.getParentDocMeta(ctx, contentInfo)
	if parentContentInfo != nil && parentContentInfo.GetTitle() != "" && title == "" {
		title = parentContentInfo.GetTitle()
	}

	// 如果 title 仍然为空，且为图片类型，则使用 abstract 作为 title
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil &&
		contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() == "image" && title == "" && abstract != "" {
		title = abstract
	}

	return
}

func (p *PersonalKnowledgeBaseServiceImpl) getInternalDocMeta(ctx context.Context, docId int64, docType content.DocType_Type) (title string, abstract string, text string, tags []string) {
	docInfo := p.knowledgebaseDao.GetDocumentInfo(ctx, docId, docType)
	if docInfo != nil {
		title = docInfo.Title
		abstract = docInfo.Abstract
		text = docInfo.Content
		tags = strings.Split(docInfo.Tags, ",")
	}
	return
}

func (p *PersonalKnowledgeBaseServiceImpl) getDocMeta(ctx context.Context, docId int64, docType content.DocType_Type) (title string, abstract string, text string, tags []string) {
	if docType == content.DocType_InternalDoc || docType == content.DocType_AispUserUpload {
		title, abstract, text, tags = p.getInternalDocMeta(ctx, docId, docType)
	} else {
		title, abstract, text = p.getContentCoreDocMeta(ctx, docId, docType)
	}
	return
}

func (p *PersonalKnowledgeBaseServiceImpl) getParentDocMeta(ctx context.Context, contentInfo *base.ContentInfo) *base.ContentInfo {
	if contentInfo.GetExtInfo() == nil || contentInfo.GetExtInfo().GetParentInfo() == nil ||
		contentInfo.GetExtInfo().GetParentInfo().ContentID == "" {
		return nil
	}

	contentId := contentInfo.GetExtInfo().GetParentInfo().ContentID
	contentResultMap := p.contentCoreRpc.BatchGetContentByContentID(ctx, []string{contentId}, base.ContentInfoFieldContentTitle)

	return contentResultMap[contentId]
}

func getIndexId(memberId int64, docId int64, docType content.DocType_Type, knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType) int64 {
	return int64(xxhash.Sum64String(fmt.Sprintf("%d_%d_%d_%d_%d", memberId, docId, docType, knowledgeBaseId, knowledgeBaseType)))
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRuceneDoc(ctx context.Context, input *model.PersonalKnowledgeDoc) error {
	input.Title = p.segmentRpc.Clean(ctx, input.Title)
	input.Abstract = p.segmentRpc.Clean(ctx, input.Abstract)
	input.Content = p.segmentRpc.Clean(ctx, input.Content)
	ruceneDoc := &model.PersonalKnowledgeDocRucene{
		Id:                util.Int64String(input.Id),
		MemberId:          input.MemberId,
		DocId:             input.DocId,
		DocType:           input.DocType.String(),
		KnowledgeBaseId:   input.PersonalKnowledgeBaseId,
		KnowledgeBaseType: input.PersonalKnowledgeBaseType.String(),
		Visibility:        input.Visibility.String(),
		Tags:              input.Tags,
		Content: model.SegmentInfo{
			Words: p.getSegment(ctx, input.Content),
			Raw:   input.Content,
			Store: true,
		},
		Title: model.SegmentInfo{
			Words: p.getSegment(ctx, input.Title),
			Raw:   input.Title,
			Store: true,
		},
		Abstract: model.SegmentInfo{
			Words: p.getSegment(ctx, input.Abstract),
			Raw:   input.Abstract,
			Store: true,
		},
	}

	rucenePath, ruceneIndex := getRuceneDocPathAndIndex(input.Scene)
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, rucenePath, ruceneIndex, ruceneDoc, ruceneDoc.Id)
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRuceneBasePersonal(ctx context.Context, input *model.PersonalKnowledgeBase) error {
	input.PersonalKnowledgeBaseName = p.segmentRpc.Clean(ctx, input.PersonalKnowledgeBaseName)
	ruceneBase := &model.PersonalKnowledgeBaseRucene{
		Id:                util.Int64String(input.Id),
		MemberId:          input.MemberId,
		KnowledgeBaseId:   input.PersonalKnowledgeBaseId,
		KnowledgeBaseType: input.PersonalKnowledgeBaseType.String(),
		KnowledgeBaseName: model.SegmentInfo{
			Words: p.getSegment(ctx, input.PersonalKnowledgeBaseName),
			Raw:   input.PersonalKnowledgeBaseName,
			Store: true,
		},
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, model.PersonalKnowledgeBasePath, model.PersonalKnowledgeBaseIndex, ruceneBase, ruceneBase.Id)
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRuceneBasePublic(ctx context.Context, input *model.CommonKnowledgeBase) error {
	input.KnowledgeBaseName = p.segmentRpc.Clean(ctx, input.KnowledgeBaseName)
	input.KnowledgeBaseDescription = p.segmentRpc.Clean(ctx, input.KnowledgeBaseDescription)
	ruceneBase := &model.PublicKnowledgeBaseRucene{
		Id:                util.Int64String(input.Id),
		MemberId:          input.MemberId,
		KnowledgeBaseId:   input.KnowledgeBaseId,
		KnowledgeBaseType: input.KnowledgeBaseType.String(),
		KnowledgeBaseName: model.SegmentInfo{
			Words: p.getSegment(ctx, input.KnowledgeBaseName),
			Raw:   input.KnowledgeBaseName,
			Store: true,
		},
		KnowledgeBaseDesc: model.SegmentInfo{
			Words: p.getSegment(ctx, input.KnowledgeBaseDescription),
			Raw:   input.KnowledgeBaseDescription,
			Store: true,
		},
		KnowledgeBaseVisibility: input.KnowledgeBaseVisibility,
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, model.PublicKnowledgeBasePath, model.PublicKnowledgeBaseIndex, ruceneBase, ruceneBase.Id)
}

func (p *PersonalKnowledgeBaseServiceImpl) getSegment(ctx context.Context, text string) []*model.Word {
	var result []*model.Word

	response := p.segmentRpc.Segment(ctx, text, "Common", true, true, true)
	if response == nil {
		return result
	}

	for _, item := range response.Words {
		if item.GrainType == 1 {
			result = append(result, &model.Word{
				Value:  item.Word,
				Begin:  item.PositionBegin,
				Length: item.Length,
			})
		}
	}

	return result
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRumDocIndex(ctx context.Context, input *model.PersonalKnowledgeDoc) error {
	embeddings := p.klaraEmbeddingClient.BatchInferBgeM3DenseEmb(ctx, []string{input.Title})
	if len(embeddings) != 1 || len(embeddings[0]) != m3EmbeddingDim {
		log.Errorf(ctx, "get doc embedding failed, input:%s", input.Title)
		return errors.New("get doc embedding failed")
	}

	rumTableName := macro.InternalKnowledgeBaseTitleRumTable

	resp := p.rumClient.RumUpsert(ctx, rumTableName, input.Id, embeddings[0], "", map[string]interface{}{
		macro.PersonalKnowledgeBaseMemberIdFieldName:          input.MemberId,
		macro.PersonalKnowledgeBaseDocIdFieldName:             util.Int64String(input.DocId),
		macro.PersonalKnowledgeBaseDocTypeFieldName:           input.DocType.String(),
		macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName:   input.PersonalKnowledgeBaseId,
		macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName: input.PersonalKnowledgeBaseType.String(),
		macro.PersonalKnowledgeBaseExtraRumFieldName:          strings.Join(append(input.Tags, input.Visibility.String()), ","),
		macro.PersonalKnowledgeRawFieldName:                   input.Title,
	})

	if resp == false {
		return errors.New("upsert rucene failed")
	}

	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRumContentIndex(ctx context.Context, input *model.PersonalKnowledgeDoc) error {
	// 模型输入长度最多支持 8k，超出部分模型内部截断，不报错。由于存在英文论文，本次截断长度设置为 80k，打满压测：93ms
	embContent := fmt.Sprintf("%s\n%s", input.Title, util.UnicodeSubstr(input.Content, 0, 80000))
	embeddings := p.klaraEmbeddingClient.BatchInferBgeM3DenseEmb(ctx, []string{embContent})
	if len(embeddings) != 1 || len(embeddings[0]) != m3EmbeddingDim {
		log.Errorf(ctx, "get doc embedding failed, input:%s", input.Title)
		return errors.New("get doc embedding failed")
	}

	rumTableName := macro.PersonalKnowledgeBaseContentRumTable

	resp := p.rumClient.RumUpsert(ctx, rumTableName, input.Id, embeddings[0], "", map[string]interface{}{
		macro.PersonalKnowledgeBaseMemberIdFieldName:          input.MemberId,
		macro.PersonalKnowledgeBaseDocIdFieldName:             util.Int64String(input.DocId),
		macro.PersonalKnowledgeBaseDocTypeFieldName:           input.DocType.String(),
		macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName:   input.PersonalKnowledgeBaseId,
		macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName: input.PersonalKnowledgeBaseType.String(),
		macro.PersonalKnowledgeBaseExtraRumFieldName:          strings.Join(append(input.Tags, input.Visibility.String()), ","),
		macro.PersonalKnowledgeRawFieldName:                   input.Title,
	})

	if resp == false {
		return errors.New("upsert rucene failed")
	}

	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) GetRelateQueryAndSave(ctx context.Context, input *model.PersonalKnowledgeDoc, maxLength int) []string {
	if input.Content == "" && input.Abstract != "" {
		input.Content = input.Abstract
	}
	relateQueries := p.klaraModelService.GenKnowledgeBaseRelateQuery(ctx, input.Content, maxLength)
	if len(relateQueries) != 0 {
		p.redisDao.SetDocRelateQueries(ctx, input.DocId, input.DocType, relateQueries)
	}
	return relateQueries
}

func (p *PersonalKnowledgeBaseServiceImpl) syncRumRelateQueryIndex(ctx context.Context, input *model.PersonalKnowledgeDoc) error {
	relateQueries := p.GetRelateQueryAndSave(ctx, input, p.defaultMaxLength)
	var indexs []int64

	rumTableName := macro.InternalKnowledgeBaseQuestionRumTable

	// 写入 rum 索引
	for _, query := range relateQueries {
		embeddings := p.klaraEmbeddingClient.BatchInferBgeM3DenseEmb(ctx, []string{query})
		if len(embeddings) != 1 || len(embeddings[0]) != m3EmbeddingDim {
			log.Errorf(ctx, "get query embedding failed, input:%s", query)
			return errors.New("get query embedding failed")
		}

		indexId := int64(xxhash.Sum64String(fmt.Sprintf("%d_%d_%d_%d_%d_%s", input.MemberId, input.DocId, input.DocType, input.PersonalKnowledgeBaseId, input.PersonalKnowledgeBaseType, query)))
		resp := p.rumClient.RumUpsert(ctx, rumTableName, indexId, embeddings[0], "", map[string]interface{}{
			macro.PersonalKnowledgeBaseMemberIdFieldName:          input.MemberId,
			macro.PersonalKnowledgeBaseDocIdFieldName:             input.DocId,
			macro.PersonalKnowledgeBaseDocTypeFieldName:           input.DocType.String(),
			macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName:   input.PersonalKnowledgeBaseId,
			macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName: input.PersonalKnowledgeBaseType.String(),
			macro.PersonalKnowledgeBaseExtraRumFieldName:          strings.Join(append(input.Tags, input.Visibility.String()), ","),
			macro.PersonalKnowledgeRawFieldName:                   query,
		})

		if resp == false {
			return errors.New("upsert rum failed")
		}
		indexs = append(indexs, indexId)
	}

	// 存储 doc 索引 id 和 query 索引 ids 的映射关系
	p.redisDao.SetDocIndex2QueriesIndex(ctx, input.Id, indexs)

	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) delRuceneDoc(ctx context.Context, id string, scene proto.KnowledgeBaseScene) error {
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	rucenePath, ruceneIndex := getRuceneDocPathAndIndex(scene)
	return p.ruceneRpc.Delete(ctx, ruceneHost, rucenePath, ruceneIndex, &model.PersonalKnowledgeDocRucene{Id: id}, id)
}

func (p *PersonalKnowledgeBaseServiceImpl) delRuceneBaseAllDoc(ctx context.Context, memberId int64, baseId int64, baseType proto.PersonalKnowledgeBaseType, scene proto.KnowledgeBaseScene) error {
	condition := p.getBaseAllDocCondition(memberId, baseId, baseType)
	rucenePath, ruceneIndex := getRuceneDocPathAndIndex(scene)
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, rucenePath, ruceneIndex, macro.PersonalKnowledgeBaseDocStoreFields)
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return p.ruceneRpc.RemoveDocWithQuery(ctx, ruceneHost, rucenePath, ruceneIndex, ruceneQueryRequest.QueryDef)
}

func (p *PersonalKnowledgeBaseServiceImpl) delRuceneBase(ctx context.Context, id string, visibility proto.KnowledgeBaseVisibility) error {
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	if visibility == proto.KnowledgeBaseVisibility_PUBLIC_FEATURE || visibility == proto.KnowledgeBaseVisibility_PUBLIC_ONLY {
		return p.ruceneRpc.Delete(ctx, ruceneHost, model.PublicKnowledgeBasePath, model.PublicKnowledgeBaseIndex, &model.PublicKnowledgeBaseRucene{Id: id}, id)
	}
	return p.ruceneRpc.Delete(ctx, ruceneHost, model.PersonalKnowledgeBasePath, model.PersonalKnowledgeBaseIndex, &model.PersonalKnowledgeBaseRucene{Id: id}, id)
}

func (p *PersonalKnowledgeBaseServiceImpl) delRumTitle(ctx context.Context, id int64) error {
	rumTableName := macro.InternalKnowledgeBaseTitleRumTable
	isSucc := p.rumClient.RumDelete(ctx, rumTableName, id, "")
	if !isSucc {
		log.Errorf(ctx, "personal knowledge base title delete failed. id:%d", id)
		return errors.New("rum delete failed")
	}
	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) delRumQuery(ctx context.Context, id int64) error {
	queriesIndexIds := p.redisDao.GetDocIndex2QueriesIndex(ctx, id)
	rumTableName := macro.InternalKnowledgeBaseQuestionRumTable

	for _, queriesIndexId := range queriesIndexIds {
		isSucc := p.rumClient.RumDelete(ctx, rumTableName, queriesIndexId, "")
		if !isSucc {
			log.Errorf(ctx, "personal knowledge base query delete failed. id:%d", queriesIndexId)
			return errors.New("rum delete failed")
		}
	}

	return nil
}

func (p *PersonalKnowledgeBaseServiceImpl) delRumContent(ctx context.Context, id int64) error {
	rumTableName := macro.PersonalKnowledgeBaseContentRumTable
	isSucc := p.rumClient.RumDelete(ctx, rumTableName, id, "")
	if !isSucc {
		log.Errorf(ctx, "personal knowledge base content delete failed. id:%d", id)
		return errors.New("rum delete failed")
	}
	return nil
}

func getDocSearchFieldNameAndWeight(searchField proto.KbRecallSearchField) (string, float64) {
	switch searchField {
	case proto.KbRecallSearchField_RSF_TITLE:
		return macro.PersonalKnowledgeBaseTitleFieldName, 1.5
	case proto.KbRecallSearchField_RSF_ABSTRACT:
		return macro.PersonalKnowledgeBaseAbstractFieldName, 1.0
	case proto.KbRecallSearchField_RSF_CONTENT:
		return macro.PersonalKnowledgeBaseContentFieldName, 1.0
	default:
		return "", 0
	}
}

func getBaseSearchFieldNameAndWeight(searchField proto.KbRecallSearchField) (string, float64) {
	switch searchField {
	case proto.KbRecallSearchField_RSF_TITLE:
		return macro.PersonalKnowledgeBaseKnowledgeBaseNameFieldName, 1.5
	case proto.KbRecallSearchField_RSF_DESCRIPTION:
		return macro.PersonalKnowledgeBaseKnowledgeBaseDescriptionFieldName, 1.0
	default:
		return "", 0
	}
}

func (p *PersonalKnowledgeBaseServiceImpl) getSearchDocCondition(ctx context.Context, params *proto.KbRecallSearchRequest) *model.MultiCondition {
	var mustConditions []model.MultiCondition
	var knowledgeBaseTypeShouldConditions []model.MultiCondition
	var knowledgeBaseIdShouldConditions []model.MultiCondition
	var searchWordsShouldConditions []model.MultiCondition

	// memberId 筛选项
	if params.MemberId != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseMemberIdFieldName,
				FieldValue:  params.MemberId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// query 筛选条件，检索 title、abstract
	if params.Query != "" {
		words := p.getSegment(ctx, params.Query)
		for _, searchField := range params.GetSearchRecallField() {
			searchFieldName, weight := getDocSearchFieldNameAndWeight(searchField)
			if searchFieldName == "" {
				continue
			}
			for _, word := range words {
				searchWordsShouldConditions = append(searchWordsShouldConditions, model.MultiCondition{
					Condition: &model.Condition{
						FieldName:   searchFieldName,
						FieldValue:  word.Value,
						OperateType: model.OperateTypeEq,
						Weight:      weight,
					},
				})
			}
		}
	}
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: searchWordsShouldConditions})

	// 知识库筛选条件
	for _, knowledgeBaseType := range params.GetKnowledgeBaseType() {
		knowledgeBaseTypeShouldConditions = append(knowledgeBaseTypeShouldConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
				FieldValue:  knowledgeBaseType.String(),
				OperateType: model.OperateTypeEq,
			},
		})
	}
	for _, knowledgeBaseId := range params.GetKnowledgeBaseIds() {
		knowledgeBaseIdShouldConditions = append(knowledgeBaseIdShouldConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
				FieldValue:  knowledgeBaseId,
				OperateType: model.OperateTypeEq,
			},
		})
	}
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: knowledgeBaseTypeShouldConditions})
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: knowledgeBaseIdShouldConditions})

	return &model.MultiCondition{
		Musts: mustConditions,
	}
}

func (p *PersonalKnowledgeBaseServiceImpl) getSearchBaseCondition(ctx context.Context, params *proto.KbRecallSearchRequest) *model.MultiCondition {
	var mustConditions []model.MultiCondition
	var knowledgeBaseTypeShouldConditions []model.MultiCondition
	var knowledgeBaseIdShouldConditions []model.MultiCondition
	var searchWordsShouldConditions []model.MultiCondition

	// memberId 筛选项
	if params.MemberId != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseMemberIdFieldName,
				FieldValue:  params.MemberId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	if params.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_FEATURE || params.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_ONLY {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseVisibilityFieldName,
				FieldValue:  params.GetVisibility().String(),
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// query 筛选条件，检索知识库相关字段
	if params.Query != "" {
		words := p.getSegment(ctx, params.Query)
		for _, searchField := range params.GetSearchRecallField() {
			searchFieldName, weight := getBaseSearchFieldNameAndWeight(searchField)
			if searchFieldName == "" {
				continue
			}
			for _, word := range words {
				searchWordsShouldConditions = append(searchWordsShouldConditions, model.MultiCondition{
					Condition: &model.Condition{
						FieldName:   searchFieldName,
						FieldValue:  word.Value,
						OperateType: model.OperateTypeEq,
						Weight:      weight,
					},
				})
			}
		}
	}
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: searchWordsShouldConditions})

	// 知识库筛选条件
	for _, knowledgeBaseType := range params.GetKnowledgeBaseType() {
		knowledgeBaseTypeShouldConditions = append(knowledgeBaseTypeShouldConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
				FieldValue:  knowledgeBaseType.String(),
				OperateType: model.OperateTypeEq,
			},
		})
	}
	for _, knowledgeBaseId := range params.GetKnowledgeBaseIds() {
		knowledgeBaseIdShouldConditions = append(knowledgeBaseIdShouldConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
				FieldValue:  knowledgeBaseId,
				OperateType: model.OperateTypeEq,
			},
		})
	}
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: knowledgeBaseTypeShouldConditions})
	mustConditions = append(mustConditions, model.MultiCondition{Shoulds: knowledgeBaseIdShouldConditions})

	return &model.MultiCondition{
		Musts: mustConditions,
	}
}

func (p *PersonalKnowledgeBaseServiceImpl) getBaseAllDocCondition(memberId int64, baseId int64, baseType proto.PersonalKnowledgeBaseType) *model.MultiCondition {
	var mustConditions []model.MultiCondition

	// memberId 筛选项
	mustConditions = append(mustConditions, model.MultiCondition{
		Condition: &model.Condition{
			FieldName:   macro.PersonalKnowledgeBaseMemberIdFieldName,
			FieldValue:  memberId,
			OperateType: model.OperateTypeEq,
		},
	})

	// 知识库 id 筛选条件
	mustConditions = append(mustConditions, model.MultiCondition{
		Condition: &model.Condition{
			FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
			FieldValue:  baseId,
			OperateType: model.OperateTypeEq,
		},
	})

	// 知识库 type 筛选条件
	mustConditions = append(mustConditions, model.MultiCondition{
		Condition: &model.Condition{
			FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
			FieldValue:  baseType.String(),
			OperateType: model.OperateTypeEq,
		},
	})

	return &model.MultiCondition{
		Musts: mustConditions,
	}
}

func getRuceneDocPathAndIndex(scene proto.KnowledgeBaseScene) (string, string) {
	switch scene {
	case proto.KnowledgeBaseScene_PERSONAL_ZHIDA:
		return model.PersonalKnowledgeDocPath, model.PersonalKnowledgeDocIndex
	case proto.KnowledgeBaseScene_INTERNAL_DOCUMENT:
		return model.InternalKnowledgeDocPath, model.InternalKnowledgeDocIndex
	default:
		return model.PersonalKnowledgeDocPath, model.PersonalKnowledgeDocIndex
	}
}
