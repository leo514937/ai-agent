package util

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/conf/digital_author_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

var rumLogicConditionFuncMap = map[string]func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32){
	digital_author_conf.RumP0CustomRecallLogic:                       getDigitalAuthorRumP0QueryCondition,
	digital_author_conf.RumP1ZhihuRecallLogic:                        getDigitalAuthorRumP1ZhihuQueryCondition,
	digital_author_conf.RumP2ZhihuRecallLogic:                        getDigitalAuthorRumP2ZhihuQueryCondition,
	digital_author_conf.RumP2LawRecallLogic:                          getDigitalAuthorRumP2LawQueryCondition,
	stream_chat_default_tab_conf.KbOutSiteRumRecallLogic:             getZhidaQueryCondition,
	stream_chat_default_tab_conf.AuthorSearchRecallLogic:             getZhidaQueryCondition,
	stream_chat_default_tab_conf.KbZhWikiRumRecallLogic:              getZhidaQueryCondition,
	stream_chat_default_tab_conf.KbEnWikiRumRecallLogic:              getZhidaQueryCondition,
	stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic: getZhidaPersonalKnowledgeBaseRumQueryCondition,
	stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic: getZhidaInternalKnowledgeBaseRumQueryCondition,
}
var rumLogicGenItemFuncMap = map[string]func(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error){
	digital_author_conf.RumP0CustomRecallLogic:                       genDigitalAuthorRumP0CustomItem,
	digital_author_conf.RumP1ZhihuRecallLogic:                        genDigitalAuthorRumP1ZhihuItem,
	digital_author_conf.RumP2ZhihuRecallLogic:                        genDigitalAuthorRumP2ZhihuItem,
	digital_author_conf.RumP2LawRecallLogic:                          genDigitalAuthorRumP2LawItem,
	stream_chat_default_tab_conf.KbOutSiteRumRecallLogic:             genZhidaRumItem,
	stream_chat_default_tab_conf.AuthorSearchRecallLogic:             genAuthorRumItem,
	stream_chat_default_tab_conf.KbZhWikiRumRecallLogic:              genWikiRumItem,
	stream_chat_default_tab_conf.KbEnWikiRumRecallLogic:              genWikiRumItem,
	stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic: genPersonalKnowledgeBaseRumItem,
	stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic: genPersonalKnowledgeBaseRumItem,
}
var digitalAuthorRumRecallNameFmt = "Rum_%s_%s_Recaller"

func getDigitalAuthorRumP0QueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	condition := fmt.Sprintf("author_id==%d", requestCtx.GetBizContext().AuthorInfo().GetMemberId())
	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.KlaraEmbedding
	return []string{condition}, embedding
}

func getDigitalAuthorRumP1ZhihuQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	// 用户未开启知识库同步，不召回 p1 库
	isP1Enable := requestCtx.GetBizContext().AuthorInfo().UserMeta().IsEnableOnsite()
	if !isP1Enable {
		return []string{}, nil
	}

	condition := fmt.Sprintf("author_id==%d and enable==1", requestCtx.GetBizContext().AuthorInfo().GetMemberId())
	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.UnifiedEmbedding
	return []string{condition}, embedding
}

func getDigitalAuthorRumP2ZhihuQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	// 用户未开启通用知识库，不召回 p2 库
	isP2Enable := requestCtx.GetBizContext().AuthorInfo().UserMeta().IsEnableUniversal()
	if !isP2Enable {
		return []string{}, nil
	}

	condition := "enable==1"
	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.UnifiedEmbedding
	return []string{condition}, embedding
}

func getDigitalAuthorRumP2LawQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	// 用户未开启通用知识库，不召回 p2 库
	isP2Enable := requestCtx.GetBizContext().AuthorInfo().UserMeta().IsEnableUniversal()
	if !isP2Enable {
		return []string{}, nil
	}

	condition := ""
	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.KlaraEmbedding
	return []string{condition}, embedding
}

func getZhidaQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	if requestCtx.GetBizContext().GetQueryMerge() == nil || len(requestCtx.GetBizContext().GetQueryMerge().ItemMeta.KlaraEmbedding) == 0 {
		return []string{}, []float32{}
	}
	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.KlaraEmbedding
	return []string{""}, embedding
}

// 直答专业版个人知识库 查询条件
func getZhidaPersonalKnowledgeBaseRumQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	if requestCtx.GetBizContext().GetQueryMerge() == nil || len(requestCtx.GetBizContext().GetQueryMerge().ItemMeta.BgeM3Embedding) == 0 {
		return []string{}, []float32{}
	}

	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.BgeM3Embedding
	var rumConditions []string

	// 1.勾选个人知识库大类，且非挂载态，检索范围为 memberId 的整个知识库
	hasUniversalPersonalKnowledgeBase := lo.Contains(requestCtx.GetBizContext().GetKnowledgeBases(), proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE)
	if hasUniversalPersonalKnowledgeBase {
		rumConditions = append(rumConditions, fmt.Sprintf("member_id==%d", requestCtx.GetBizContext().MemberId()))
	}

	// 2.用户挂载的个人知识库，包括当前挂载和历史挂载，包括挂载大类 type 和挂载具体的 id+type
	personalKnowledgeBaseList := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	personalKnowledgeBaseList = append(personalKnowledgeBaseList, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)
	if len(personalKnowledgeBaseList) == 0 {
		personalKnowledgeBaseList = append(personalKnowledgeBaseList, requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountBases()...)
	}
	personalKnowledgeBaseList = lo.Filter(personalKnowledgeBaseList, func(kb *proto.PersonalKnowledgeBase, _ int) bool {
		return kb.KnowledgeBaseType != proto.PersonalKnowledgeBaseType_PKB_INTERNAL
	})

	var idConditions []string
	for _, kb := range personalKnowledgeBaseList {
		if kb.GetKnowledgeBaseId() != 0 && kb.GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED {
			// 2.1 勾选了个人知识库具体的 id+type，如收藏夹 id1、订阅知识库 id2，则检索 子类类型 + 子类 id
			condition := fmt.Sprintf("(knowledge_base_type==%s and knowledge_base_id==%d)", kb.KnowledgeBaseType.String(), kb.KnowledgeBaseId)
			// 为避免挂载过多，进行 limit 限制，10个以内分别召回，10个以上混合召回
			if len(rumConditions) < 10 {
				rumConditions = append(rumConditions, condition)
			} else {
				idConditions = append(idConditions, condition)
			}
		} else if kb.GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED && (kb.GetVisibility() == proto.KnowledgeBaseVisibility_UNDEFINED_VISIBILITY || kb.GetVisibility() == proto.KnowledgeBaseVisibility_PRIVATE) {
			// 2.2 勾选了个人知识库子类，如收藏、rss源，则检索 memberId + 子类类型
			rumConditions = append(rumConditions, fmt.Sprintf("member_id==%d and knowledge_base_type==%s", requestCtx.GetBizContext().MemberId(), kb.KnowledgeBaseType.String()))
		} else if kb.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_FEATURE || kb.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_ONLY {
			// 2.3 勾选公共知识库所有，则检索可见性
			rumConditions = append(rumConditions, fmt.Sprintf("extra==%s", kb.Visibility.String()))
		}
	}
	if len(idConditions) > 0 {
		rumConditions = append(rumConditions, strings.Join(idConditions, "or"))
	}

	return rumConditions, embedding
}

// 直答专业版内部知识库 查询条件
func getZhidaInternalKnowledgeBaseRumQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	if requestCtx.GetBizContext().GetQueryMerge() == nil || len(requestCtx.GetBizContext().GetQueryMerge().ItemMeta.BgeM3Embedding) == 0 {
		return []string{}, []float32{}
	}

	embedding := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.BgeM3Embedding

	// 用户挂载的个人知识库，只包括当前挂载，包括挂载具体的 id+type
	internalKnowledgeBaseList := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	internalKnowledgeBaseList = append(internalKnowledgeBaseList, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)
	internalKnowledgeBaseList = lo.Filter(internalKnowledgeBaseList, func(kb *proto.PersonalKnowledgeBase, _ int) bool {
		return kb.KnowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_INTERNAL
	})

	// 无知识库勾选，返回 nil
	if len(internalKnowledgeBaseList) == 0 {
		return []string{}, []float32{}
	}
	knowledgeBaseTypeMap := map[proto.PersonalKnowledgeBaseType][]int64{}
	for _, internalKnowledgeBase := range internalKnowledgeBaseList {
		if _, exist := knowledgeBaseTypeMap[internalKnowledgeBase.GetKnowledgeBaseType()]; !exist {
			knowledgeBaseTypeMap[internalKnowledgeBase.GetKnowledgeBaseType()] = []int64{}
		}
		if internalKnowledgeBase.GetKnowledgeBaseId() > 0 {
			knowledgeBaseTypeMap[internalKnowledgeBase.GetKnowledgeBaseType()] = append(knowledgeBaseTypeMap[internalKnowledgeBase.GetKnowledgeBaseType()], internalKnowledgeBase.GetKnowledgeBaseId())
		}
	}

	var kbConditionStrArr []string
	for knowledgeBaseType, knowledgeBaseIdList := range knowledgeBaseTypeMap {
		fmtStr := ""
		if len(knowledgeBaseIdList) == 0 {
			fmtStr = fmt.Sprintf("(knowledge_base_type==%s)", knowledgeBaseType.String())
		} else {
			fmtStr = fmt.Sprintf("(knowledge_base_type==%s and knowledge_base_id in (%s))",
				knowledgeBaseType.String(), strings.Join(cast.ToStringSlice(knowledgeBaseIdList), ","))
		}
		kbConditionStrArr = append(kbConditionStrArr, fmtStr)
	}
	rumCondition := strings.Join(kbConditionStrArr, " or ")

	if len(requestCtx.GetBizContext().GetQueryTags()) > 0 {
		tagConditionStr := fmt.Sprintf("%s in (%s)", macro.PersonalKnowledgeBaseExtraRumFieldName, strings.Join(requestCtx.GetBizContext().GetQueryTags(), ","))
		rumCondition = fmt.Sprintf("(%s) and %s", rumCondition, tagConditionStr)
	}

	return []string{rumCondition}, embedding
}

func genDigitalAuthorRumP0CustomItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	item := genDigitalAuthorItem(rumItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel0
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceAuthorCustom
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRumRecallNameFmt, conf.IndexLevel0, conf.IndexSourceAuthorCustom)
	return item, nil
}
func genDigitalAuthorRumP1ZhihuItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	item := genDigitalAuthorItem(rumItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel1
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceZhihu
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRumRecallNameFmt, conf.IndexLevel1, conf.IndexSourceZhihu)
	return item, nil
}
func genDigitalAuthorRumP2ZhihuItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	item := genDigitalAuthorItem(rumItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel2
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceZhihu
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRumRecallNameFmt, conf.IndexLevel2, conf.IndexSourceZhihu)
	return item, nil
}
func genDigitalAuthorRumP2LawItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	item := genDigitalAuthorItem(rumItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel2
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceLaw
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRumRecallNameFmt, conf.IndexLevel2, conf.IndexSourceLaw)
	return item, nil
}
func genDigitalAuthorItem(rumItem *rpc.SearchResult) *entities.Item {
	indexDocUniqueId := rumItem.GetId()
	authorId := util.InterfaceTryGetInt64(rumItem.Fields[macro.AuthorIdFieldName], 0)
	docId := util.InterfaceTryGetInt64(rumItem.Fields[macro.DocIdCopyFieldName], 0)
	docTypeStr := util.InterfaceTryGetString(rumItem.Fields[macro.DocTypeFieldName], "")
	docType := content2.DocType_Type(content2.DocType_Type_value[docTypeStr])
	docUrl := util.InterfaceTryGetString(rumItem.Fields[macro.DocUrlFieldName], "")
	title := util.InterfaceTryGetString(rumItem.Fields[macro.TitleFieldName], "")
	content := util.InterfaceTryGetString(rumItem.Fields[macro.ContentFieldName], "")
	contentLevel := util.InterfaceTryGetInt64(rumItem.Fields[macro.ContentLevelFieldName], 0)
	bayesFirstName := util.InterfaceTryGetString(rumItem.Fields[macro.BayesFirstNameFieldName], "")
	enable := util.InterfaceTryGetInt64(rumItem.Fields[macro.EnableFieldName], 0)
	embeddingSource := util.InterfaceTryGetString(rumItem.Fields[macro.EmbeddingSourceFieldName], "")

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallDoc,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 content,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          docType,
			AuthorId:         authorId,
			Title:            title,
			Url:              docUrl,
			ContentLevel:     contentLevel,
			Content:          content,
			BayesFirstName:   bayesFirstName,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore:     float64(rumItem.GetSim()),
				Enable:          enable,
				EmbeddingSource: embeddingSource,
			},
		},
	}

	return item
}

func genWikiRumItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	indexDocUniqueId := rumItem.GetId()
	docId := util.InterfaceTryGetInt64(rumItem.Fields[macro.ScienceKBDocIdFieldName], 0)
	title := util.InterfaceTryGetString(rumItem.Fields[macro.ScienceKBFieldName], "")
	contentText := util.InterfaceTryGetString(rumItem.Fields[macro.ScienceKBRawFieldName], "")
	docUrl := util.InterfaceTryGetString(rumItem.Fields[macro.ScienceKBUrlFieldName], "")

	docType := content2.DocType_Text

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 contentText,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          docType,
			Title:            title,
			Content:          contentText,
			Abstract:         util.UnicodeSubstr(contentText, 0, macro.CardAbstractLimit),
			Url:              docUrl,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore: float64(rumItem.GetSim()),
			},
		},
	}

	return item, nil
}

func genPersonalKnowledgeBaseRumItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	indexDocUniqueId := rumItem.GetId()
	docId := util.InterfaceTryGetInt64(rumItem.Fields[macro.PersonalKnowledgeBaseDocIdFieldName], 0)
	docType := util.InterfaceTryGetString(rumItem.Fields[macro.PersonalKnowledgeBaseDocTypeFieldName], "")
	baseId := util.InterfaceTryGetInt64(rumItem.Fields[macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName], 0)
	baseName := util.InterfaceTryGetString(rumItem.Fields[macro.PersonalKnowledgeBaseKnowledgeBaseNameFieldName], "")
	baseType := util.InterfaceTryGetString(rumItem.Fields[macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName], "")
	memberId := util.InterfaceTryGetInt64(rumItem.Fields[macro.PersonalKnowledgeBaseMemberIdFieldName], 0)
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          content2.DocType_Type(content2.DocType_Type_value[docType]),
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore:                float64(rumItem.GetSim()),
				KnowledgeBaseId:            baseId,
				KnowledgeBaseName:          baseName,
				PersonalKnowledgeBaseType:  proto.PersonalKnowledgeBaseType(proto.PersonalKnowledgeBaseType_value[baseType]),
				KnowledgeBaseCreator:       memberId,
				UniversalKnowledgeBaseType: enums.KnowledgeBaseTypePersonal,
			},
		},
	}
	return item, nil
}

func genZhidaRumItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	indexDocUniqueId := rumItem.GetId()
	title := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteTitleFieldName], "")
	contentText := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteContentFieldName], "")
	linkUrl := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteLinkUrlFieldName], "")
	source := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteLinkSourceFieldName], "")
	sourceType := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteLinkSourceTypeFieldName], "")
	domain := util.InterfaceTryGetString(rumItem.Fields[macro.ZhidaOutSiteDomainFieldName], "")
	publishTime := util.InterfaceTryGetInt64(rumItem.Fields[macro.ZhidaOutSitePublishTimeFieldName], 0)

	if utf8.RuneCountInString(contentText) < 20 || len(title) == 0 || !strings.HasPrefix(linkUrl, "http") {
		return nil, errors.New(fmt.Sprintf("contentText or title or linkUrl is empty. contentText: %s, title: %s, linkUrl: %s", contentText, title, linkUrl))
	}

	linkType, subType, token := util.ParseLinkInfo(linkUrl)
	docType := model.GetDocType(subType)

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk, // todo: 待重排序 ready 之后改为 doc
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 contentText,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			Title:            title,
			Content:          contentText,
			Abstract:         util.UnicodeSubstr(contentText, 0, macro.CardAbstractLimit),
			Domain:           domain,
			Url:              linkUrl,
			DocType:          content2.DocType_Link,
			PublishedTime:    publishTime,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore:       float64(rumItem.GetSim()),
				CrawlerSource:     source,
				CrawlerSourceType: sourceType,
			},
		},
	}

	// 对于站内内容，写入 type 和 token
	if linkType == util.LinkTypeZhihu && docType != content2.DocType_Unknown && token != "" {
		item.GetItemMeta().UrlToken = token
		item.GetItemMeta().DocType = docType
	}

	return item, nil
}

func genAuthorRumItem(ctx context.Context, rumItem *rpc.SearchResult) (*entities.Item, error) {
	indexDocUniqueId := rumItem.GetId()
	similarity := rumItem.Sim
	authorId := util.InterfaceTryGetInt64(rumItem.Fields[macro.ZhidaAuthorFiledNameAuthorId], 0)
	authorDetail := author.DefaultAuthorDescService.BatchGetAuthorDetail(ctx, []int64{authorId})

	authorMeta := authorDetail[authorId]
	if authorMeta == nil {
		return nil, errors.New(fmt.Sprintf("author detail not found for authorId: %d", authorId))
	}

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 authorDetail[authorId].Description,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			Content:          authorDetail[authorId].Description,
			AuthorId:         authorId,
			DocType:          content2.DocType_Member,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore: float64(rumItem.GetSim()),
			},
			Url:            authorDetail[authorId].Url,
			AuthorUserMeta: authorMeta,
			Similarity:     float64(similarity),
		},
	}

	return item, nil
}

func GetRumQueryConditions(logicName string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]string, []float32) {
	if f := rumLogicConditionFuncMap[logicName]; f != nil {
		return f(requestCtx)
	}
	return []string{}, nil
}

func GenRumItem(ctx context.Context, logicName string, rumItem *rpc.SearchResult) (*entities.Item, error) {
	if f := rumLogicGenItemFuncMap[logicName]; f != nil {
		return f(ctx, rumItem)
	}
	return nil, errors.New("no genRumItem func found")
}

func GetStoreFields(logicName string) []string {
	switch logicName {
	case digital_author_conf.RumP0CustomRecallLogic:
	case digital_author_conf.RumP1ZhihuRecallLogic:
	case digital_author_conf.RumP2ZhihuRecallLogic:
	case digital_author_conf.RumP2LawRecallLogic:
		return macro.DigitalAuthorFields
	case stream_chat_default_tab_conf.KbOutSiteRumRecallLogic:
		return macro.ZhidaOutSiteBizTypeFields
	case stream_chat_default_tab_conf.AuthorSearchSelfRecallLogic:
		return macro.ZhidaAuthorFields
	case stream_chat_default_tab_conf.AuthorSearchRecallLogic:
		return macro.ZhidaAuthorFields
	case stream_chat_default_tab_conf.KbEnWikiRumRecallLogic,
		stream_chat_default_tab_conf.KbZhWikiRumRecallLogic:
		return macro.ScienceBizTypeFields
	case stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic,
		stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic:
		return macro.PersonalKnowledgeBaseDocStoreFields
	}
	return []string{}
}
