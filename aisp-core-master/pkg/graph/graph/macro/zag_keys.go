package macro

// ZagKeyScene 场景 string
const ZagKeyScene = "ZagKeyScene"

// ZagKeyQuery 用户query *model.DialogRecord
const ZagKeyQuery = "ZagKeyQuery"

// ZagKeyQueryText 用户query文本 string
const ZagKeyQueryText = "ZagKeyQueryText"
const ZagKeyChatReqMessages = "ZagKeyChatReqMessages"

// ZagKeyRespMessageId string
const ZagKeyRespMessageId = "ZagKeyRespMessageId"

// ZagKeySessionId string
const ZagKeySessionId = "ZagKeySessionId"

// ZagKeyMemberId int64
const ZagKeyMemberId = "ZagKeyMemberId"

// ZagKeyQueryMessageId string
const ZagKeyQueryMessageId = "ZagKeyQueryMessageId"

// ZagKeyQueryParentMessageId string
const ZagKeyQueryParentMessageId = "ZagKeyQueryParentMessageId"

// ZagKeyChatRespMessage 模型生成结果。类型：*proto.ChatMessage
const ZagKeyChatRespMessage = "ZagKeyChatRespMessage"

// ZagKeyRedLineAnswer 命中红线必答时的回答
const ZagKeyRedLineAnswer = "ZagKeyRedLineAnswer"

// ZagKeyQueryMergeRedLineAnswer queryMerge命中红线必答时的回答
const ZagKeyQueryMergeRedLineAnswer = "ZagKeyQueryMergeRedLineAnswer"

// ZagKeyQuerySecurityReviewIsAvailable query是否通过安全审查，bool类型
const ZagKeyQuerySecurityReviewIsAvailable = "ZagKeyQuerySecurityReviewIsAvailable"

// ZagKeyQueryMergeSecurityReviewIsAvailable queryMerge是否通过安全审查，bool类型
const ZagKeyQueryMergeSecurityReviewIsAvailable = "ZagKeyQuerySecurityReviewIsAvailable"

const ZagKeyAnswerSecurityReviewIsAvailable = "ZagKeyAnswerSecurityReviewIsAvailable"
const ZagKeyIp = "ZagKeyIp"
const ZagKeyUserAgent = "ZagKeyUserAgent"
const ZagKeyZhihaituApiSource = "ZagKeyZhihaituApiSource"

// ZagKeyFaqAnswer faq的回答，string
const ZagKeyFaqAnswer = "ZagKeyFaqAnswer"

// ZagKeyShowRecallIfFaqAnswerPresent 命中faq是否展示召回，bool类型
const ZagKeyShowRecallIfFaqAnswerPresent = "ZagKeyShowRecallIfFaqAnswerPresent"

// ZagKeyQueryMergeFaqAnswer queryMerge faq的回答，string
const ZagKeyQueryMergeFaqAnswer = "ZagKeyQueryMergeFaqAnswer"

// ZagKeyShowRecallIfQueryMergeFaqAnswerPresent queryMerge命中faq是否展示召回，bool类型
const ZagKeyShowRecallIfQueryMergeFaqAnswerPresent = "ZagKeyShowRecallIfQueryMergeFaqAnswerPresent"

// ZagKeyQuerySecurityAllPass query所有安全相关校验是否通过，bool类型
const ZagKeyQuerySecurityAllPass = "ZagKeyQuerySecurityAllPass"

// ZagKeyQueryMergeSecurityAllPass queryMerge所有安全相关校验是否通过，bool类型
const ZagKeyQueryMergeSecurityAllPass = "ZagKeyQueryMergeSecurityAllPass"

// ZagKeyAnswerSecurityPass 安全接口校验answer是否通过，bool类型
const ZagKeyAnswerSecurityPass = "ZagKeyAnswerSecurityPass"

// ZagKeyFirstTokenMs 首token的时间戳 int64
const ZagKeyFirstTokenMs = "ZagKeyFirstTokenMs"

// ZagKeyStreamChatBeginMs stream chat开始的时间戳 int64
const ZagKeyStreamChatBeginMs = "ZagKeyStreamChatBeginMs"

// ZagKeyStreamChatEndMs stream chat结束的时间戳 int64
const ZagKeyStreamChatEndMs = "ZagKeyStreamChatEndMs"

// ZagKeyRecallItemsAfterMergeAndLimit 召回结果经过merge和limit后的结果 []*data_frame.ItemData[entities.Item]
const ZagKeyRecallItemsAfterMergeAndLimit = "ZagKeyRecallItemsAfterMergeAndLimit"

// ZagKeyRelateQueries 生成相关问题 []*data_frame.ItemData[entities.Item]
const ZagKeyRelateQueries = "ZagKeyRelateQueries"

// ZagKeyRecallItemsAfterMerge 召回结果经过merge后的结果 []*data_frame.ItemData[entities.Item]
const ZagKeyRecallItemsAfterMerge = "ZagKeyRecallItemsAfterMerge"

// ZagKeyAuthorItemsAfterMerge 作者召回结果经过merge后的结果 []*data_frame.ItemData[entities.Item]
const ZagKeyAuthorItemsAfterMerge = "ZagKeyAuthorItemsAfterMerge"

// ZagKeyResponse graph的输出，any类型
const ZagKeyResponse = "ZagKeyResponse"
const ZagKeyGeneratedPrompt = "ZagKeyGeneratedPrompt"

// ZagKeyFinalEnd 是否最终执行完，如果有异步节点，异步节点执行完才算执行完。chan bool类型
const ZagKeyFinalEnd = "ZagKeyFinalEnd"

// ZagKeyCurrentQuery 用户当前对话 *message.DialogueWrapper
const ZagKeyCurrentQuery = "ZagKeyCurrentQuery"

// ZagKeyCurrentAnswer 用户当前对话 *message.DialogueWrapper
const ZagKeyCurrentAnswer = "ZagKeyCurrentAnswer"

// ZagKeyHitResponseCache 是否命中response的cache bool
const ZagKeyHitResponseCache = "ZagKeyHitResponseCache"

// ZagKeyDocRoute 专业版 文档路由结果
const ZagKeyDocRoute = "ZagKeyDocRoute"

// ZagKeyRelevantQueries 相关query
const ZagKeyRelevantQueries = "ZagKeyRelevantQueries"

// ZagKeyIsPrefabWord 是否为预置词 bool
const ZagKeyIsPrefabWord = "ZagKeyIsPrefabWord"

// ZagKeyHistoryDialogue 历史对话 []*message.DialogueWrapper
const ZagKeyHistoryDialogue = "ZagKeyHistoryDialogue"

// ZagKeyQueryMergeEmbedding query merge embedding. []float32
const ZagKeyQueryMergeEmbedding = "ZagKeyQueryMergeEmbedding"

// ZagKeyQueryEmbedding author search agent query embedding. []float32
const ZagKeyQueryEmbedding = "ZagKeyQueryEmbedding"

// ZagKeyIntention 意图 string
const ZagKeyIntention = "ZagKeyIntention"

// ZagKeyRelatedWordIsHitCache 相关词是否命中缓存 boolean
const ZagKeyRelatedWordIsHitCache = "ZagKeyRelatedWordIsHitCache"
