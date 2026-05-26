package generate

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"golang.org/x/exp/slices"
)

const defaultContextAssistantText = "好的，我会参考对话历史和相关的知乎社区讨论来回答您的问题。"

type MessageHandler struct {
	msgFuncMap                 map[conf.MessageHandlerType]func(isUseRecall bool) []*dto.ChatRequestMessage
	messageConfigArr           []conf.ChatMsgConfig
	recallItemList             []*data_frame.ItemData[entities.Item]
	memberId                   int64
	query                      string
	queryMerge                 string
	answer                     string
	searchSourceInfoMap        map[string][]*req_macro.SourceInfo
	historyDialogue            []*message.DialogueWrapper
	queryDefinition            *entities.QueryDefinition
	authorInfo                 *entities.User
	promptService              prompt.PromptMapperService
	knowledgeBaseInfo          []*model.KnowledgeBaseInfo
	authorMetaInfo             []*model.AuthorInfo
	universalKnowledgeBaseInfo []*model.UniversalKnowledgeBaseInfo
	mountRefs                  *entities.RefMountData
	promptApolloNamespace      string
	brandDescription           string
	contextLengthLimit         int64
	extraContextLength         int
	maxToken                   int32
	isOutputSystem             bool
	promptInputByUseRecall     *model.PromptInput
	promptInputByNotUseRecall  *model.PromptInput
	isPureDocs                 bool
	chatModelType              proto.ChatModel
	defModelName               string
}

func NewMessageHandler(
	messageConfigArr []conf.ChatMsgConfig,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	itemList []*data_frame.ItemData[entities.Item], contextLengthLimit int64, extraContextLength int, maxToken int32, isOutputSystem bool) *MessageHandler {

	// 原始query
	query := requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent
	// query merge
	queryMerge := query
	queryMergeItem := requestCtx.GetBizContext().GetQueryMerge()
	if queryMergeItem != nil {
		queryMerge = queryMergeItem.Text
	}

	// Answer
	answer := ""
	if requestCtx.GetBizContext().GetCurrentDialogue().Answer != nil {
		answer = util.RemoveTags(requestCtx.GetBizContext().GetCurrentDialogue().Answer.MessageContent)
	}

	mountRefs := requestCtx.GetBizContext().GetCurrReferenceMount()
	if mountRefs.GetMountLength() == 0 {
		mountRefs = requestCtx.GetBizContext().GetHistoryReferenceMount()
	}

	obj := &MessageHandler{
		messageConfigArr:           messageConfigArr,
		query:                      query,
		queryMerge:                 queryMerge,
		answer:                     answer,
		memberId:                   requestCtx.GetBizContext().MemberId(),
		historyDialogue:            requestCtx.GetBizContext().GetHistoryDialogue(),
		queryDefinition:            requestCtx.GetBizContext().GetQueryDefinition(),
		authorInfo:                 requestCtx.GetBizContext().AuthorInfo(),
		knowledgeBaseInfo:          requestCtx.GetBizContext().GetKnowledgeBaseInfo(),
		authorMetaInfo:             requestCtx.GetBizContext().GetAuthorMetaInfo(),
		universalKnowledgeBaseInfo: requestCtx.GetBizContext().GetUniversalKnowledgeBaseInfo(),
		mountRefs:                  mountRefs,
		promptService:              prompt.DefaultPromptMapperService,
		contextLengthLimit:         contextLengthLimit,
		extraContextLength:         zrecUtil.Max(0, extraContextLength),
		maxToken:                   maxToken,
		isOutputSystem:             isOutputSystem,
		searchSourceInfoMap:        requestCtx.GetBizContext().GetSearchSourceMap(),
		isPureDocs:                 requestCtx.GetBizContext().IsMountPureDoc(),
		chatModelType:              requestCtx.GetBizContext().GetCustomChatModel(),
		defModelName:               "知海图",
	}
	obj.recallItemList = obj.getRecallItem(itemList)

	// 品牌信息
	if requestCtx.GetBizContext().GetExtraInfo() != nil && len(requestCtx.GetBizContext().GetExtraInfo().GetBrandName()) != 0 {
		brand := requestCtx.GetBizContext().GetExtraInfo().GetBrandName()[0]
		var brandDescMap = make(map[string]string)
		config.MustGetJsonByNamespace(macro.ZplusApolloNamespace, macro.BrandDescriptionConfigName, &brandDescMap)
		obj.brandDescription = brandDescMap[brand]
		if obj.brandDescription == "" {
			obj.brandDescription = brandDescMap["default"]
		}
	}

	if requestCtx.GetBizContext().GetBizType() == proto.ChatType_ZPLUS_BRAND.String() {
		obj.promptApolloNamespace = prompt.ConfigNamespaceZplus
	} else {
		obj.promptApolloNamespace = prompt.ConfigNamespaceAI
	}

	obj.promptInputByUseRecall = obj.buildPromptInput(true)
	obj.promptInputByNotUseRecall = obj.buildPromptInput(false)
	obj.initMsgFuncMap()
	return obj
}

func (m *MessageHandler) BuildMessages() []*dto.ChatRequestMessage {
	return lo.Filter(m.BuildAllMessages(), func(item *dto.ChatRequestMessage, _ int) bool {
		if m.isOutputSystem {
			return true
		}
		return item.Role != dto.ChatRequestMessageRoleSystem
	})
}

func (m *MessageHandler) BuildAllMessages() []*dto.ChatRequestMessage {
	messages := m.BuildMessagesByConfigArr(m.messageConfigArr)

	// 预先 生成除召回的 message length，如果发现message length 已经超长 则优先砍召回
	// 保障调用模型时 上下文不会超长
	currContextLength := m.getContextLengthFromCustom(messages)
	// 如果 contextLengthLimit <=0 则表示没有默认配置上下文长度 则不处理
	// 2025年03月22日14:51:18 zpc
	if m.contextLengthLimit <= 0 || (currContextLength+int64(m.maxToken)) <= m.contextLengthLimit {
		return messages
	}

	// 计算当前召回知识库长度
	var knowledgeBasesLength int64
	knowledgeBases := m.handleKnowledge()
	for _, knowledgeBase := range knowledgeBases {
		knowledgeBasesLength += int64(util.UnicodeLen(util.GetJSONIgnoreError(knowledgeBase)))
	}
	if knowledgeBasesLength > 0 {
		notUseRecallMessage := m.buildMessagesByConfigArrCustom(m.messageConfigArr, false)
		notUseRecallMessageLength := m.getContextLengthFromCustom(notUseRecallMessage)
		// 重新计算 上下文长度时，无召回长度要加上额外上下文长度（extraContextLength）
		quotaKnowledgeBasesContextLengthLimit := m.contextLengthLimit - (notUseRecallMessageLength + int64(m.extraContextLength) + int64(m.maxToken))
		if quotaKnowledgeBasesContextLengthLimit > 0 {
			quotaKnowledgeBases := util.ChunkArrWithLimitStrLength(knowledgeBases, int(quotaKnowledgeBasesContextLengthLimit), func(item *model.PromptInputKnowledgeBase) string {
				return util.GetJSONIgnoreError(item)
			})

			// 是否兜底
			isFallback := false
			// 补充措施 如果只剩下一个召回 则考虑从内容中截取
			if len(quotaKnowledgeBases) == 0 && int64(util.UnicodeLen(knowledgeBases[0].Text)) > quotaKnowledgeBasesContextLengthLimit {
				knowledgeBases[0].Text = util.UnicodeSubstr(knowledgeBases[0].Text, 0, int(quotaKnowledgeBasesContextLengthLimit))
				quotaKnowledgeBases = append(quotaKnowledgeBases, knowledgeBases[0])
				isFallback = true
			}
			recallItemList := make([]*data_frame.ItemData[entities.Item], 0)
			for _, kb := range quotaKnowledgeBases {
				recallItem := m.recallItemList[kb.RecallIndex]
				if isFallback {
					recallItem.GetBizItem().Text = kb.Text
				}
				recallItemList = append(recallItemList, recallItem)
			}
			m.recallItemList = recallItemList
			m.promptInputByUseRecall = m.buildPromptInput(true)
		}
	}
	messages = m.BuildMessagesByConfigArr(m.messageConfigArr)
	return messages
}

func (m *MessageHandler) BuildMessagesByConfigArr(messageConfigArr []conf.ChatMsgConfig) []*dto.ChatRequestMessage {
	return m.buildMessagesByConfigArrCustom(messageConfigArr, true)
}

func (m *MessageHandler) buildMessagesByConfigArrCustom(messageConfigArr []conf.ChatMsgConfig, isUseRecall bool) []*dto.ChatRequestMessage {
	messages := make([]*dto.ChatRequestMessage, 0)
	for _, cf := range messageConfigArr {
		if msgFunc, isExist := m.msgFuncMap[cf.HandlerType]; isExist {
			messages = append(messages, msgFunc(isUseRecall)...)
		}
	}
	return messages
}

func (m *MessageHandler) getContextLengthFromCustom(messages []*dto.ChatRequestMessage) int64 {
	var messageLength int64
	for _, msg := range messages {
		messageLength += int64(util.UnicodeLen(msg.Content))
	}
	return messageLength
}

func (m *MessageHandler) GetContextLength() int64 {
	return m.getContextLengthFromCustom(m.BuildAllMessages())
}

func (m *MessageHandler) GetContextLengthNotAutoClip() int64 {
	return m.getContextLengthFromCustom(m.BuildMessagesByConfigArr(m.messageConfigArr))
}

func (m *MessageHandler) GetContextLengthIgnoreRecall() int64 {
	return m.getContextLengthFromCustom(m.buildMessagesByConfigArrCustom(m.messageConfigArr, false))
}

func (m *MessageHandler) GetContextLengthIgnoreSystem() int64 {
	messages := m.BuildAllMessages()
	// 过滤掉 System
	messages = lo.Filter(messages, func(item *dto.ChatRequestMessage, _ int) bool {
		return item.Role != dto.ChatRequestMessageRoleSystem
	})
	return m.getContextLengthFromCustom(messages)
}

func (m *MessageHandler) BuildPrompt(ctx context.Context, promptId string, promptTag string) (string, int, error) {
	return m.BuildPromptByDefPrompt(ctx, promptId, "", promptTag, "")
}

func (m *MessageHandler) BuildPromptByDefPrompt(ctx context.Context, promptId string, defaultPromptTemplate string, promptTag string, nameSpace string) (string, int, error) {
	return m.buildPromptByDefPromptCustom(ctx, promptId, defaultPromptTemplate, promptTag, nameSpace, true)
}

func (m *MessageHandler) buildPromptInput(isUseRecall bool) *model.PromptInput {
	promptInput := &model.PromptInput{
		Query:                     m.query,
		QueryMerge:                m.queryMerge,
		Answer:                    m.answer,
		BrandDescription:          m.brandDescription,
		IsChineseByQueryAndAnswer: util.IsChinese(m.query + m.answer),
		SearchSourceMap:           m.searchSourceInfoMap,
	}

	if m.authorInfo != nil {
		if userMeta := m.authorInfo.UserMeta(); userMeta != nil {
			promptInput.Topic = userMeta.GetFinalSkilledAnswer()
			promptInput.AuthorName = userMeta.GetUserName()
		}
	}

	if m.queryDefinition != nil && m.queryDefinition.Definition != "" {
		promptInput.QueryDefinition = model.QueryDefinition{
			Definition:  m.queryDefinition.Definition,
			DocTitle:    m.queryDefinition.DocTitle,
			DocTypeText: m.queryDefinition.DocTypeText,
		}
	}

	// 处理通用知识库
	systemUniversalKnowledgeBases, userUniversalKnowledgeBases := m.handleKnowledgeType()
	promptInput.SystemUniversalKnowledgeBaseInfo = systemUniversalKnowledgeBases
	promptInput.UserUniversalKnowledgeBaseInfo = userUniversalKnowledgeBases

	// 处理Doc知识库
	knowledgeBases := m.handleKnowledge()
	if isUseRecall && len(knowledgeBases) > 0 {
		promptInput.KnowledgeBase = knowledgeBases
		promptInput.Knowledge = m.mergeKnowledge(knowledgeBases)
		promptInput.FullKnowledge = m.mergeFullKnowledge(knowledgeBases)
	}

	currModelName := m.defModelName
	if modelName, isExistModelName := modelNameMap[m.chatModelType.String()]; isExistModelName {
		currModelName = modelName
	}
	promptInput.ModelName = currModelName
	promptInput.IsPureDocs = m.isPureDocs

	promptInput.KnowledgeBaseInfo = m.knowledgeBaseInfo
	promptInput.AuthorMetaInfo = m.authorMetaInfo
	promptInput.UniversalKnowledgeBaseInfo = m.universalKnowledgeBaseInfo
	return promptInput
}
func (m *MessageHandler) buildPromptByDefPromptCustom(ctx context.Context, promptId string, defaultPromptTemplate string, promptTag string, nameSpace string, isUseRecall bool) (string, int, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "pkg.graph.graph.generate.MessageHandler.buildPromptByDefPromptCustom",
	})

	promptInput := m.promptInputByUseRecall
	if !isUseRecall {
		promptInput = m.promptInputByNotUseRecall
	}

	// load and gen prompt template
	if nameSpace == "" {
		nameSpace = m.promptApolloNamespace
	}
	promptTemplate := m.loadPrompt(ctx, promptId, defaultPromptTemplate, promptTag, m.memberId, nameSpace)
	promptContent, err := model.GenPrompt(promptInput, promptTemplate, promptId)
	if err != nil {
		logger.Errorf(ctx, "build prompt template parse error: %+v", err)
		return promptContent, len(promptInput.KnowledgeBase), err
	}

	return promptContent, len(promptInput.KnowledgeBase), nil
}

func (m *MessageHandler) initMsgFuncMap() {
	// 默认 配置不允许有重复的 type，如果存则默认选择 0 位
	configGroup := lo.GroupBy(m.messageConfigArr, func(config conf.ChatMsgConfig) conf.MessageHandlerType {
		return config.HandlerType
	})

	m.msgFuncMap = map[conf.MessageHandlerType]func(isUseRecall bool) []*dto.ChatRequestMessage{
		conf.MsgElementByElementChatHistory: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByElementChatHistory]; isExistConfig && len(currConfigArr) > 0 {
				// 先根据limit 截取对话历史
				historyDialogue := m.historyDialogue[zrecUtil.Max(0, len(m.historyDialogue)-currConfigArr[0].HistoryLimit):]
				// 再根据内容长度截取
				historyDialogue = util.ChunkArrWithLimitStrLength(historyDialogue, zrecUtil.Max(0, currConfigArr[0].ContentLengthLimit),
					func(item *message.DialogueWrapper) string {
						text := ""
						if item.Query != nil {
							text += item.Query.MessageContent
						}
						if item.Answer != nil {
							text += item.Answer.MessageContent
						}
						return text
					})
				respMessages = append(respMessages, message.HistToChatRequestMessage(historyDialogue)...)
			}
			return respMessages
		},
		conf.MsgElementByElementQuery: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByElementQuery]; isExistConfig && len(currConfigArr) > 0 {
				respMessages = append(respMessages, &dto.ChatRequestMessage{
					Content: m.query,
					Role:    dto.ChatRequestMessageRoleUser,
				})
			}
			return respMessages
		},
		conf.MsgElementByElementCustomQuery: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByElementCustomQuery]; isExistConfig && len(currConfigArr) > 0 {
				buildPrompt, _, buildPromptErr := m.buildPromptByDefPromptCustom(context.TODO(), currConfigArr[0].PromptId, currConfigArr[0].DefaultPromptTemplate, currConfigArr[0].PromptTag, "", isUseRecall)
				if buildPromptErr != nil {
					return respMessages
				}
				respMessages = append(respMessages, &dto.ChatRequestMessage{
					Content: buildPrompt,
					Role:    dto.ChatRequestMessageRoleUser,
				})
			}
			return respMessages
		},
		conf.MsgElementByElementQueryOrQueryDefinition: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByElementQueryOrQueryDefinition]; isExistConfig && len(currConfigArr) > 0 {
				if m.queryDefinition != nil && m.queryDefinition.Definition != "" {
					buildPrompt, _, buildPromptErr := m.buildPromptByDefPromptCustom(context.TODO(), currConfigArr[0].PromptId, currConfigArr[0].DefaultPromptTemplate, currConfigArr[0].PromptTag, "", isUseRecall)
					if buildPromptErr != nil {
						return respMessages
					}
					respMessages = append(respMessages, &dto.ChatRequestMessage{
						Content: buildPrompt,
						Role:    dto.ChatRequestMessageRoleUser,
					})
				} else {
					respMessages = append(respMessages, &dto.ChatRequestMessage{
						Content: m.query,
						Role:    dto.ChatRequestMessageRoleUser,
					})
				}
			}
			return respMessages
		},
		conf.MsgElementByContextAssistantResponse: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByContextAssistantResponse]; isExistConfig && len(currConfigArr) > 0 {
				contextAssistantText := currConfigArr[0].AssistantText
				if contextAssistantText == "" {
					contextAssistantText = defaultContextAssistantText
				}

				respMessages = append(respMessages, &dto.ChatRequestMessage{
					Content: contextAssistantText,
					Role:    dto.ChatRequestMessageRoleAI,
				})
			}
			return respMessages
		},
		conf.MsgElementByKnowledgeContext: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementByKnowledgeContext]; isExistConfig && len(currConfigArr) > 0 {
				buildPrompt, _, buildPromptErr := m.buildPromptByDefPromptCustom(context.TODO(), currConfigArr[0].PromptId, currConfigArr[0].DefaultPromptTemplate, currConfigArr[0].PromptTag, "", isUseRecall)
				if buildPromptErr != nil {
					return respMessages
				}
				respMessages = append(respMessages, &dto.ChatRequestMessage{
					Content: buildPrompt,
					Role:    dto.ChatRequestMessageRoleUser,
				})
			}
			return respMessages
		},
		conf.MsgElementBySystem: func(isUseRecall bool) []*dto.ChatRequestMessage {
			respMessages := make([]*dto.ChatRequestMessage, 0)
			if currConfigArr, isExistConfig := configGroup[conf.MsgElementBySystem]; isExistConfig && len(currConfigArr) > 0 {
				buildPrompt, _, buildPromptErr := m.buildPromptByDefPromptCustom(context.TODO(), currConfigArr[0].PromptId, currConfigArr[0].DefaultPromptTemplate, currConfigArr[0].PromptTag, "", isUseRecall)
				if buildPromptErr != nil {
					return respMessages
				}
				respMessages = append(respMessages, &dto.ChatRequestMessage{
					Content: buildPrompt,
					Role:    dto.ChatRequestMessageRoleSystem,
				})
			}
			return respMessages
		},
	}
}

// getRecallItem 获得召回Item
func (m *MessageHandler) getRecallItem(sourceItem []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	return lo.Filter(sourceItem, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk &&
			item.GetBizItem().GetItemMeta() != nil &&
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used
	})
}

// handleKnowledgeType 处理通用知识库与召回知识库类型
func (m *MessageHandler) handleKnowledgeType() ([]*model.UniversalKnowledgeBaseInfo, []*model.UniversalKnowledgeBaseInfo) {
	personalUniversalBaseMap := make(map[string]*model.UniversalKnowledgeBaseInfo)
	authorUniversalBaseMap := make(map[int64]*model.UniversalKnowledgeBaseInfo)
	otherUniversalBaseMap := make(map[enums.KnowledgeBaseType]*model.UniversalKnowledgeBaseInfo)

	systemUniversalKnowledgeBaseInfo := make([]*model.UniversalKnowledgeBaseInfo, 0)
	userUniversalKnowledgeBaseInfo := make([]*model.UniversalKnowledgeBaseInfo, 0)

	personalUniversalBaseMapKeyFunc := func(personalKnowledgeBaseId int64, personalKnowledgeBaseType proto.PersonalKnowledgeBaseType) string {
		return fmt.Sprintf("%d:%s", personalKnowledgeBaseId, personalKnowledgeBaseType.String())
	}
	personalKnowledgeBaseMap := lo.SliceToMap(m.knowledgeBaseInfo, func(item *model.KnowledgeBaseInfo) (string, *model.KnowledgeBaseInfo) {
		return personalUniversalBaseMapKeyFunc(item.KnowledgeBaseId, item.KnowledgeBaseType), item
	})

	// 处理通用知识库
	for _, universalBaseMeta := range m.universalKnowledgeBaseInfo {
		_, isExist := otherUniversalBaseMap[universalBaseMeta.KnowledgeBaseType]
		if !isExist {
			knowledgeBaseHandler := enums.NewKnowledgeBase(universalBaseMeta.KnowledgeBaseType, universalBaseMeta.KnowledgeBaseName, universalBaseMeta.KnowledgeBaseDescription)
			otherUniversalBaseMap[universalBaseMeta.KnowledgeBaseType] = &model.UniversalKnowledgeBaseInfo{
				KnowledgeBaseType:        universalBaseMeta.KnowledgeBaseType,
				KnowledgeBaseName:        knowledgeBaseHandler.GetFmtName(),
				KnowledgeBaseDescription: knowledgeBaseHandler.GetFmtDesc(),
				Order:                    knowledgeBaseHandler.GetOrder(),
			}
		}
	}
	// 处理挂载用户知识库
	for _, authorMeta := range m.authorMetaInfo {
		_, isExist := authorUniversalBaseMap[authorMeta.MemberId]
		if !isExist {
			kbType := enums.KnowledgeBaseTypeAuthor
			knowledgeBaseHandler := enums.NewKnowledgeBase(kbType, authorMeta.MemberName, authorMeta.MemberDescription)
			authorUniversalBaseMap[authorMeta.MemberId] = &model.UniversalKnowledgeBaseInfo{
				KnowledgeBaseType:        kbType,
				KnowledgeBaseName:        knowledgeBaseHandler.GetFmtName(),
				KnowledgeBaseDescription: knowledgeBaseHandler.GetFmtDesc(),
				Order:                    knowledgeBaseHandler.GetOrder(),
			}
		}
	}

	// 处理知乎个人收藏All、RssAll、收藏、RSS、内部文档
	if otherUniversalBaseMap[enums.KnowledgeBaseTypePersonal] == nil {
		mountBases := m.mountRefs.GetMountBases()
		for _, mountBase := range mountBases {
			key := personalUniversalBaseMapKeyFunc(mountBase.GetKnowledgeBaseId(), mountBase.GetKnowledgeBaseType())
			pKbInfo := personalKnowledgeBaseMap[key]

			var kbType enums.KnowledgeBaseType
			var kbName = ""
			var kbDesc = ""
			switch mountBase.GetKnowledgeBaseType() {
			case proto.PersonalKnowledgeBaseType_PKB_RSS:
				if mountBase.GetKnowledgeBaseId() != 0 {
					if pKbInfo == nil {
						continue
					}
					kbName = pKbInfo.KnowledgeBaseName
					kbDesc = pKbInfo.Description
				}
				kbType = lo.Ternary(mountBase.GetKnowledgeBaseId() == 0, enums.KnowledgeBaseTypeRSSAll, enums.KnowledgeBaseTypeRSS)
			case proto.PersonalKnowledgeBaseType_PKB_FAV:
				if pKbInfo != nil {
					kbName = pKbInfo.KnowledgeBaseName
					kbDesc = pKbInfo.Description
				}
				kbType = lo.Ternary(mountBase.GetKnowledgeBaseId() == 0, enums.KnowledgeBaseTypeZhihuFavAll, enums.KnowledgeBaseTypeZhihuFav)
			default:
				if mountBase.GetKnowledgeBaseId() == 0 || pKbInfo == nil {
					continue
				}
				kbType = enums.KnowledgeBaseTypePersonalFolder
				kbName = pKbInfo.KnowledgeBaseName
				kbDesc = pKbInfo.Description
			}

			_, isExist := personalUniversalBaseMap[key]
			if !isExist {
				knowledgeBaseHandler := enums.NewKnowledgeBase(kbType, kbName, kbDesc)
				personalUniversalBaseMap[key] = &model.UniversalKnowledgeBaseInfo{
					KnowledgeBaseType:        kbType,
					KnowledgeBaseName:        knowledgeBaseHandler.GetFmtName(),
					KnowledgeBaseDescription: knowledgeBaseHandler.GetFmtDesc(),
					Order:                    knowledgeBaseHandler.GetOrder(),
				}
			}
		}
	}

	// 处理召回内容
	for _, item := range m.recallItemList {
		var knowledgeBaseInfo *model.UniversalKnowledgeBaseInfo
		kbType := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseType
		switch kbType {
		case enums.KnowledgeBaseTypePersonal:
			itemPersonalKnowledgeBaseId := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId
			itemPersonalKnowledgeBaseType := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().PersonalKnowledgeBaseType
			if otherUniversalBaseMap[enums.KnowledgeBaseTypePersonal] != nil {
				knowledgeBaseInfo = otherUniversalBaseMap[enums.KnowledgeBaseTypePersonal]
			} else {
				kbKey := personalUniversalBaseMapKeyFunc(itemPersonalKnowledgeBaseId, itemPersonalKnowledgeBaseType)
				knowledgeBaseInfo = personalUniversalBaseMap[kbKey]
				if knowledgeBaseInfo == nil {
					// 如果没查到 则尝试获取下中类 ALL，比如（RSSAll、FavAll）
					kbKey = personalUniversalBaseMapKeyFunc(0, itemPersonalKnowledgeBaseType)
					knowledgeBaseInfo = personalUniversalBaseMap[kbKey]
				}
			}
		case enums.KnowledgeBaseTypeAuthor:
			currAuthorMetaInfo := authorUniversalBaseMap[item.GetBizItem().GetItemMeta().AuthorId]
			if currAuthorMetaInfo != nil {
				knowledgeBaseInfo = currAuthorMetaInfo
			}
		default:
			currOtherUniversalBase := otherUniversalBaseMap[kbType]
			if currOtherUniversalBase != nil {
				knowledgeBaseInfo = currOtherUniversalBase
			}
		}

		if knowledgeBaseInfo != nil {
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseName = knowledgeBaseInfo.KnowledgeBaseName
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseDesc = knowledgeBaseInfo.KnowledgeBaseDescription
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseType = kbType
		}
	}

	for _, universalBase := range otherUniversalBaseMap {
		switch universalBase.KnowledgeBaseType {
		case enums.KnowledgeBaseTypeGlobal, enums.KnowledgeBaseTypeZhihu, enums.KnowledgeBaseTypePaper, enums.KnowledgeBaseTypePersonal:
			systemUniversalKnowledgeBaseInfo = append(systemUniversalKnowledgeBaseInfo, universalBase)
		default:
			userUniversalKnowledgeBaseInfo = append(userUniversalKnowledgeBaseInfo, universalBase)
		}
	}
	for _, universalBase := range personalUniversalBaseMap {
		userUniversalKnowledgeBaseInfo = append(userUniversalKnowledgeBaseInfo, universalBase)
	}
	for _, universalBase := range authorUniversalBaseMap {
		userUniversalKnowledgeBaseInfo = append(userUniversalKnowledgeBaseInfo, universalBase)
	}

	sort.Slice(systemUniversalKnowledgeBaseInfo, func(i, j int) bool {
		return systemUniversalKnowledgeBaseInfo[i].Order < systemUniversalKnowledgeBaseInfo[j].Order
	})
	sort.Slice(userUniversalKnowledgeBaseInfo, func(i, j int) bool {
		return userUniversalKnowledgeBaseInfo[i].Order < userUniversalKnowledgeBaseInfo[j].Order
	})
	return systemUniversalKnowledgeBaseInfo, userUniversalKnowledgeBaseInfo
}

// handleKnowledge 处理知识库召回内容
func (m *MessageHandler) handleKnowledge() []*model.PromptInputKnowledgeBase {
	knowledgeBases := make([]*model.PromptInputKnowledgeBase, 0)
	// 取出知识库召回内容 且是标记为可使用的
	recallItems := m.recallItemList
	if len(recallItems) == 0 {
		return knowledgeBases
	}

	for index, item := range recallItems {
		title := item.GetBizItem().GetItemMeta().Title
		// 如果是answer内容 且标题为空 则去取question的title
		if title == "" && item.GetBizItem().GetItemMeta().DocType == content.DocType_Answer && item.GetBizItem().GetItemMeta().ParentContentInfo != nil {
			title = item.GetBizItem().GetItemMeta().ParentContentInfo.GetTitle()
		}

		url := item.GetBizItem().GetItemMeta().Url
		authorUrl := ""

		var knowledgeType int
		if item.GetBizItem().GetItemMeta().DocType == content.DocType_Answer ||
			item.GetBizItem().GetItemMeta().DocType == content.DocType_Article ||
			item.GetBizItem().GetItemMeta().DocType == content.DocType_Paper {
			knowledgeType = model.KnowledgeBaseTypeZhihuAnswerAndArticleAndPaper
		} else if item.GetBizItem().GetItemMeta().DocType == content.DocType_ZhiDaUserUpload {
			knowledgeType = model.KnowledgeBaseTypeUserUpLoad
		} else if slices.Contains(item.GetBizItem().GetItemMeta().RecallSourceInfo.KbSources, conf.KbSourceAuthorBge) {
			knowledgeType = model.KnowledgeBaseTypeZhihuAuthor
			authorUrl = url
		} else {
			knowledgeType = model.KnowledgeBaseTypeWeb
		}

		docPublishedTimeFormatStr := ""
		contentInfo := item.GetBizItem().GetItemMeta().ContentInfo
		if !(contentInfo != nil && contentInfo.GetBizExtDetail() != nil &&
			contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil &&
			contentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() == "image") && item.GetBizItem().GetItemMeta().PublishedTime > 0 {
			docPublishedTimeFormatStr = time.Unix(item.GetBizItem().GetItemMeta().PublishedTime, 0).Format("2006-01-02")
		}
		tagInfo := item.GetBizItem().GetItemMeta().TagInfo

		knowledgeBase := &model.PromptInputKnowledgeBase{
			RecallIndex:                index,
			DocTitle:                   title,
			Text:                       item.GetBizItem().Text,
			Type:                       knowledgeType,
			AuthorUrl:                  authorUrl,
			Url:                        url,
			DocType:                    m.getKnowledgeDocTypeName(item.GetBizItem().GetItemMeta()),
			IsOutLink:                  item.GetBizItem().GetItemMeta().IsOutLink() || item.GetBizItem().GetItemMeta().DocType == content.DocType_Link,
			DocPublishedTimeFormatStr:  docPublishedTimeFormatStr,
			UniversalKnowledgeBaseName: item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseName,
			UniversalKnowledgeBaseDesc: item.GetBizItem().GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseDesc,
			AnswerProperty:             graphUtil.GetAnswerPropertyTagValue(tagInfo),
		}
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo != nil {
			knowledgeBase.Timeliness = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo.TimelinessScore
			knowledgeBase.RelevanceScore = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo.RelevanceScore
			knowledgeBase.AuthorityScore = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo.AuthorityScore
			knowledgeBase.AuthorityLevel = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo.AuthorityLevel
			knowledgeBase.RelevanceLevel = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ExtraInfo.RelevanceLevel
		}

		knowledgeBases = append(knowledgeBases, knowledgeBase)

	}
	return knowledgeBases
}

func (m *MessageHandler) mergeKnowledge(knowledgeBases []*model.PromptInputKnowledgeBase) string {
	var strBuilder strings.Builder
	for i, text := range knowledgeBases {
		cleanedText := strings.ReplaceAll(text.Text, "\n", "")
		strBuilder.WriteString(fmt.Sprintf("%d. %s\n\n", i+1, cleanedText))
	}
	strBuilder.WriteString("\n\n")
	return strBuilder.String()
}

func (m *MessageHandler) mergeFullKnowledge(knowledgeBases []*model.PromptInputKnowledgeBase) string {
	var strBuilder strings.Builder
	for i, text := range knowledgeBases {
		cleanedText := strings.ReplaceAll(text.Text, "\n", "")
		strBuilder.WriteString(
			fmt.Sprintf("## %d. \n### 发布时间: %s\n### 标题: %s\n### 内容: %s\n\n",
				i+1, text.DocPublishedTimeFormatStr, text.DocTitle, cleanedText))
	}
	return strBuilder.String()
}

// loadPrompt 加载 prompt
func (m *MessageHandler) loadPrompt(ctx context.Context, promptId string, defaultPromptTemplate string, promptTag string, memberID int64, apolloNamespace string) string {
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
	return m.promptService.LoadPromptByApolloNamespace(ctx, promptId, promptTemp, promptTag, memberID, apolloNamespace)
}

// getKnowledgeDocTypeName 获取prompt 执行类型翻译
// 主要用于在拼接prompt时 拼接 <资料 文档类型=知乎回答>...</资料>
func (m *MessageHandler) getKnowledgeDocTypeName(itemMeta *model.ItemMeta) string {
	if itemMeta.DocType == content.DocType_Answer {
		return "知乎回答"
	} else if itemMeta.DocType == content.DocType_Article {
		return "知乎文章"
	} else if itemMeta.DocType == content.DocType_Member {
		return "知乎答主"
	} else if itemMeta.DocType == content.DocType_ZhiDaUserUpload {
		return "用户上传文档"
	} else if itemMeta.DocType == content.DocType_Paper {
		contentInfo := itemMeta.ContentInfo
		if contentInfo != nil && contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
			switch contentInfo.GetBizExtDetail().GetPaperBizExt().GetSource() {
			case paper_biz_ext.PaperPublishSource_WeiPu:
				return "维普论文"
			case paper_biz_ext.PaperPublishSource_Arxiv:
				return "arxiv论文"
			}
		}

	}
	return "网页"
}

var modelNameMap = map[string]string{
	proto.ChatModel_CM_ZHI_HAI_TU.String():   "知海图",
	proto.ChatModel_CM_DEEP_SEEK_R1.String(): "Deepseek-R1",
	proto.ChatModel_CM_QWQ_32B.String():      "QWQ-32B",
}
