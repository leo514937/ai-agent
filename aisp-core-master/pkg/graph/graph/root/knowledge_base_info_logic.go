package root

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/utils"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	knowledge "git.in.zhihu.com/one-rpc-go/thrift-ai_ingress/knowledge_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/thrift-go/zfav_go_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	mapset "github.com/deckarep/golang-set"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 获取知识库详细信息
type KnowledgeBaseInfoLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.KnowledgeBaseInfo]
	aiIngressClient       rpc.AiIngressRPC
	contentCoreRpc        rpc.ContentCoreRPC
	zFavRPC               rpc.ZFavRPC
	knowledgebaseDao      dao.KnowledgeBaseV2Dao
	promptService         prompt.PromptMapperService
	promptApolloNamespace string
}

func NewKnowledgeBaseInfoLogic(name string, config map[string]string) *KnowledgeBaseInfoLogic {
	res := &KnowledgeBaseInfoLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.KnowledgeBaseInfo](name, config),
	}
	res.aiIngressClient = impl.DefaultAiIngressRPCImpl
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	res.zFavRPC = impl.DefaultZFavRPCImpl
	res.knowledgebaseDao = daoImpl.DefaultKnowledgeBaseV2DaoImpl
	res.promptService = prompt.DefaultPromptMapperService
	res.promptApolloNamespace = prompt.ConfigNamespaceAI
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

var zhihuDocTypeSet = mapset.NewSet(
	content.DocType_Answer,
	content.DocType_Article,
	content.DocType_ZVideo,
	content.DocType_Pin)

func (s *KnowledgeBaseInfoLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) ([]*model.KnowledgeBaseInfo, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.KnowledgeBaseInfoLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	var result []*model.KnowledgeBaseInfo

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.KnowledgeBaseInfoSkip.ToConvert()))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", s.GetName())
		return result, nil
	}

	kbDocLimit := cast.ToInt64(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.ConfigLimit))
	if kbDocLimit == 0 {
		log.Infof(ctx, "kbDocLimit is zero: %s", s.GetName())
		return result, nil
	}

	// 根据请求传入的 knowledgeBase 获取其详细信息
	memberId := requestCtx.GetBizContext().MemberId()
	knowledgeBases := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	knowledgeBases = append(knowledgeBases, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)

	// 此处耦合业务逻辑。正常挂载下，挂载与大类知识库互斥；订阅挂载下，挂载与大类知识库同时存在。此处判定只有正常挂载，才获取知识库 meta 信息塞给模型 context
	// todo: @wangran 后续优化订阅逻辑
	if len(requestCtx.GetBizContext().GetKnowledgeBases()) > 0 && len(knowledgeBases) > 1 {
		return result, nil
	}

	var favKnowledgeBaseIds, otherKnowledgeBaseIds []int64
	var hasFavUniversalBase = requestCtx.GetBizContext().GetCurrReferenceMount().HasFavUniversalBase()
	for _, knowledgeBase := range knowledgeBases {
		if knowledgeBase.GetKnowledgeBaseId() == 0 {
			continue
		}
		if knowledgeBase.GetKnowledgeBaseType() == proto.PersonalKnowledgeBaseType_PKB_FAV {
			favKnowledgeBaseIds = append(favKnowledgeBaseIds, knowledgeBase.GetKnowledgeBaseId())
		} else {
			otherKnowledgeBaseIds = append(otherKnowledgeBaseIds, knowledgeBase.GetKnowledgeBaseId())
		}
	}

	// 收藏夹和其他知识库分开查询
	// 1、非收藏夹内容，从后端接口获取
	resp := s.aiIngressClient.ConcurrentGetKnowledgeBaseDetail(ctx, requestCtx.GetBizContext().MemberId(), otherKnowledgeBaseIds, kbDocLimit, 10)
	for _, knowledgeBase := range knowledgeBases {
		knowledgeMeta := resp[knowledgeBase.GetKnowledgeBaseId()]
		if knowledgeMeta == nil {
			continue
		}
		knowledgeBaseInfo := &model.KnowledgeBaseInfo{
			KnowledgeBaseId:   knowledgeBase.GetKnowledgeBaseId(),
			KnowledgeBaseName: knowledgeMeta.GetKnowledgeName(),
			KnowledgeBaseType: knowledgeBase.GetKnowledgeBaseType(),
			Total:             knowledgeMeta.GetTotal(),
			Description:       knowledgeMeta.GetKnowledgeDescription(),
		}
		for _, kbItems := range knowledgeMeta.GetKnowledgeItems() {
			docType := model.GetDocType(kbItems.GetType())
			if docType == content.DocType_ZhiDaUserUpload {
				knowledgeBaseInfo.UserUploadCount = kbItems.GetCount()
			} else if docType == content.DocType_Webpage {
				knowledgeBaseInfo.WebPageCount = kbItems.GetCount()
			} else if zhihuDocTypeSet.Contains(docType) {
				knowledgeBaseInfo.ZhihuCount += kbItems.GetCount()
			} else {
				continue
			}
			knowledgeBaseInfo.Docs = append(knowledgeBaseInfo.Docs, s.getDocMetas(ctx, kbItems.GetItems(), docType)...)
		}

		knowledgeBaseInfo.KnowledgeBaseTypeName = getKnowledgeBaseTypeName(knowledgeBase.GetKnowledgeBaseType())
		sort.Slice(knowledgeBaseInfo.Docs, func(i, j int) bool {
			return knowledgeBaseInfo.Docs[i].JoinedTime > knowledgeBaseInfo.Docs[j].JoinedTime
		})
		knowledgeBaseInfo.Docs = knowledgeBaseInfo.Docs[:utils.MinInt(len(knowledgeBaseInfo.Docs), int(kbDocLimit))]

		result = append(result, knowledgeBaseInfo)
	}

	// 2、收藏夹 meta 信息从单独的 rpc 获取
	result = append(result, s.getFavMetas(ctx, memberId, favKnowledgeBaseIds, hasFavUniversalBase)...)

	constant.DataInputNodeLog.Infof(logCtx, "bases:%s", util.GetJSONIgnoreError(knowledgeBases))
	macro.ProcessNodeLog.Infof(logCtx, "rpc:%s", util.GetJSONIgnoreError(resp))
	constant.DataOutputNodeLog.Infof(logCtx, "result:%s", util.GetJSONIgnoreError(result))

	s.saveTracing(knowledgeBases, result, startTime, requestCtx)

	return result, nil
}

func (s *KnowledgeBaseInfoLogic) getFavMetas(ctx context.Context, memberId int64, favListIds []int64, hasFavUniversalBase bool) []*model.KnowledgeBaseInfo {
	var zfavLists []*zfav_go_thrift.Favlist
	if hasFavUniversalBase {
		zfavLists = s.zFavRPC.ListMemberFavlist(ctx, memberId)
	} else {
		for _, favListId := range favListIds {
			zfavLists = append(zfavLists, s.zFavRPC.GetFavlist(ctx, memberId, favListId))
		}
	}

	result := make([]*model.KnowledgeBaseInfo, 0)
	for _, zfavList := range zfavLists {
		if zfavList == nil {
			continue
		}
		baseInfo := &model.KnowledgeBaseInfo{
			KnowledgeBaseId:       zfavList.GetID(),
			KnowledgeBaseName:     zfavList.GetTitle(),
			KnowledgeBaseType:     proto.PersonalKnowledgeBaseType_PKB_FAV,
			KnowledgeBaseTypeName: getKnowledgeBaseTypeName(proto.PersonalKnowledgeBaseType_PKB_FAV),
			Docs:                  s.getFavDocMetas(ctx, memberId, zfavList.GetID()),
			CreatedAt:             util.TimeStamp2Date(zfavList.GetCreated()),
			UpdatedAt:             util.TimeStamp2Date(zfavList.GetLastUpdated()),
		}
		baseInfo.Total = int64(len(baseInfo.Docs))
		sort.Slice(baseInfo.Docs, func(i, j int) bool {
			return baseInfo.Docs[i].JoinedTime > baseInfo.Docs[j].JoinedTime
		})
		for idx, doc := range baseInfo.Docs {
			doc.Idx = idx
		}
		baseInfo.Docs = baseInfo.Docs[:utils.MinInt(len(baseInfo.Docs), 50)]
		result = append(result, baseInfo)
	}

	return result
}

func (s *KnowledgeBaseInfoLogic) getFavDocMetas(ctx context.Context, memberId int64, knowledgeBaseId int64) []*model.KbDocMeta {
	favItemList := s.zFavRPC.ListFavlistItem(ctx, memberId, knowledgeBaseId)

	result := make([]*model.KbDocMeta, 0)
	docTypeItemsMap := map[content.DocType_Type][]*knowledge.Item{}

	for _, kbDoc := range favItemList {
		docType := rpc.ContentType2DocType(kbDoc.GetContentType())
		if docType == content.DocType_Unknown {
			continue
		}
		docTypeItemsMap[docType] = append(docTypeItemsMap[docType], &knowledge.Item{ID: kbDoc.ContentID, CreatedAt: kbDoc.GetCreated()})
	}

	for docType, items := range docTypeItemsMap {
		result = append(result, s.getDocMetas(ctx, items, docType)...)
	}

	return result
}

func (s *KnowledgeBaseInfoLogic) getDocMetas(ctx context.Context, docs []*knowledge.Item, docType content.DocType_Type) []*model.KbDocMeta {
	contents := make([]model.Content, 0)
	for _, doc := range docs {
		contents = append(contents, model.Content{
			ContentID:   doc.GetID(),
			ContentType: docType,
		})
	}

	contentResultMap := s.contentCoreRpc.BatchGetContent(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentExtInfo,
	)

	var result []*model.KbDocMeta
	for _, doc := range docs {
		contentInfo, isOk := contentResultMap[model.Content{
			ContentID:   doc.GetID(),
			ContentType: docType,
		}]
		if !isOk {
			continue
		}
		title := contentInfo.GetTitle()
		if title == "" && contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
			contentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
			title = s.getParentTitle(ctx, contentInfo.GetExtInfo().GetParentInfo().ContentID)
		}

		var url string
		if contentInfo.GetExtInfo() != nil {
			url = contentInfo.GetExtInfo().GetURL()
		}

		result = append(result, &model.KbDocMeta{
			DocId:      doc.GetID(),
			DocType:    docType,
			DocTypeStr: docTypeNameMap[docType],
			Url:        url,
			Title:      title,
			JoinedTime: doc.GetCreatedAt(),
		})
	}

	return result
}

var docTypeNameMap = map[content.DocType_Type]string{
	content.DocType_Answer:  "知乎回答",
	content.DocType_Article: "知乎文章",
}

func (s *KnowledgeBaseInfoLogic) getParentTitle(ctx context.Context, contentId string) string {
	resp := s.contentCoreRpc.BatchGetContentByContentID(ctx, []string{contentId}, base.ContentInfoFieldContentTitle)
	if resp != nil && resp[contentId] != nil {
		return resp[contentId].GetTitle()
	}
	return ""
}

func getKnowledgeBaseTypeName(knowledgeBaseType proto.PersonalKnowledgeBaseType) string {
	switch knowledgeBaseType {
	case proto.PersonalKnowledgeBaseType_PKB_FAV:
		return "用户个人收藏夹"
	case proto.PersonalKnowledgeBaseType_PKB_RSS:
		return "用户rss订阅"
	case proto.PersonalKnowledgeBaseType_PKB_FOLDER:
		return "用户个人知识库"
	default:
		return "未知"
	}
}

// loadPrompt 加载 prompt
func (s *KnowledgeBaseInfoLogic) loadPrompt(ctx context.Context, promptId string, defaultPromptTemplate string, promptTag string, memberID int64, apolloNamespace string) string {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":   "pkg.graph.graph.generate.MessageHandler",
		"method": "loadPrompt",
	})

	promptTemp := "{{.Query}}"
	if defaultPromptTemplate != "" {
		promptTemp = defaultPromptTemplate
	}

	logger.Infof(ctx, "loadPrompt start.")
	if promptId == "" {
		logger.Infof(ctx, "loadPrompt promptID is empty.")
		return promptTemp
	}
	return s.promptService.LoadPromptByApolloNamespace(ctx, promptId, promptTemp, promptTag, memberID, apolloNamespace)
}

func (s *KnowledgeBaseInfoLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], knowledgeBaseInfo []*model.KnowledgeBaseInfo) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.ChatHistoryLogic.realMergeUser")
	defer span.Finish()

	var hasFavUniversalBase = requestCtx.GetBizContext().GetCurrReferenceMount().HasFavUniversalBase()
	if hasFavUniversalBase {
		// 过滤收藏夹知识库
		favBaseList := lo.Filter(knowledgeBaseInfo, func(item *model.KnowledgeBaseInfo, _ int) bool {
			return item.KnowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_FAV
		})
		// 处理收藏夹整体描述
		var universalFavDescription string
		if len(favBaseList) > 0 {
			favBaseCount := len(favBaseList)
			docCount := 0
			for _, favBase := range favBaseList {
				docCount += len(favBase.Docs)
			}
			promptInput := model.PromptInput{
				FavBaseCount: favBaseCount,
				DocCount:     docCount,
				Date:         util.GetNowDate(),
			}
			promptContent, err := model.GenPrompt(&promptInput, s.promptService.LoadPromptByApolloNamespace(ctx, "fav_base", "", "", user.MemberId(), s.promptApolloNamespace), "fav_knowledge_base_info")
			if err == nil && promptContent != "" {
				universalFavDescription = promptContent
			}
		}
		// 获取子收藏夹描述
		var favDescriptions []string
		for _, favBase := range favBaseList {
			promptInput := model.PromptInput{
				KnowledgeBaseInfo: []*model.KnowledgeBaseInfo{favBase},
			}
			knowledgeBaseTemplate := s.promptService.LoadPromptByApolloNamespace(ctx, "fav_base_item", "", "", user.MemberId(), s.promptApolloNamespace)
			promptContent, err := model.GenPrompt(&promptInput, knowledgeBaseTemplate, "knowledge_base_info_meta")
			if err != nil {
				continue
			}
			favDescriptions = append(favDescriptions, promptContent)
		}
		requestCtx.GetBizContext().SetKnowledgeBaseInfo([]*model.KnowledgeBaseInfo{
			{KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FAV,
				Description: fmt.Sprintf("%s\n%s", universalFavDescription, strings.Join(favDescriptions, "\n")),
			},
		})
		return nil
	}

	// 生成知识库Desc信息
	for _, baseInfo := range knowledgeBaseInfo {
		promptInput := model.PromptInput{
			KnowledgeBaseInfo: []*model.KnowledgeBaseInfo{baseInfo},
		}
		var knowledgeBaseTemplate string
		if baseInfo.KnowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_FAV {
			knowledgeBaseTemplate = s.promptService.LoadPromptByApolloNamespace(ctx, "fav_base_item", "", "", user.MemberId(), s.promptApolloNamespace)
		} else {
			knowledgeBaseTemplate = s.promptService.LoadPromptByApolloNamespace(ctx, "knowledge_base", "", "", user.MemberId(), s.promptApolloNamespace)
		}
		promptContent, err := model.GenPrompt(&promptInput, knowledgeBaseTemplate, "knowledge_base_info_meta")
		if err != nil {
			continue
		}
		baseInfo.Description = promptContent
	}

	requestCtx.GetBizContext().SetKnowledgeBaseInfo(knowledgeBaseInfo)
	return nil
}

func (s *KnowledgeBaseInfoLogic) saveTracing(knowledgeBases []*proto.PersonalKnowledgeBase, knowledgeBaseInfo []*model.KnowledgeBaseInfo, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(knowledgeBases)},
		LogicOutput: []string{util.GetJSONIgnoreError(knowledgeBaseInfo)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)
}
