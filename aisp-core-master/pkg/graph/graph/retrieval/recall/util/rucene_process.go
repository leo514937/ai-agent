package util

import (
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/conf/digital_author_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

var ruceneLogicConditionFuncMap = map[string]func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition{
	digital_author_conf.RuceneP0CustomRecallLogic:                       getDigitalAuthorRuceneP0QueryCondition,
	digital_author_conf.RuceneP2LawRecallLogic:                          getDigitalAuthorRuceneP2QueryCondition,
	stream_chat_default_tab_conf.KbOutSiteRuceneRecallLogic:             getZhidaOutSiteRuceneQueryCondition,
	stream_chat_default_tab_conf.KbZhWikiRuceneRecallLogic:              getZhidaOutSiteRuceneQueryCondition,
	stream_chat_default_tab_conf.KbEnWikiRuceneRecallLogic:              getZhidaOutSiteRuceneQueryCondition,
	stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic: getZhidaPersonalKnowledgeBaseRuceneQueryCondition,
	stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic: getZhidaInternalKnowledgeBaseRuceneQueryCondition,
}

var ruceneLogicGenItemFuncMap = map[string]func(ruceneItem *client.Hit) *entities.Item{
	digital_author_conf.RuceneP0CustomRecallLogic:                       genP0CustomDigitalAuthorItem,
	digital_author_conf.RuceneP2LawRecallLogic:                          genP2LawDigitalAuthorItem,
	stream_chat_default_tab_conf.KbOutSiteRuceneRecallLogic:             genZhidaOutSiteItem,
	stream_chat_default_tab_conf.KbZhWikiRuceneRecallLogic:              genWikiItem,
	stream_chat_default_tab_conf.KbEnWikiRuceneRecallLogic:              genWikiItem,
	stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic: genPersonalKnowledgeBaseItem,
	stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic: genPersonalKnowledgeBaseItem,
}

var digitalAuthorRuceneRecallNameFmt = "Rucene_%s_%s_Recaller"

func getDigitalAuthorRuceneP0QueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	keywords := getDigitalAuthorKeyWords(requestCtx.GetBizContext().GetQueryMerge().GetItemMeta())
	var mustConditions []model.MultiCondition

	// keyword 检索条件
	var keyWordConditions []model.MultiCondition
	for _, keyword := range keywords {
		keyWordConditions = append(keyWordConditions,
			model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.RuceneFieldContentSeg,
					FieldValue:  keyword,
					OperateType: model.OperateTypeEq,
				},
			})
	}
	// authorId 检索条件
	authorIdConditions := []model.MultiCondition{
		{Condition: &model.Condition{
			FieldName:   macro.RuceneFieldAuthorId,
			FieldValue:  requestCtx.GetBizContext().AuthorInfo().GetMemberId(),
			OperateType: model.OperateTypeEq,
		}},
	}

	mustConditions = append(mustConditions, keyWordConditions...)
	mustConditions = append(mustConditions, authorIdConditions...)

	// 检查必要条件
	if len(mustConditions) == 0 {
		return nil
	}

	result := &model.MultiCondition{
		Musts: mustConditions,
	}
	return []*model.MultiCondition{result}
}

func getDigitalAuthorRuceneP2QueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	keywords := getDigitalAuthorKeyWords(requestCtx.GetBizContext().GetQueryMerge().GetItemMeta())
	var mustConditions []model.MultiCondition

	// keyword 检索条件
	var keyWordConditions []model.MultiCondition
	for _, keyword := range keywords {
		keyWordConditions = append(keyWordConditions,
			model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.RuceneFieldContentSeg,
					FieldValue:  keyword,
					OperateType: model.OperateTypeEq,
				},
			})
	}

	mustConditions = append(mustConditions, keyWordConditions...)

	// 检查必要条件
	if len(mustConditions) == 0 {
		return nil
	}

	result := &model.MultiCondition{
		Musts: mustConditions,
	}
	return []*model.MultiCondition{result}
}

func getDigitalAuthorKeyWords(itemMeta *model.ItemMeta) []string {
	var keywords []string
	var maxLen = 3
	for _, queryTerm := range itemMeta.QuKeywords {
		if queryTerm.IsMust {
			keywords = append(keywords, queryTerm.GetText())
		}
		if len(keywords) == maxLen {
			return keywords
		}
	}

	return keywords
}

func getZhidaOutSiteRuceneQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	isMustQuTerms := lo.GroupBy(requestCtx.GetBizContext().GetQueryMerge().ItemMeta.QuKeywords, func(item *query_profile.QpTerm) bool {
		return item.IsMust
	})

	var mustConditions []model.MultiCondition
	var shouldConditions []model.MultiCondition

	for _, quTerm := range isMustQuTerms[true] {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.RuceneFieldContentSeg,
				FieldValue:  quTerm.GetText(),
				OperateType: model.OperateTypeEq,
				Boost:       1.0,
				Weight:      quTerm.GetTermImportance(),
			},
		})
	}
	for _, quTerm := range isMustQuTerms[false] {
		shouldConditions = append(shouldConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.RuceneFieldContentSeg,
				FieldValue:  quTerm.GetText(),
				OperateType: model.OperateTypeEq,
				Boost:       0.0,
				Weight:      quTerm.GetTermImportance(),
			},
		})
	}

	result := &model.MultiCondition{
		Musts:   mustConditions,
		Shoulds: shouldConditions,
	}
	return []*model.MultiCondition{result}
}

func getZhidaPersonalKnowledgeBaseRuceneQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	// 1. 拼接知识库 id、type 查询条件
	finalConditions := getZhidaKBRuceneQueryCondition(requestCtx)
	if len(finalConditions) == 0 {
		return nil
	}

	quKeys := requestCtx.GetBizContext().GetQueryMerge().ItemMeta.QuKeywords
	if len(quKeys) == 0 {
		return nil
	}

	isMustQuTerms := lo.GroupBy(quKeys, func(item *query_profile.QpTerm) bool {
		return item.IsMust
	})

	for _, finalCondition := range finalConditions {
		// 2. 拼接 分词 查询条件
		var mustConditions []model.MultiCondition
		var shouldConditions []model.MultiCondition

		for _, quTerm := range isMustQuTerms[true] {
			mustConditions = append(mustConditions, model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseContentFieldName,
					FieldValue:  quTerm.GetText(),
					OperateType: model.OperateTypeEq,
					Boost:       1.0,
					Weight:      quTerm.GetTermImportance(),
				},
			})
		}
		for _, quTerm := range isMustQuTerms[false] {
			shouldConditions = append(shouldConditions, model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseTitleFieldName,
					FieldValue:  quTerm.GetText(),
					OperateType: model.OperateTypeEq,
					Boost:       0.0,
					Weight:      quTerm.GetTermImportance(),
				},
			})
		}
		quCondition := model.MultiCondition{
			Musts:   mustConditions,
			Shoulds: shouldConditions,
		}
		finalCondition.Musts = append(finalCondition.Musts, quCondition)
	}

	return finalConditions
}

func getZhidaKBRuceneQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	var finalConditions []*model.MultiCondition

	// 1.勾选个人知识库大类，且非挂载态，检索范围为 memberId 的整个知识库
	hasUniversalPersonalKnowledgeBase := lo.Contains(requestCtx.GetBizContext().GetKnowledgeBases(), proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE)
	if hasUniversalPersonalKnowledgeBase {
		finalConditions = append(finalConditions, &model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseMemberIdFieldName,
				FieldValue:  requestCtx.GetBizContext().MemberId(),
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// 2.用户挂载的个人知识库，包括当前挂载和历史挂载，包括挂载大类 type 和挂载具体的 id+type
	personalKnowledgeBaseList := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	personalKnowledgeBaseList = append(personalKnowledgeBaseList, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)
	if len(personalKnowledgeBaseList) == 0 {
		personalKnowledgeBaseList = append(personalKnowledgeBaseList, requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountBases()...)
	}
	var idTypeShouldCondition []model.MultiCondition

	for _, personalKnowledgeBase := range personalKnowledgeBaseList {
		if personalKnowledgeBase.GetKnowledgeBaseId() != 0 && personalKnowledgeBase.GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED {
			// 2.1 勾选了个人知识库具体的 id+type，如收藏夹 id1、订阅知识库 id2，则检索 子类类型 + 子类 id
			idTypeMustCondition := []model.MultiCondition{
				{Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
					FieldValue:  personalKnowledgeBase.GetKnowledgeBaseType().String(),
					OperateType: model.OperateTypeEq,
				}},
				{Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
					FieldValue:  personalKnowledgeBase.GetKnowledgeBaseId(),
					OperateType: model.OperateTypeEq,
				}},
			}
			// 为避免挂载过多，进行 limit 限制，10个以内分别召回，10个以上混合召回
			if len(finalConditions) < 10 {
				finalConditions = append(finalConditions, &model.MultiCondition{
					Musts: idTypeMustCondition,
				})
			} else {
				idTypeShouldCondition = append(idTypeShouldCondition, model.MultiCondition{
					Musts: idTypeMustCondition,
				})
			}

		} else if personalKnowledgeBase.GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED &&
			(personalKnowledgeBase.GetVisibility() == proto.KnowledgeBaseVisibility_UNDEFINED_VISIBILITY || personalKnowledgeBase.GetVisibility() == proto.KnowledgeBaseVisibility_PRIVATE) {
			// 2.2 勾选了个人知识库子类，如收藏、rss源，则检索 memberId + 子类类型
			memberTypeMustCondition := []model.MultiCondition{
				{Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
					FieldValue:  personalKnowledgeBase.GetKnowledgeBaseType().String(),
					OperateType: model.OperateTypeEq,
				}},
				{Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseMemberIdFieldName,
					FieldValue:  requestCtx.GetBizContext().MemberId(),
					OperateType: model.OperateTypeEq,
				}},
			}
			finalConditions = append(finalConditions, &model.MultiCondition{
				Musts: memberTypeMustCondition,
			})
		} else if personalKnowledgeBase.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_FEATURE || personalKnowledgeBase.GetVisibility() == proto.KnowledgeBaseVisibility_PUBLIC_ONLY {
			// 2.3 勾选公共知识库所有，则检索可见性
			finalConditions = append(finalConditions, &model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseVisibilityFieldName,
					FieldValue:  personalKnowledgeBase.GetVisibility().String(),
					OperateType: model.OperateTypeEq,
				},
			})
		}
	}

	if len(idTypeShouldCondition) > 0 {
		finalConditions = append(finalConditions, &model.MultiCondition{
			Shoulds: idTypeShouldCondition,
		})
	}

	return finalConditions
}

func getZhidaInternalKnowledgeBaseRuceneQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	// 1. 拼接知识库 id、type 查询条件
	finalCondition := getZhidaInternalKBRuceneQueryCondition(requestCtx)
	if finalCondition == nil {
		return nil
	}
	// 2. 拼接 分词 查询条件
	var qpShouldConditions []model.MultiCondition
	isMustQuTerms := lo.GroupBy(requestCtx.GetBizContext().GetQueryMerge().ItemMeta.QuKeywords, func(item *query_profile.QpTerm) bool {
		return item.IsMust
	})
	for _, quTerm := range isMustQuTerms[true] {
		qpShouldConditions = append(qpShouldConditions, []model.MultiCondition{
			{Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseTitleFieldName,
				FieldValue:  quTerm.GetText(),
				OperateType: model.OperateTypeEq,
				Boost:       1.2,
				Weight:      quTerm.GetTermImportance(),
			}},
			{Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseAbstractFieldName,
				FieldValue:  quTerm.GetText(),
				OperateType: model.OperateTypeEq,
				Boost:       1.1,
				Weight:      quTerm.GetTermImportance(),
			}},
			{Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseContentFieldName,
				FieldValue:  quTerm.GetText(),
				OperateType: model.OperateTypeEq,
				Boost:       1.0,
				Weight:      quTerm.GetTermImportance(),
			}},
		}...)
	}
	// 3. 如果有标签，拼接标签查询条件
	var tagShouldConditions []model.MultiCondition
	for _, tag := range requestCtx.GetBizContext().GetQueryTags() {
		tagShouldConditions = append(tagShouldConditions, []model.MultiCondition{
			{Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseTagsRuceneFieldName,
				FieldValue:  tag,
				OperateType: model.OperateTypeEq,
				Boost:       1.0,
			}},
		}...)
	}

	quCondition := model.MultiCondition{
		Shoulds: qpShouldConditions,
	}
	tagCondition := model.MultiCondition{
		Shoulds: tagShouldConditions,
	}
	finalCondition.Musts = append(finalCondition.Musts, quCondition, tagCondition)

	return []*model.MultiCondition{finalCondition}
}

func getZhidaInternalKBRuceneQueryCondition(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) *model.MultiCondition {
	finalCondition := model.MultiCondition{}

	// 用户挂载的个人知识库，只包括当前挂载，包括挂载具体的 id+type
	internalKnowledgeBaseList := requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()
	internalKnowledgeBaseList = append(internalKnowledgeBaseList, requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases()...)
	internalKnowledgeBaseList = lo.Filter(internalKnowledgeBaseList, func(kb *proto.PersonalKnowledgeBase, _ int) bool {
		return kb.KnowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_INTERNAL
	})

	// 无知识库勾选，返回 nil
	if len(internalKnowledgeBaseList) == 0 {
		return nil
	}

	idTypeShouldCondition := model.MultiCondition{}
	for _, personalKnowledgeBase := range internalKnowledgeBaseList {
		idTypeMustCondition := model.MultiCondition{}
		tmpMustConditions := []model.MultiCondition{
			{Condition: &model.Condition{
				FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
				FieldValue:  personalKnowledgeBase.GetKnowledgeBaseType().String(),
				OperateType: model.OperateTypeEq,
			}},
		}
		if personalKnowledgeBase.GetKnowledgeBaseId() >= 0 {
			tmpMustConditions = append(tmpMustConditions, model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
					FieldValue:  personalKnowledgeBase.GetKnowledgeBaseId(),
					OperateType: model.OperateTypeEq,
				},
			})
		}
		idTypeMustCondition.Musts = tmpMustConditions
		idTypeShouldCondition.Shoulds = append(idTypeShouldCondition.Shoulds, idTypeMustCondition)
	}
	finalCondition.Musts = append(finalCondition.Musts, idTypeShouldCondition)

	return &finalCondition
}

func genP0CustomDigitalAuthorItem(ruceneItem *client.Hit) *entities.Item {
	item := genDigitalAuthorRuceneItem(ruceneItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel0
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceAuthorCustom
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRuceneRecallNameFmt, conf.IndexLevel0, conf.IndexSourceAuthorCustom)
	return item
}
func genP2LawDigitalAuthorItem(ruceneItem *client.Hit) *entities.Item {
	item := genDigitalAuthorRuceneItem(ruceneItem)
	item.GetItemMeta().GetRecallSourceInfo().IndexLevel = conf.IndexLevel2
	item.GetItemMeta().GetRecallSourceInfo().IndexSource = conf.IndexSourceLaw
	item.GetItemMeta().GetRecallSourceInfo().RecallerName = fmt.Sprintf(digitalAuthorRuceneRecallNameFmt, conf.IndexLevel2, conf.IndexSourceLaw)

	return item
}

func genDigitalAuthorRuceneItem(ruceneItem *client.Hit) *entities.Item {
	indexDocUniqueId := util.SafeString2Int64(ruceneItem.Id, 0)
	authorId := ruceneItem.StoreFields.GetInt64(macro.RuceneFieldAuthorId)
	docId := ruceneItem.StoreFields.GetInt64(macro.RuceneFieldDocIdCopy)
	docTypeStr := ruceneItem.StoreFields.GetString(macro.RuceneFieldDocType)
	docType := content.DocType_Type(content.DocType_Type_value[docTypeStr])
	enable := ruceneItem.StoreFields.GetInt64(macro.RuceneFieldEnable)
	contentText := ruceneItem.StoreFields.GetString(macro.RuceneFieldContent)
	title := ruceneItem.StoreFields.GetString(macro.RuceneFieldTitle)
	bayesFirstName := ruceneItem.StoreFields.GetString(macro.RuceneFieldBayesFirstName)

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallDoc,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 contentText,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          docType,
			AuthorId:         authorId,
			Title:            title,
			Content:          contentText,
			BayesFirstName:   bayesFirstName,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore: float64(ruceneItem.Score),
				Enable:      enable,
			},
		},
	}

	return item
}

func genZhidaOutSiteItem(ruceneItem *client.Hit) *entities.Item {
	indexDocUniqueId := util.SafeString2Int64(ruceneItem.Id, 0)
	title := ruceneItem.StoreFields.GetString(macro.ZhidaTitle)
	contentText := ruceneItem.StoreFields.GetString(macro.ZhidaContent)
	domain := ruceneItem.StoreFields.GetString(macro.ZhidaDomain)
	linkUrl := ruceneItem.StoreFields.GetString(macro.ZhidaLinkUrl)
	source := ruceneItem.StoreFields.GetString(macro.ZhidaSource)
	sourceType := ruceneItem.StoreFields.GetString(macro.ZhidaSourceType)
	publishTime := ruceneItem.StoreFields.GetInt64(macro.ZhidaPublishTimeSecond)

	if utf8.RuneCountInString(contentText) < 20 || len(title) == 0 || !strings.HasPrefix(linkUrl, "http") {
		return nil
	}

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
			DocType:          content.DocType_Link,
			PublishedTime:    publishTime,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore:       float64(ruceneItem.Score),
				CrawlerSource:     source,
				CrawlerSourceType: sourceType,
			},
		},
	}

	return item
}

func genWikiItem(ruceneItem *client.Hit) *entities.Item {
	indexDocUniqueId := util.SafeString2Int64(ruceneItem.Id, 0)
	docId := ruceneItem.StoreFields.GetInt64(macro.ScienceDocId)
	title := ruceneItem.StoreFields.GetString(macro.ScienceTitle)
	contentText := ruceneItem.StoreFields.GetString(macro.ScienceContent)
	linkUrl := ruceneItem.StoreFields.GetString(macro.ScienceUrl)

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 contentText,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          content.DocType_Text,
			Title:            title,
			Content:          contentText,
			Abstract:         util.UnicodeSubstr(contentText, 0, macro.CardAbstractLimit),
			Url:              linkUrl,
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore: float64(ruceneItem.Score),
			},
		},
	}

	return item
}

func genPersonalKnowledgeBaseItem(ruceneItem *client.Hit) *entities.Item {
	indexDocUniqueId := util.SafeString2Int64(ruceneItem.Id, 0)
	docId := ruceneItem.StoreFields.GetInt64(macro.PersonalKnowledgeBaseDocIdFieldName)
	docType := ruceneItem.StoreFields.GetString(macro.PersonalKnowledgeBaseDocTypeFieldName)
	baseId := ruceneItem.StoreFields.GetInt64(macro.PersonalKnowledgeBaseKnowledgeBaseIdFieldName)
	baseName := ruceneItem.StoreFields.GetString(macro.PersonalKnowledgeBaseKnowledgeBaseNameFieldName)
	baseType := ruceneItem.StoreFields.GetString(macro.PersonalKnowledgeBaseKnowledgeBaseTypeFieldName)
	memberId := ruceneItem.StoreFields.GetInt64(macro.PersonalKnowledgeBaseMemberIdFieldName)
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			IndexDocUniqueId: indexDocUniqueId,
			DocId:            docId,
			DocType:          content.DocType_Type(content.DocType_Type_value[docType]),
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallScore:                float64(ruceneItem.Score),
				KnowledgeBaseId:            baseId,
				KnowledgeBaseName:          baseName,
				PersonalKnowledgeBaseType:  proto.PersonalKnowledgeBaseType(proto.PersonalKnowledgeBaseType_value[baseType]),
				KnowledgeBaseCreator:       memberId,
				UniversalKnowledgeBaseType: enums.KnowledgeBaseTypePersonal,
			},
		},
	}
	return item
}

func GetRuceneQueryCondition(logicName string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*model.MultiCondition {
	if f := ruceneLogicConditionFuncMap[logicName]; f != nil {
		return f(requestCtx)
	}
	return nil
}

func GenRuceneItem(logicName string, ruceneItem *client.Hit) *entities.Item {
	if f := ruceneLogicGenItemFuncMap[logicName]; f != nil {
		return f(ruceneItem)
	}
	return nil
}
