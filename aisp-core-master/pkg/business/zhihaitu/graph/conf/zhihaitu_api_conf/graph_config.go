package zhihaitu_api_conf

import (
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	zhihaitu_conf "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
)

const (
	// stage
	RootStage     = "root"
	SecurityStage = "security"
	RetrieveStage = "retrieve"
	GenerateStage = "generate"
	ResponseStage = "response"

	// logic
	UserMessageLogic                     = "userMessage"
	RedLineLogic                         = "redLine"
	FaqLogic                             = "faq"
	QuestionSecurityReviewLogic          = "questionSecurityReview"
	SecurityConditionLogic               = "securityCondition"
	QuestionSecurityReviewConditionLogic = "questionSecurityReviewCondition"
	RetrievalLogic                       = "retrievalLogic"
	RetrievalBing12371Logic              = "retrievalBing12371"
	RetrievalBingGovLogic                = "retrievalBingGov"
	RetrievalBingNewsLogic               = "retrievalBingNews"
	RetrievalBingXinghuanetLogic         = "retrievalBingXinghuanet"
	RetrievalBingCctvLogic               = "retrievalBingCctv"
	RetrievalBingPeopleLogic             = "retrievalBingPeople"
	RetrievalMergeLogic                  = "retrievalMerge"
	QueryPromptLogic                     = "queryPrompt"
	ChatLogic                            = "chat"
	EmptyLogic                           = "empty"
	AnswerSecurityReviewLogic            = "answerSecurityReview"
	Empty1Logic                          = "empty1"
	ResponseLogic                        = macro.ResponseNode
)

var LogicBizConfigMap = map[string]map[string]string{
	QuestionSecurityReviewLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceZhihaituQuery.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeQuery.ToConvert(),
			SceneContextKey:  graph_macro.ZagKeyZhihaituApiSource,
			SetRedLineAnswer: true,
		}.ToJsonString(),
	},
	FaqLogic: {
		conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
		conf.ConfigFaqKey:                 string(conf.ZhihaituFAQ),
		conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String(), conf.FaqMatchTypeFullMatch.String()),
		conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
	},
	SecurityConditionLogic: {
		conf.ConditionExpression: fmt.Sprintf("(%s == nil || %s == \"\") && (%s == nil || %s == \"\")", graph_macro.ZagKeyRedLineAnswer, graph_macro.ZagKeyRedLineAnswer, graph_macro.ZagKeyFaqAnswer, graph_macro.ZagKeyFaqAnswer),
		conf.ConditionIfBranch:   entities.Normal,
		conf.ConditionElseBranch: entities.Break,
	},
	QuestionSecurityReviewConditionLogic: {
		conf.ConditionCondition:  "==",
		conf.ConditionCompareTo:  "true",
		conf.ConditionIfBranch:   entities.Normal,
		conf.ConditionElseBranch: entities.Break,
	},
	RetrievalBing12371Logic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "www.12371.cn",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	RetrievalBingGovLogic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "www.gov.cn",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	RetrievalBingNewsLogic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "www.news.cn",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	RetrievalBingXinghuanetLogic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "www.xinhuanet.com",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	RetrievalBingCctvLogic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "news.cctv.com",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	RetrievalBingPeopleLogic: {
		zhihaitu_conf.ConfigRetrieveQuerySite: "www.people.com.cn",
		zhihaitu_conf.ConfigRetrieveSize:      "2",
	},
	QueryPromptLogic: {
		zhihaitu_conf.ConfigSystemPromptID:        "zhihaitu_system_prompt",
		zhihaitu_conf.ConfigUserPromptID:          "zhihaitu_user_prompt",
		zhihaitu_conf.ConfigKnowledgebasePromptID: "zhihaitu_knowledgebase_prompt",
		zhihaitu_conf.ConfigPromptNameSpace:       "zhihaitu.properties",
	},
	ChatLogic: {
		conf.ConfigModelName:      entities.Qwen24BInstructSft162V2,
		conf.ConfigChatHistoryKey: "false",
	},
	AnswerSecurityReviewLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceZhihaituAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			SceneContextKey:  graph_macro.ZagKeyZhihaituApiSource,
			SetRedLineAnswer: true,
		}.ToJsonString(),
	},
	ResponseLogic: {
		conf.RefuseText: constant.RefuseText,
	},
}

var LogicStaticConfigMap = map[string]map[string]string{
	RedLineLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyRedLineAnswer,
	},
	QuestionSecurityReviewLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQuery),
		conf.ConfigOutputNames: util.JoinNamesToString(graph_macro.ZagKeyQuerySecurityReviewIsAvailable),
	},
	FaqLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyFaqAnswer,
	},
	SecurityConditionLogic: {
		conf.ConfigInputNames: util.JoinNamesToString(graph_macro.ZagKeyRedLineAnswer, graph_macro.ZagKeyFaqAnswer),
	},
	QuestionSecurityReviewConditionLogic: {
		conf.ConfigInputNames: graph_macro.ZagKeyQuerySecurityReviewIsAvailable,
	},
	RetrievalBing12371Logic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBing12371,
	},
	RetrievalBingGovLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBingGov,
	},
	RetrievalBingNewsLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBingNews,
	},
	RetrievalBingXinghuanetLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBingXinhuanet,
	},
	RetrievalBingCctvLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBingCctv,
	},
	RetrievalBingPeopleLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveBingPeople,
	},
	RetrievalMergeLogic: {
		conf.ConfigInputNames: util.JoinNamesToString(zhihaitu_conf.ZagKeyRetrieveBing12371, zhihaitu_conf.ZagKeyRetrieveBingGov,
			zhihaitu_conf.ZagKeyRetrieveBingNews, zhihaitu_conf.ZagKeyRetrieveBingXinhuanet,
			zhihaitu_conf.ZagKeyRetrieveBingCctv, zhihaitu_conf.ZagKeyRetrieveBingPeople),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyRetrieveMergeItems,
	},
	QueryPromptLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQueryText, zhihaitu_conf.ZagKeyRetrieveMergeItems),
		conf.ConfigOutputNames: zhihaitu_conf.ZagKeyPromptMessages,
	},
	ChatLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(zhihaitu_conf.ZagKeyPromptMessages, graph_macro.ZagKeyRespMessageId),
		conf.ConfigOutputNames: graph_macro.ZagKeyChatRespMessage,
	},
	AnswerSecurityReviewLogic: {
		conf.ConfigInputNames:  util.JoinNamesToString(graph_macro.ZagKeyQuery, graph_macro.ZagKeyChatRespMessage, graph_macro.ZagKeyRedLineAnswer, graph_macro.ZagKeyFaqAnswer),
		conf.ConfigOutputNames: util.JoinNamesToString(graph_macro.ZagKeyAnswerSecurityReviewIsAvailable),
	},
	ResponseLogic: {
		conf.ConfigInputNames: util.JoinNamesToString(
			graph_macro.ZagKeyQuerySecurityReviewIsAvailable, graph_macro.ZagKeyAnswerSecurityReviewIsAvailable,
			graph_macro.ZagKeyRedLineAnswer, graph_macro.ZagKeyRespMessageId, graph_macro.ZagKeyChatRespMessage, graph_macro.ZagKeyFaqAnswer),
		conf.ConfigOutputNames: graph_macro.ZagKeyResponse,
	},
}
