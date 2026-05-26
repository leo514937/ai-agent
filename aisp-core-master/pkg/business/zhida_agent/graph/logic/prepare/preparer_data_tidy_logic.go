package prepare

import (
	"context"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 整理preparer数据
type PreparerDataTidyLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, *sourceResult]
	documentParseService service.DocumentParseService
	userCoreRpc          rpc.UserCoreService
	authorDescService    author.AuthorDescService
	contentCoreRpc       rpc.ContentCoreRPC
	doubleCheckTypes     []aiContent.DocType_Type
	aiIngressClient      rpc.AiIngressRPC
}

func NewPreparerDataTidyLogic(name string, config map[string]string) *PreparerDataTidyLogic {
	res := &PreparerDataTidyLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, *sourceResult](name, config),
	}
	res.userCoreRpc = impl.DefaultUserCoreServiceImpl
	res.authorDescService = author.DefaultAuthorDescService
	res.aiIngressClient = impl.DefaultAiIngressRPCImpl
	res.documentParseService = service.DefaultDocumentParseService
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	res.doubleCheckTypes = []aiContent.DocType_Type{aiContent.DocType_Webpage, aiContent.DocType_CrawlerWebpage}
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

func (m *PreparerDataTidyLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) (*sourceResult, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.PreparerDataTidyLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	result := make(map[string]*req_macro.SourceInfo)
	resultNew := make(map[string][]*req_macro.SourceInfo)
	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(m.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", m.GetName())
		return nil, nil
	}

	// 处理挂载源
	for _, universalKnowledgeBaseMeta := range requestCtx.GetBizContext().GetUniversalKnowledgeBaseInfo() {
		if universalKnowledgeBaseMeta != nil {
			sourceInfo := &req_macro.SourceInfo{
				Type:        req_macro.SourceTypeIndex,
				Description: universalKnowledgeBaseMeta.KnowledgeBaseDescription,
				Meta: req_macro.SourceMeta{
					Name: universalKnowledgeBaseMeta.KnowledgeBaseName,
				},
			}
			result[universalKnowledgeBaseMeta.KnowledgeBaseName] = sourceInfo
			resultNew[universalKnowledgeBaseMeta.KnowledgeBaseName] = append(resultNew[universalKnowledgeBaseMeta.KnowledgeBaseName], sourceInfo)
		}
	}

	// 处理挂载用户
	memberMetas := m.handleMembers(ctx, requestCtx)
	for _, memberMeta := range memberMetas {
		if memberMeta != nil {
			sourceInfo := &req_macro.SourceInfo{
				Type: req_macro.SourceTypePortfolio,
				Meta: req_macro.SourceMeta{
					ID:      memberMeta.MemberId,
					DocType: aiContent.DocType_Member,
					Name:    memberMeta.MemberName,
				},
				Description: memberMeta.MemberDescription,
			}
			result[memberMeta.MemberName] = sourceInfo
			resultNew[memberMeta.MemberName] = append(resultNew[memberMeta.MemberName], sourceInfo)
		}
	}

	// 处理知识库
	knowledgeBases := m.handleKnowledgeBase(ctx, requestCtx)
	for _, knowledgeBaseMeta := range knowledgeBases {
		if knowledgeBaseMeta != nil {
			sourceInfo := &req_macro.SourceInfo{
				Type: req_macro.SourceTypeKnowledgeBase,
				Meta: req_macro.SourceMeta{
					ID:                knowledgeBaseMeta.KnowledgeBaseId,
					KnowledgeBaseType: knowledgeBaseMeta.KnowledgeBaseType,
					Name:              knowledgeBaseMeta.KnowledgeBaseName,
				},
				Description: knowledgeBaseMeta.Description,
			}
			result[knowledgeBaseMeta.KnowledgeBaseName] = sourceInfo
			resultNew[knowledgeBaseMeta.KnowledgeBaseName] = append(resultNew[knowledgeBaseMeta.KnowledgeBaseName], sourceInfo)
		}
	}

	// 处理挂载文档
	mountDocs := m.handleMountDocs(ctx, requestCtx)
	for _, mountDoc := range mountDocs {
		if mountDoc != nil {
			description := mountDoc.snippet
			if description == "" {
				description = util.UnicodeSubstr(mountDoc.content, 0, 1024)
			}
			// 需要去取 DocName 和 Description
			sourceInfo := &req_macro.SourceInfo{
				Type: req_macro.SourceTypeSelected,
				Meta: req_macro.SourceMeta{
					ID:      mountDoc.id.ContentID,
					DocType: mountDoc.id.GetDocType(),
					Name:    mountDoc.title,
				},
				Description: description,
			}

			result[mountDoc.title] = sourceInfo
			resultNew[mountDoc.title] = append(resultNew[mountDoc.title], sourceInfo)
		}
	}

	resultObj := &sourceResult{
		sourceMap:    result,
		newSourceMap: resultNew,
	}
	// 保存tracing
	m.saveTracing(startTime, resultObj, requestCtx)
	return resultObj, nil
}

func (m *PreparerDataTidyLogic) handleMembers(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.AuthorInfo {
	result := make([]*model.AuthorInfo, 0)
	ids := requestCtx.GetBizContext().GetCurrReferenceMount().GetMountMembers()
	members, err := m.userCoreRpc.BatchGetUserByIds(ctx, ids, []string{
		user_core_thrift.ProfileField,
	})
	statisticMeta := m.authorDescService.BatchGetAuthorStatisticMeta(ctx, ids)
	if err == nil {
		for _, member := range members {
			if member == nil {
				continue
			}

			var description string
			// 如果当前用户有静态的meta 则直接替换获取静态meta
			if userStatisticMeta, isExist := statisticMeta[member.GetMeta().GetID()]; isExist {
				description = userStatisticMeta.Description
			}
			// 如果静态Meta为空，则使用平台的Description
			if description == "" {
				description = member.GetProfile().GetDescription()
			}
			// 如果平台的Description还是取不到，则直接使用用户的Headline
			if description == "" {
				description = member.GetProfile().GetHeadline()
			}
			result = append(result, &model.AuthorInfo{
				MemberId:          member.GetMeta().GetID(),
				MemberName:        member.GetProfile().GetFullname(),
				MemberDescription: description,
			})
		}
	}
	return result
}

func (m *PreparerDataTidyLogic) handleKnowledgeBase(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.KnowledgeBaseInfo {
	result := make([]*model.KnowledgeBaseInfo, 0)

	knowledgeBases := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	knowledgeBases = append(knowledgeBases, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)

	var otherKnowledgeBaseIds []int64
	for _, knowledgeBase := range knowledgeBases {
		if knowledgeBase.GetKnowledgeBaseId() == 0 {
			continue
		}
		if knowledgeBase.GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_FAV {
			otherKnowledgeBaseIds = append(otherKnowledgeBaseIds, knowledgeBase.GetKnowledgeBaseId())
		}
	}

	// 非收藏夹知识库
	resp := m.aiIngressClient.ConcurrentGetKnowledgeBaseDetail(ctx, requestCtx.GetBizContext().MemberId(), otherKnowledgeBaseIds, 0, 10)
	for _, knowledgeBase := range knowledgeBases {
		knowledgeMeta := resp[knowledgeBase.GetKnowledgeBaseId()]
		if knowledgeMeta == nil {
			continue
		}
		knowledgeBaseInfo := &model.KnowledgeBaseInfo{
			KnowledgeBaseId:   knowledgeBase.GetKnowledgeBaseId(),
			KnowledgeBaseName: knowledgeMeta.GetKnowledgeName(),
			KnowledgeBaseType: knowledgeBase.GetKnowledgeBaseType(),
			Description:       knowledgeMeta.GetKnowledgeDescription(),
		}

		result = append(result, knowledgeBaseInfo)
	}
	return result
}

func (m *PreparerDataTidyLogic) handleMountDocs(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*mountDocInfo {
	contents := make([]model.Content, 0)
	for _, docIdentity := range requestCtx.GetBizContext().GetCurrReferenceMount().GetMountDocs() {
		if docIdentity != nil {
			docId := docIdentity.GetDocId()
			docType := model.GetDocTypeByZhiDaType(docIdentity.GetDocType())
			// 只针对站内内容，获取 contentInfo
			if docType == aiContent.DocType_Unknown || docType == aiContent.DocType_Text || docType == aiContent.DocType_Link ||
				docType == aiContent.DocType_InternalDoc || docType == aiContent.DocType_AispUserUpload || docId == 0 {
				continue
			}
			contents = append(contents, model.NewContentWithDocType(docId, docType))
		}
	}

	// 查询内容 url token
	contentResultMap := m.contentCoreRpc.BatchGetContent(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)

	// check一下 其他业务 有没有知乎召回的内容，如果有，删除，重新召回
	deleteContents := make([]model.Content, 0)
	deleteContentKeyMap := make(map[model.Content]model.Content)
	reTryContents := make([]model.Content, 0)
	for k, v := range contentResultMap {
		if v == nil || !lo.Contains(m.doubleCheckTypes, k.GetDocType()) || !strings.Contains(v.GetBizExt(), "url") {
			continue
		}
		ext := &bizExt{}
		err := util.JSONUnmarshal([]byte(v.GetBizExt()), ext)
		if err != nil {
			continue
		}
		linkType, subType, token := util.ParseLinkInfo(ext.Url)
		// 判断是否知乎召回
		if linkType == util.LinkTypeZhihu && token != "" {
			deleteContents = append(deleteContents, k)
			deleteContentKeyMap[k] = model.NewContentWithToken(token, subType)
			reTryContents = append(reTryContents, deleteContentKeyMap[k])
		}
	}
	for _, k := range deleteContents {
		delete(contentResultMap, k)
	}
	reTryContentResultMap := m.contentCoreRpc.BatchGetContent(ctx, reTryContents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)
	contentResultMap = util.OverrideMap(contentResultMap, reTryContentResultMap)

	// 创建并发组
	group := safe_group.NewGroupWithTimeout("PreparerDataTidyLogic.handleMountDocs", 2000).SetLimit(200)
	// 创建结果通道
	resultChan := make(chan *mountDocInfo, len(contentResultMap))
	for k, v := range contentResultMap {
		group.Go(func() error {
			defer func() {
				if r := recover(); r != nil {
					log.Warnf(ctx, "PreparerDataTidyLogic.handleMountDocs Parse Panic => %v", r)
				}

				if v != nil {
					var title = v.GetTitle()
					var text string
					var snippet string
					// 维普 arxiv 的 pdf
					if model.GetDocType(v.GetContentType()) == aiContent.DocType_Paper {
						_, text = m.documentParseService.PaperParse(ctx, v)
					}

					// 用户上传
					if model.GetDocType(v.GetContentType()) == aiContent.DocType_ZhiDaUserUpload {
						_, text, snippet = m.documentParseService.UserUploadParse(ctx, v)
					}

					// 个人知识库订阅流
					if v.GetBizExtDetail() != nil && v.GetBizExtDetail().GetExternalWebpageBizExt() != nil {
						_, text = m.documentParseService.RssParse(ctx, v)
					}

					// 图文类型
					if v.GetContentBody() != nil {
						// 清洗正文
						body := v.GetContentBody().GetBody()
						filteredBody, err := util.ContentHtml2Markdown(ctx, body)
						if err == nil {
							text = filteredBody
						}
					}

					// 发送结果到通道
					resultChan <- &mountDocInfo{
						id:          k,
						baseContent: v,
						title:       title,
						content:     text,
						snippet:     snippet,
					}
				}
			}()
			return nil
		})
	}

	// 等待所有 goroutine 完成并关闭通道
	go func() {
		wgErr := group.Wait()
		if wgErr != nil {
			log.Errorf(ctx, "ContentCoreMetaFetcherLogic Parse Wait Err => %v", wgErr)
		}
		close(resultChan)
	}()

	result := make([]*mountDocInfo, 0)
	// 收集结果并更新 resMap
	for res := range resultChan {
		result = append(result, res)
	}

	// 处理title
	titleGroup := safe_group.NewGroupWithTimeout("PreparerDataTidyLogic.handleMountDocs.title", 2000).SetLimit(200)
	for _, doc := range result {
		if doc.title == "" && doc.baseContent != nil && doc.baseContent.GetExtInfo().GetParentInfo() != nil {
			titleGroup.Go(func() error {
				parentContentId := doc.baseContent.GetExtInfo().GetParentInfo().ContentID
				parentContentResultMap := m.contentCoreRpc.BatchGetContentByContentID(ctx, []string{parentContentId}, base.ContentInfoFieldContentTitle)
				parentContentInfo, parentContentInfoIsOk := parentContentResultMap[parentContentId]
				if parentContentInfoIsOk && parentContentInfo.GetOutID() != "" && parentContentInfo.GetTitle() != "" {
					doc.title = parentContentInfo.GetTitle()
				}
				return nil
			})
		}
	}
	_ = titleGroup.Wait()
	// 只保留 title 不为空的挂载内容
	return lo.Filter(result, func(item *mountDocInfo, index int) bool {
		return item.title != ""
	})
}

func (m *PreparerDataTidyLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], result *sourceResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.MembersInfoLogic.realMergeUser")
	defer span.Finish()
	if result != nil {
		requestCtx.GetBizContext().SetSourceMap(result.sourceMap)
		requestCtx.GetBizContext().SetSearchSourceMap(result.newSourceMap)
	}
	return nil
}

func (m *PreparerDataTidyLogic) saveTracing(startTime int64, sourceR *sourceResult, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   m.GetName(),
		LogicInput:  []string{},
		LogicOutput: []string{util.GetJSONIgnoreError(sourceR)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(m.GetName(), logicTracing)
}

type bizExt struct {
	Url string `json:"url"`
}

type mountDocInfo struct {
	id          model.Content
	baseContent *base.ContentInfo
	title       string
	content     string
	snippet     string
}

type sourceResult struct {
	sourceMap    map[string]*req_macro.SourceInfo
	newSourceMap map[string][]*req_macro.SourceInfo
}
