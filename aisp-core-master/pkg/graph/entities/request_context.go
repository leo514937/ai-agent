package entities

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-bidding_xg_tools/brandai"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	ai_daily_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources/ab"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type RequestContext struct {
	// 场景(用于路由到不同的图)
	scenes string
	// 接口名称
	api string
	// 业务类型
	bizType string
	// 推荐词请求信息
	suggestQueriesType proto.SuggestQueriesType
	// 相关词附加信息
	docAboutQueriesRequest *proto.DocAboutQueriesRequest
	// 指定文档相关词附加信息
	specifiedDocAboutQueriesRequest []*proto.DocAboutQueriesRequest
	// QueryMerge请求信息
	buildQueryType proto.BuildQueryType
	// 请求信息
	reqInfo *proto.RequestInfo
	// 召回请求信息
	recallRequest *proto.ZhidaRecallRequest
	// Chat场景附加信息
	chatExtraInfo *proto.ChatExtraInfo
	// 请求相关 context 信息
	requestContextInfo RequestContextInfo
	// session
	sessionId int64
	// 请求 memberId
	memberId int64
	// 请求头信息，包含 ip、udid 等信息
	requestHeader *proto.RequestHeader
	// 为支持多实验域增加的字段，在创建 RequestContext 的时候进行赋值，此时还是单线程，后面调用的时候只是读取，因此使用 map 结构，不会产生并发读写的问题
	abContext map[zlab.SceneId]*zlab.ZlabABContext
	// 业务场景自身 context，逐步替代业务自定义 reqInfo 结构体，避免太多太乱
	productContext ProductContext
	// 返回内容
	responseItemList []*Item
	// 创作者信息
	authorInfo *User
	// 历史会话
	historyDialogue []*message.DialogueWrapper
	// 当前用户请求输入message
	requestMessage *proto.ChatMessage
	// 返回 messageId
	respMessageId string
	// 当前会话
	currentDialogue *message.DialogueWrapper
	// Query意图
	intention *proto.Intention
	// QueryMerge
	queryMerge *Item
	// QueryMerge列表
	queryMergeList []*Item
	// 相关性判断
	correlation enums.CorrelationType
	// rag检索召回条数
	ragRecallItems []*Item
	// 算子 tracing 日志，解决并发写入问题
	logicTracing *sync.Map
	// tracing 日志
	tracing *proto.Tracing
	// tracing 中间过程
	middleProcess *proto.TracingMiddleProcess
	// process tracing
	processTracing *ProcessTracing
	// 是否豁免安全，默认false
	IsExemptSecurity bool
	// 是否测试请求
	isTest bool
	// Summary 召回Embedding 分批大小
	summaryRecallEmbeddingBatchSize int
	// Summary 召回ReRank 分批大小
	summaryRecallReRankBatchSize int
	// 是否开启缓存
	isEnableCache bool
	// 是否命中缓存
	isHitCache bool
	// 是否命中不合法请求
	isRequestIllegal bool
	// 附加信息
	extraInfo *proto.ExtraInfo
	// 时效性
	timeliness enums.TimelinessType
	// 配置
	logicConfigMap  map[string]map[string]string
	logicConfigLock sync.RWMutex
	// ab命中情况
	abParam AbParam
	// 跑 case 配置
	runCaseConfig RunCaseConfig
	// 对话风格
	chatStyle proto.ChatStyle
	// 召回内容Id集合 如果不为空 则表示用户在重答阶段使用了指定的召回内容
	// 服务端 默认不感知重答状态，message在持久化，根据messageId 覆盖更新
	recallContentIds []string
	// 召回内容
	recallItems []*Item
	// trafficSourceChatCacheSecTTLMap
	trafficSourceChatCacheSecTTLMap map[string]int
	// queryDefinition 名词解释
	queryDefinition *QueryDefinition
	// 指定文档源
	assignmentDocKnowledgeBase []proto.DocKnowledgeBase
	// 指定文档
	assignmentDocs []*proto.ChatCardProRelevantSource
	// docRouter 专业版 模式下路由
	docRouter DocRouter
	// 指定个人文件夹 RSS、文件夹、知乎收藏
	assignmentPersonalKnowledgeBase []*proto.PersonalKnowledgeBase
	// 直答专业版 数据源类型
	zhiDaProSourceType         enums.ZhiDaProSourceType
	securityZhiDaProSourceType string
	// 品牌ai 外部信息
	brandExternalInfo *brandai.ExtraInfo
	// 当前引用挂载
	currReferenceMount *RefMountData
	// 历史引用挂载
	historyReferenceMount *RefMountData
	// 指定知识库
	knowledgeBases []proto.KnowledgeBaseType
	// 动态Stage配置
	dynamicStageConfig stage_config.GraphStageLogicConfig[RequestContext, User, Item]
	// customModel 用户自定义模型
	customModel proto.ChatModel
	// chatEvent
	chatEvent                 *chat_event.ChatEvent
	chatEvent2ResponseHandler *chat_event.ChatEventResponse
	// 是否挂载纯Doc
	isMountPureDoc bool
	// 是否命中缓存
	hitCacheResp *proto.ChatResponse
	// AI每日精选请求
	playlistRequest *ai_daily_model.QueryPlaylistRequest
	// AI每日精选数据
	playlistData *ai_daily_model.PlayListData
	// 深度搜索 SourceMap
	sourceMap       map[string]*req_macro.SourceInfo
	searchSourceMap map[string][]*req_macro.SourceInfo
	// 深度搜索 context
	deepSearchContext *DeepSearchContext
	// toolInfo 如果当前context 是 function calling 的话 该字段有对应设置
	toolInfo *dto.FunctionCallResult
	// chat messages
	messages []*dto.ChatRequestMessage
}

type DeepSearchContext struct {
	RetrievalType            proto.RetrievalType
	Goal                     string
	Extract                  string
	Queries                  []string     // search模式独有
	Priority                 PriorityType // browse模式独有
	SourcesName              []string
	SourceType               SourceType
	LastRoundItems           []*data_frame.ItemData[Item]
	RenderedReferenceContent string // 渲染后的引用内容
}

type SourceType int

const (
	SourceTypeSpecificDoc SourceType = 1
)

type PriorityType string

const (
	PriorityTypeRecency PriorityType = "recency"
	PriorityTypeBest    PriorityType = "best"
	PriorityTypeRandom  PriorityType = "random"
	PriorityTypeAll     PriorityType = "all"
)

type QueryDefinition struct {
	DocId       int64
	DocTitle    string
	DocType     aiContent.DocType_Type
	DocTypeText string
	Definition  string
}

// RunCaseConfig
// CaseCache 与 UseSessionCache 存在冲突，二者只能生效其一，case优先
type RunCaseConfig struct {
	IsOpen                     bool                         // 是否开启执行 case 模式
	IsBase                     bool                         // 是否 base 执行
	IsSaveSessionCache         bool                         // 是否保存 session 缓存
	IsUseSessionCache          bool                         // 是否使用 session 缓存
	ExpName                    string                       // 实验组名称
	ManualDirectAffectedLogics []string                     // 直接影响算子（手动设定后 会该算子的后继算子产生影响）
	AffectedLogics             []string                     // 所有产生影响的算子，这些算子重新计算，其余算子走缓存
	LogicConfig                map[string]map[string]string // 变更算子的配置
}

type AbParam struct {
	abParamMap                 map[zlab.SceneId][]zlab.ZlabValue
	abParamValue               map[zlab.SceneId]map[string]string
	abParamValueWithoutDefault map[zlab.SceneId]map[string]string
	abParamStrSlice            []string
}

type ProcessTracing struct {
	SecurityTracing chan *proto.SecurityTracing
	Prompt          chan *proto.Prompt
	LlmAnswer       chan *proto.LLMAnswer
	Exp             chan string
	Intention       string
}

// RequestContextInfo 存放真正的请求相关上下文信息
type RequestContextInfo struct {
	// 知识库相关
	knowledgeBaseInfo []*model.KnowledgeBaseInfo
	// 收藏夹大类描述
	favDescription string
	// 通用知识库相关，即知识库大类
	universalKnowledgeBaseInfo []*model.UniversalKnowledgeBaseInfo
	// Agent知识库相关，即知识库大类
	agentUniversalKnowledgeBaseInfo []*model.UniversalKnowledgeBaseInfo
	// 创作者相关
	authorMetaInfo []*model.AuthorInfo
	// 内部请求标签
	queryTags []string
}

func NewRequestContextFromChatRequestAndStageConf(request *proto.ChatRequest, dynamicStageConfig stage_config.GraphStageLogicConfig[RequestContext, User, Item]) *RequestContext {
	requestContext := NewRequestContextFromChatRequest(request, dynamicStageConfig.GetDefaultBizConfigMap())
	requestContext.dynamicStageConfig = dynamicStageConfig
	return requestContext
}

func NewRequestContextFromChatRequest(request *proto.ChatRequest, configMap map[string]map[string]string) *RequestContext {
	respMessageId := request.GetRespMessageId()
	if respMessageId == "" {
		respMessageId = uuid.NewString()
	}
	info := request.GetInfo()
	bizType := request.GetType().String()
	requestMessage := formatRequestMessage(info.GetMessage())
	queryDialog := NewQueryDialogFormQuery(info, bizType)
	if request.GetPrevMessageId() != "" && request.GetPrevMessageId() != "0" {
		queryDialog.MessageGroupId = request.GetPrevMessageId()
	} else {
		queryDialog.MessageGroupId = requestMessage.GetMessageId()
	}

	assignmentDocs := request.GetAssignmentDocs()
	if assignmentDocs != nil && len(assignmentDocs) > 0 {
		for _, assignmentDoc := range assignmentDocs {
			if assignmentDoc.GetDocType() == proto.DocType_UNKNOWN_DOCTYPE {
				continue
			}

			// 通用站外
			if assignmentDoc.GetDocType() == proto.DocType_UNIVERSAL_OFFSITE {
				continue
			}
		}
	}

	// 2024年10月12日15:43:11
	// 根据直达专业版协议 优先获取新版的召回内容，如果为空则尝试进行旧版获取方式兜底
	recallContentIds := getRecallContentIds(request)
	if len(recallContentIds) == 0 {
		recallContentIds = request.GetRecallContentIds()
	}

	// 当前挂载兼容 (尽可能兼容，防止流量误切时 造成业务瘫痪)
	currReferenceMount := NewRefMountData(request.GetCurrReferenceMount())
	if currReferenceMount.GetMountLength() == 0 && len(request.GetAssignmentDocs()) > 0 {
		for _, assignmentDoc := range request.GetAssignmentDocs() {
			docId, docIdErr := cast.ToInt64E(assignmentDoc.GetDocId())
			if docIdErr != nil || docId == 0 {
				continue
			}
			currReferenceMount.PutRefData(&proto.ReferenceMount{
				MountDoc: &proto.DocIdentity{
					DocId:   docId,
					DocType: assignmentDoc.GetDocType(),
				},
			})
		}
	}

	// 知识库兼容 (尽可能兼容，防止流量误切时 造成业务瘫痪)
	knowledgeBases := request.GetKnowledgeBases()
	if len(knowledgeBases) == 0 {
		if request.GetHeader().GetTrafficSource() == proto.TrafficSource_zhida_pro && (len(request.GetAssignmentDocKnowledgeBase()) > 0 || len(request.GetPersonalKnowledgeBase()) > 0) {
			// 兼容专业版
			for _, assignmentDocKnowledgeBase := range request.GetAssignmentDocKnowledgeBase() {
				switch assignmentDocKnowledgeBase {
				case proto.DocKnowledgeBase_KB_CHINESE, proto.DocKnowledgeBase_KB_ENGLISH:
					knowledgeBases = append(knowledgeBases, proto.KnowledgeBaseType_KBT_PAPER)
				default:
					knowledgeBases = append(knowledgeBases, proto.KnowledgeBaseType_KBT_ZHIHU)
				}
			}

			if len(request.GetPersonalKnowledgeBase()) > 0 {
				knowledgeBases = append(knowledgeBases, proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE)
			}
		} else if request.GetHeader().GetTrafficSource() == proto.TrafficSource_zhida && request.GetHeader().GetVersion() != graph_constant.ZhiDaV2Version {
			// 兼容直答V1
			knowledgeBases = append(knowledgeBases, proto.KnowledgeBaseType_KBT_ZHIHU)
			knowledgeBases = append(knowledgeBases, proto.KnowledgeBaseType_KBT_GLOBAL)
		}
	}

	// 兼容 ChatStyle_DEEP_THINKING
	chatModel := request.GetChatModel()
	if chatModel == proto.ChatModel_CM_ZHI_HAI_TU && request.GetChatStyle() == proto.ChatStyle_DEEP_THINKING {
		chatModel = proto.ChatModel_CM_DEEP_SEEK_R1
	}

	requestContext := &RequestContext{
		api:            graph_constant.ApiStreamChat,
		bizType:        bizType,
		reqInfo:        info,
		sessionId:      cast.ToInt64(info.GetSessionId()),
		requestMessage: requestMessage,
		respMessageId:  respMessageId,
		memberId:       info.GetMemberId(),
		requestHeader:  request.GetHeader(),
		currentDialogue: &message.DialogueWrapper{
			Query: queryDialog,
		},
		logicConfigMap:                  configMap,
		chatStyle:                       request.GetChatStyle(),
		recallContentIds:                recallContentIds,
		chatExtraInfo:                   request.GetChatExtraInfo(),
		assignmentDocKnowledgeBase:      lo.Uniq(request.GetAssignmentDocKnowledgeBase()),
		assignmentDocs:                  request.GetAssignmentDocs(),
		assignmentPersonalKnowledgeBase: request.GetPersonalKnowledgeBase(),
		knowledgeBases:                  lo.Uniq(knowledgeBases),
		currReferenceMount:              currReferenceMount,
		historyReferenceMount:           NewRefMountData(request.GetHistoryReferenceMount()),
		customModel:                     chatModel,
	}
	requestContext.initContext()

	// 如果是直答 tab 会话，需要特殊处理
	if proto.ChatType_ZHIDA_TAB == request.GetType() {
		caseConfig := RunCaseConfig{
			IsSaveSessionCache: true,
		}
		// 如果Query 的 GroupMessageId == MessageId 并且 recall_content_ids 不为空 则表述为重答
		// 重答场景下 需要使用召回缓存
		if queryDialog.MessageGroupId == queryDialog.MessageId && len(requestContext.GetRecallContentIds()) > 0 {
			// 重答
			caseConfig.IsUseSessionCache = true
			// 直接影响 rerank v2算子 和 后继的所有算子
			caseConfig.ManualDirectAffectedLogics = []string{"KbRecallChunkAndReRankV2Before"}
		}
		requestContext.SetRunCaseConfig(caseConfig)
	}

	// 如果是 app 版发现 tab，风格固定为深入
	if proto.ChatType_DISCOVER_TAB == request.GetType() {
		requestContext.SetChatStyle(proto.ChatStyle_THOROUGH)
	}

	// 添加 abContext
	requestContext.AddAllZlabABContext()
	return requestContext
}

func NewRequestContextFromChatRequestByBizType(request *proto.ChatRequest, bizType string) *RequestContext {
	respMessageId := request.GetRespMessageId()
	if respMessageId == "" {
		respMessageId = uuid.NewString()
	}

	info := request.GetInfo()
	info.GetMessage()
	requestMessage := formatRequestMessage(info.GetMessage())
	queryDialog := NewQueryDialogFormQuery(info, bizType)
	if request.GetPrevMessageId() != "" && request.GetPrevMessageId() != "0" {
		queryDialog.MessageGroupId = request.GetPrevMessageId()
	} else {
		queryDialog.MessageGroupId = requestMessage.GetMessageId()
	}

	requestContext := &RequestContext{
		api:            graph_constant.ApiStreamChat,
		bizType:        bizType,
		reqInfo:        info,
		sessionId:      cast.ToInt64(info.GetSessionId()),
		requestMessage: requestMessage,
		respMessageId:  respMessageId,
		memberId:       info.GetMemberId(),
		requestHeader:  request.GetHeader(),
		currentDialogue: &message.DialogueWrapper{
			Query: queryDialog,
		},
		chatStyle: request.GetChatStyle(),
	}
	requestContext.initContext()
	return requestContext
}

func NewRequestContextFromSuggestQueriesRequest(request *proto.SuggestQueriesRequest, configMap map[string]map[string]string, isTask bool) *RequestContext {
	info := request.GetInfo()
	bizType := request.GetType().String()
	requestMessage := formatRequestMessage(info.GetMessage())
	queryDialog := NewQueryDialogFormQuery(info, bizType)
	queryDialog.MessageGroupId = requestMessage.GetMessageId()

	requestContext := &RequestContext{
		api:            graph_constant.ApiSuggestQueries,
		bizType:        bizType,
		reqInfo:        info,
		sessionId:      cast.ToInt64(request.GetInfo().GetSessionId()),
		memberId:       request.GetInfo().GetMemberId(),
		requestMessage: requestMessage,
		currentDialogue: &message.DialogueWrapper{
			Query: queryDialog,
		},
		requestHeader:                   request.GetHeader(),
		suggestQueriesType:              request.GetType(),
		docAboutQueriesRequest:          request.GetDocAboutQueriesRequest(),
		specifiedDocAboutQueriesRequest: request.GetSpecifiedDocAboutQueriesRequest(),
		extraInfo:                       request.GetExtraInfo(),
		logicConfigMap:                  configMap,
	}

	// 如果是离线任务 则默认该配置为关闭
	if isTask {
		requestContext.SetLogicConfig("RelatedWordGetCacheLogic", conf.RelatedWordIsUseCache.ToConvert(), cast.ToString(false))
		requestContext.SetLogicConfig("RelatedWordGetCacheLogic", conf.RelatedWordCacheNilIsGenerate.ToConvert(), cast.ToString(true))
	}

	requestContext.initContext()
	requestContext.AddAiRecMemberZlabABContext()
	return requestContext
}

func NewRequestContextFromRecallRequest(request *proto.ZhidaRecallRequest, dynamicStageConfig stage_config.GraphStageLogicConfig[RequestContext, User, Item], productContext ProductContext) *RequestContext {
	info := &proto.RequestInfo{
		Message: &proto.ChatMessage{
			MessageId:   request.GetRecallExtInfo().GetMessageId(),
			TimestampMs: util.TimeUnixMilli(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        request.GetQuery(),
		},
		MemberId: request.GetMemberId(),
	}
	bizType := request.GetRecallExtInfo().GetChatType().String()
	requestMessage := formatRequestMessage(info.GetMessage())

	queryDialog := NewQueryDialogFormQuery(info, bizType)
	queryDialog.MessageGroupId = requestMessage.GetMessageId()

	requestContext := &RequestContext{
		api:            graph_constant.ApiRecall,
		bizType:        bizType,
		reqInfo:        info,
		memberId:       request.GetMemberId(),
		requestMessage: requestMessage,
		requestHeader: &proto.RequestHeader{
			ClientSource:  request.GetRecallExtInfo().GetClientSource(),
			TrafficSource: request.GetRecallExtInfo().GetTrafficSource(),
		},
		knowledgeBases: request.GetRecallExtInfo().GetKnowledgeBases(),
		currReferenceMount: &RefMountData{
			RefDatas: request.GetRecallExtInfo().GetReferenceMount(),
		},
		currentDialogue: &message.DialogueWrapper{
			Query: queryDialog,
		},
		dynamicStageConfig: dynamicStageConfig,
		logicConfigMap:     dynamicStageConfig.GetDefaultBizConfigMap(),
		productContext:     productContext,
	}

	requestContext.initContext()
	requestContext.AddAllZlabABContext()
	return requestContext
}

func NewDeepSearchRequestContextFromRootRequest(request *RequestContext, dynamicStageConfig stage_config.GraphStageLogicConfig[RequestContext, User, Item]) *RequestContext {
	requestContext := &RequestContext{
		api:                graph_constant.ApiDeepSearch,
		bizType:            request.bizType,
		reqInfo:            request.reqInfo,
		memberId:           request.memberId,
		requestMessage:     request.requestMessage,
		requestHeader:      request.requestHeader,
		knowledgeBases:     request.GetKnowledgeBases(),
		currReferenceMount: request.currReferenceMount,
		currentDialogue:    request.currentDialogue,
		dynamicStageConfig: dynamicStageConfig,
		logicConfigMap:     dynamicStageConfig.GetDefaultBizConfigMap(),
		sourceMap:          request.GetSourceMap(),
		searchSourceMap:    request.GetSearchSourceMap(),
		deepSearchContext:  request.GetDeepSearchContext(),
		chatEvent:          request.chatEvent,
		abParam:            request.abParam,
	}

	requestContext.initContext()
	requestContext.AddAllZlabABContext()
	return requestContext
}

func NewRouterChatSubRequestContextFromRootRequest(request *RequestContext, dynamicStageConfig stage_config.GraphStageLogicConfig[RequestContext, User, Item], toolInfo *dto.FunctionCallResult) *RequestContext {
	requestContext := &RequestContext{
		api:                graph_constant.ApiStreamChatSub,
		bizType:            request.bizType,
		reqInfo:            request.reqInfo,
		requestMessage:     request.requestMessage,
		requestHeader:      request.requestHeader,
		memberId:           request.MemberId(),
		respMessageId:      request.RespMessageId(),
		knowledgeBases:     request.GetKnowledgeBases(),
		currReferenceMount: request.GetCurrReferenceMount(),
		currentDialogue:    request.GetCurrentDialogue(),
		historyDialogue:    request.GetHistoryDialogue(),
		dynamicStageConfig: dynamicStageConfig,
		logicConfigMap:     dynamicStageConfig.GetDefaultBizConfigMap(),
		sourceMap:          request.GetSourceMap(),
		searchSourceMap:    request.GetSearchSourceMap(),
		deepSearchContext:  request.GetDeepSearchContext(),
		chatStyle:          request.GetChatStyle(),
		customModel:        request.GetCustomChatModel(),
		toolInfo:           toolInfo,
		messages:           request.GetMessages(),
		chatEvent:          request.GetChatEvent(),
		tracing:            request.Tracing(),
		logicTracing:       request.logicTracing,
		processTracing:     request.ProcessTracing(),
		middleProcess:      request.GetMiddleProcess(),
		abParam:            request.abParam,
	}

	requestContext.initContext()
	requestContext.AddAllZlabABContext()
	return requestContext
}

func NewRequestContextFromBuildQueryRequest(request *proto.BuildQueryRequest, configMap map[string]map[string]string) *RequestContext {
	requestContext := &RequestContext{
		api:            graph_constant.ApiBuildQuery,
		bizType:        "all",
		reqInfo:        request.GetInfo(),
		sessionId:      cast.ToInt64(request.GetInfo().GetSessionId()),
		memberId:       request.GetInfo().GetMemberId(),
		requestMessage: formatRequestMessage(request.GetInfo().GetMessage()),
		buildQueryType: request.GetType(),
		logicConfigMap: configMap,
	}
	requestContext.initContext()
	return requestContext
}

func NewRequestContextForDigitalChat(request *proto.DigitalAuthorRequestInfo, productContext ProductContext, configMap map[string]map[string]string) *RequestContext {
	requestContext := &RequestContext{
		api:            graph_constant.ApiDigitalAuthorChat,
		bizType:        proto.ChatType_DIGITAL_AUTHOR.String(),
		productContext: productContext,
		requestMessage: formatRequestMessage(request.GetMessage()),
		respMessageId:  request.GetRespMessageId(),
		memberId:       cast.ToInt64(request.GetSenderId()),
		requestHeader:  request.GetHeader(),
		authorInfo: &User{
			MemberId: cast.ToInt64(request.GetReceiverId()),
		},
		IsExemptSecurity: request.GetIsExemptSecurity(),
		logicConfigMap:   configMap,
	}
	requestContext.initContext()
	return requestContext
}

func NewRequestContextForZhihaitu(request *proto.ChatRequest, parentMessageId string, historyDialogue []*message.DialogueWrapper, api string, bizTypePostfix string, configMap map[string]map[string]string) *RequestContext {
	bizType := proto.ChatType_ZHIHAITU.String()
	requestMessage := formatRequestMessage(request.GetInfo().GetMessage())
	queryDialog := NewQueryDialogFormQuery(request.GetInfo(), bizType)
	if request.GetPrevMessageId() != "" && request.GetPrevMessageId() != "0" {
		queryDialog.MessageGroupId = request.GetPrevMessageId()
	} else {
		queryDialog.MessageGroupId = requestMessage.GetMessageId()
	}
	requestContext := &RequestContext{
		api:            api,
		bizType:        bizType + bizTypePostfix,
		requestMessage: requestMessage,
		respMessageId:  request.GetRespMessageId(),
		reqInfo:        request.GetInfo(),
		memberId:       cast.ToInt64(request.GetInfo().MemberId),
		currentDialogue: &message.DialogueWrapper{
			Query: queryDialog,
		},
		historyDialogue: historyDialogue,
		logicConfigMap:  configMap,
	}
	requestContext.initContext()
	requestContext.currentDialogue.Query.ParentMessageId = parentMessageId
	return requestContext

}

func NewRequestContextFromAIDailyRequest(request *ai_daily_model.QueryPlaylistRequest) *RequestContext {
	requestContext := &RequestContext{
		api:             graph_constant.ApiAIDailyPlaylist,
		bizType:         "all",
		playlistRequest: &ai_daily_model.QueryPlaylistRequest{},
		playlistData: &ai_daily_model.PlayListData{
			Theme2ThemeSimMap:       make(map[string]float64),
			ViewedQuestionSimMap:    make(map[string]float64),
			Question2QuestionSimMap: make(map[string]float64),
			SecurityRegulateMap:     make(map[string]struct{}),
		},
	}
	requestContext.initContext()
	requestContext.SetPlaylistRequest(request)
	return requestContext
}

// 添加布谷实验平台 ab context - 全
func (r *RequestContext) AddAllZlabABContext() {
	abContext := zlab.NewZlabABContext(ab.ZlabRecommendMemberStategyClient, macro.ZlabSceneIdRecommendMemberStrategyDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	abContextAiGuideWord := zlab.NewZlabABContext(ab.ZlabAiRecMemberStategyClient, macro.ZlabSceneIdAiRecDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	abContextWebStandard := zlab.NewZlabABContext(ab.ZlabWebStandardClient, macro.ZlabSceneIdWebStandardDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	abContextAiGrowth := zlab.NewZlabABContext(ab.ZlabGrowthClient, macro.ZlabSceneIdAiGrowthDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	abContextSearch := zlab.NewZlabABContext(ab.ZlabSearchClient, macro.ZlabSceneIdSearchDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	r.AddABContext(abContext)
	r.AddABContext(abContextAiGuideWord)
	r.AddABContext(abContextWebStandard)
	r.AddABContext(abContextAiGrowth)
	r.AddABContext(abContextSearch)
}

// 添加布谷实验平台 ab context - AI 实验 memberId 分流
func (r *RequestContext) AddAiRecMemberZlabABContext() {
	abContextAiGuideWord := zlab.NewZlabABContext(ab.ZlabAiRecMemberStategyClient, macro.ZlabSceneIdAiRecDomain,
		r.RequestHeader().GetUdid(), uint64(r.MemberId()))
	r.AddABContext(abContextAiGuideWord)
}

const MaxTracingChanSize = 100

// 有一些字段不想后面每次都判断空指针，进行初始化
func (r *RequestContext) initContext() {
	r.scenes = BuildGraphScene(r.api, r.bizType)
	if r.authorInfo == nil {
		r.authorInfo = &User{}
	}
	r.logicTracing = &sync.Map{}
	r.abContext = make(map[zlab.SceneId]*zlab.ZlabABContext)
	if r.tracing == nil {
		r.tracing = &proto.Tracing{
			MemberId:      util.Int64String(r.MemberId()),
			MessageId:     r.RequestMessage().GetMessageId(),
			RespMessageId: r.RespMessageId(),
			Scene:         r.Scenes(),
			ProcessTracing: &proto.ProcessTracing{
				Intention: &proto.Intention{},
			},
		}
	}
	r.middleProcess = &proto.TracingMiddleProcess{}
	r.processTracing = &ProcessTracing{
		SecurityTracing: make(chan *proto.SecurityTracing, MaxTracingChanSize),
		Prompt:          make(chan *proto.Prompt, MaxTracingChanSize),
		LlmAnswer:       make(chan *proto.LLMAnswer, MaxTracingChanSize),
		Exp:             make(chan string, MaxTracingChanSize),
	}
	r.abParam = AbParam{
		abParamMap:                 make(map[zlab.SceneId][]zlab.ZlabValue),
		abParamValue:               make(map[zlab.SceneId]map[string]string),
		abParamValueWithoutDefault: make(map[zlab.SceneId]map[string]string),
		abParamStrSlice:            []string{},
	}

}

func (r *RequestContext) SetMessages(messages []*dto.ChatRequestMessage) {
	r.messages = messages
}

func (r *RequestContext) AddMessages(message *dto.ChatRequestMessage) {
	if message == nil {
		return
	}
	r.messages = append(r.messages, message)
}

func (r *RequestContext) GetMessages() []*dto.ChatRequestMessage {
	return r.messages
}

func (r *RequestContext) GetToolInfo() *dto.FunctionCallResult {
	return r.toolInfo
}

// IsMountPureDoc 由 stage_rerank_config 写入，当前挂载纯文本且无知识库，则为纯文本
func (r *RequestContext) IsMountPureDoc() bool {
	return r.isMountPureDoc
}

func (r *RequestContext) SetMountPureDoc(flag bool) {
	r.isMountPureDoc = flag
}

func (r *RequestContext) GetCustomChatModel() proto.ChatModel {
	return r.customModel
}

func (r *RequestContext) GetDynamicStageConfig() (stage_config.GraphStageLogicConfig[RequestContext, User, Item], bool) {
	if r.dynamicStageConfig == nil {
		return nil, false
	}
	return r.dynamicStageConfig, true
}

func (r *RequestContext) SetZhiDaProSourceType(sourceType enums.ZhiDaProSourceType) {
	r.zhiDaProSourceType = sourceType
}

func (r *RequestContext) GetZhiDaProSourceType() enums.ZhiDaProSourceType {
	return r.zhiDaProSourceType
}

func (r *RequestContext) GetCurrReferenceMount() *RefMountData {
	if r.currReferenceMount == nil {
		return &RefMountData{}
	}
	return r.currReferenceMount
}

func (r *RequestContext) GetHistoryReferenceMount() *RefMountData {
	if r.historyReferenceMount == nil {
		return &RefMountData{}
	}
	return r.historyReferenceMount
}

func (r *RequestContext) GetCurrentAndHistoryReferenceMount() *RefMountData {
	result := &RefMountData{}
	if r.currReferenceMount != nil {
		result.RefDatas = append(result.RefDatas, r.currReferenceMount.RefDatas...)
	}
	if r.historyReferenceMount != nil {
		result.RefDatas = append(result.RefDatas, r.historyReferenceMount.RefDatas...)
	}
	return result
}

func (r *RequestContext) GetKnowledgeBases() []proto.KnowledgeBaseType {
	return r.knowledgeBases
}

func (r *RequestContext) SetSecurityZhiDaProSourceType(sourceType string) {
	r.securityZhiDaProSourceType = sourceType
}

func (r *RequestContext) GetSecurityZhiDaProSourceType() string {
	return r.securityZhiDaProSourceType
}

func (r *RequestContext) SetDocRouter(router DocRouter) {
	r.docRouter = router
}

func (r *RequestContext) GetDocRouter() DocRouter {
	if r.docRouter == "" {
		return KnowledgeBase
	}
	return r.docRouter
}

func (r *RequestContext) GetAssignmentDocKnowledgeBase() []proto.DocKnowledgeBase {
	if r.assignmentDocKnowledgeBase == nil {
		return []proto.DocKnowledgeBase{}
	}
	return r.assignmentDocKnowledgeBase
}

func (r *RequestContext) GetAssignmentPersonalKnowledgeBase() []*proto.PersonalKnowledgeBase {
	if r.assignmentPersonalKnowledgeBase == nil {
		return []*proto.PersonalKnowledgeBase{}
	}
	return r.assignmentPersonalKnowledgeBase
}

func (r *RequestContext) GetAssignmentDocs() []*proto.ChatCardProRelevantSource {
	if r.assignmentDocs == nil {
		return []*proto.ChatCardProRelevantSource{}
	}
	return r.assignmentDocs
}

func (r *RequestContext) GetChatCacheSecTTLByTrafficSource() (int, bool) {
	if r.trafficSourceChatCacheSecTTLMap == nil {
		return 0, false
	}
	ttl, isOk := r.trafficSourceChatCacheSecTTLMap[r.RequestHeader().GetTrafficSource().String()]
	return ttl, isOk
}

func (r *RequestContext) PutChatCacheSecTTL(trafficSource string, secTTL int) {
	if r.trafficSourceChatCacheSecTTLMap == nil {
		r.trafficSourceChatCacheSecTTLMap = map[string]int{}
	}
	r.trafficSourceChatCacheSecTTLMap[trafficSource] = secTTL
}

func (r *RequestContext) GetChatExtraInfo() *proto.ChatExtraInfo {
	if r.chatExtraInfo == nil {
		return &proto.ChatExtraInfo{}
	}
	return r.chatExtraInfo
}

func (r *RequestContext) GetRecallContentIds() []string {
	if r.recallContentIds == nil {
		return []string{}
	}
	return r.recallContentIds
}

func (r *RequestContext) GetTimeliness() enums.TimelinessType {
	return r.timeliness
}
func (r *RequestContext) SetTimeliness(t enums.TimelinessType) {
	r.timeliness = t
}

func (r *RequestContext) GetQueryDefinition() *QueryDefinition {
	return r.queryDefinition
}
func (r *RequestContext) SetQueryDefinition(queryDefinition *QueryDefinition) {
	r.queryDefinition = queryDefinition
}

func (r *RequestContext) GetExtraInfo() *proto.ExtraInfo {
	return r.extraInfo
}

func (r *RequestContext) SetExtraInfo(extraInfo *proto.ExtraInfo) {
	r.extraInfo = extraInfo
}

func (r *RequestContext) GetKnowledgeBaseInfo() []*model.KnowledgeBaseInfo {
	return r.requestContextInfo.knowledgeBaseInfo
}

func (r *RequestContext) SetKnowledgeBaseInfo(knowledgeBaseInfo []*model.KnowledgeBaseInfo) {
	r.requestContextInfo.knowledgeBaseInfo = knowledgeBaseInfo
}

func (r *RequestContext) GetFavDescription() string {
	return r.requestContextInfo.favDescription
}

func (r *RequestContext) SetFavDescription(favDescription string) {
	r.requestContextInfo.favDescription = favDescription
}

func (r *RequestContext) GetUniversalKnowledgeBaseInfo() []*model.UniversalKnowledgeBaseInfo {
	return r.requestContextInfo.universalKnowledgeBaseInfo
}

func (r *RequestContext) SetUniversalKnowledgeBaseInfo(universalKnowledgeBaseInfo []*model.UniversalKnowledgeBaseInfo) {
	r.requestContextInfo.universalKnowledgeBaseInfo = universalKnowledgeBaseInfo
}

func (r *RequestContext) GetAgentUniversalKnowledgeBaseInfo() []*model.UniversalKnowledgeBaseInfo {
	return r.requestContextInfo.agentUniversalKnowledgeBaseInfo
}

func (r *RequestContext) SetAgentUniversalKnowledgeBaseInfo(universalKnowledgeBaseInfo []*model.UniversalKnowledgeBaseInfo) {
	r.requestContextInfo.agentUniversalKnowledgeBaseInfo = universalKnowledgeBaseInfo
}

func (r *RequestContext) GetAuthorMetaInfo() []*model.AuthorInfo {
	return r.requestContextInfo.authorMetaInfo
}

func (r *RequestContext) SetAuthorMetaInfo(authorMetaInfo []*model.AuthorInfo) {
	r.requestContextInfo.authorMetaInfo = authorMetaInfo
}

func (r *RequestContext) GetQueryTags() []string {
	return r.requestContextInfo.queryTags
}

func (r *RequestContext) SetQueryTags(queryTags []string) {
	r.requestContextInfo.queryTags = queryTags
}

// set  brandExternalInfo
func (r *RequestContext) SetBrandExternalInfo(externalInfo *brandai.ExtraInfo) {
	r.brandExternalInfo = externalInfo
}
func (r *RequestContext) GetBrandExternalInfo() *brandai.ExtraInfo {
	return r.brandExternalInfo
}

func (r *RequestContext) SetPlaylistRequest(req *ai_daily_model.QueryPlaylistRequest) {
	r.playlistRequest = req
}
func (r *RequestContext) GetPlaylistRequest() *ai_daily_model.QueryPlaylistRequest {
	return r.playlistRequest
}

func (r *RequestContext) SetPlayListData(data *ai_daily_model.PlayListData) {
	r.playlistData = data
}
func (r *RequestContext) GetPlayListData() *ai_daily_model.PlayListData {
	return r.playlistData
}

func (r *RequestContext) GetSummaryRecallEmbeddingBatchSize() int {
	if r.summaryRecallEmbeddingBatchSize < 1 {
		return 1
	}
	return r.summaryRecallEmbeddingBatchSize
}
func (r *RequestContext) SetSummaryRecallEmbeddingBatchSize(batchSize int) {
	r.summaryRecallEmbeddingBatchSize = batchSize
}

func (r *RequestContext) GetSummaryRecallReRankBatchSize() int {
	if r.summaryRecallReRankBatchSize < 1 {
		return 1
	}
	return r.summaryRecallReRankBatchSize
}
func (r *RequestContext) SetSummaryRecallReRankBatchSize(batchSize int) {
	r.summaryRecallReRankBatchSize = batchSize
}

func (r *RequestContext) GetHitCacheResp() *proto.ChatResponse {
	return r.hitCacheResp
}

func (r *RequestContext) SetHitCacheResp(resp *proto.ChatResponse) {
	r.hitCacheResp = resp
}

func (r *RequestContext) IsHitCache() bool {
	return r.hitCacheResp != nil
}

// IsChineseByQueryAndAnswer 判断当前请求是否是中文请求
func (r *RequestContext) IsChineseByQueryAndAnswer() bool {
	// 原始query
	query := ""
	if r.GetCurrentDialogue().Query != nil {
		query = r.GetCurrentDialogue().Query.MessageContent
	}
	// Answer
	answer := ""
	if r.GetCurrentDialogue().Answer != nil {
		answer = r.GetCurrentDialogue().Answer.MessageContent
	}
	return util.IsChinese(query + answer)
}

func (r *RequestContext) IsRequestIllegal() bool {
	return r.isRequestIllegal
}

func (r *RequestContext) SetRequestIllegal(isRequestIllegal bool) {
	r.isRequestIllegal = isRequestIllegal
}

func (r *RequestContext) IsEnableCache() bool {
	return r.isEnableCache
}

func (r *RequestContext) SetEnableCache(isEnableCache bool) {
	r.isEnableCache = isEnableCache
}

func (r *RequestContext) GetSuggestQueriesType() proto.SuggestQueriesType {
	return r.suggestQueriesType
}

func (r *RequestContext) GetDocAboutQueriesRequest() *proto.DocAboutQueriesRequest {
	return r.docAboutQueriesRequest
}

func (r *RequestContext) GetSpecifiedDocAboutQueriesRequest() []*proto.DocAboutQueriesRequest {
	return r.specifiedDocAboutQueriesRequest
}

func (r *RequestContext) Scenes() string {
	return r.scenes
}

// GetChatSchema 获取当前ChatSchema
func (r *RequestContext) GetChatSchema() enums.ChatSchema {
	// 修改标题&重新生成
	currChatSchema := enums.ChatSchemaByNormal
	if r.GetBizType() == proto.ChatType_ZHIDA_TAB.String() {
		if r.GetCurrentDialogue().Query.MessageGroupId == r.GetCurrentDialogue().Query.MessageId &&
			len(r.GetRecallContentIds()) > 0 {
			// 重答
			currChatSchema = enums.ChatSchemaByReAnswer
		} else if r.GetCurrentDialogue().Query.MessageGroupId != r.GetCurrentDialogue().Query.MessageId &&
			len(r.GetRecallContentIds()) == 0 {
			// 修改标题
			currChatSchema = enums.ChatSchemaByUpdateTitle
		}
	}
	return currChatSchema
}

func (r *RequestContext) RequestInfo() *proto.RequestInfo {
	return r.reqInfo
}

func (r *RequestContext) RequestMessage() *proto.ChatMessage {
	return r.requestMessage
}

func (r *RequestContext) MessageId() string {
	return r.requestMessage.GetMessageId()
}

func (r *RequestContext) ResponseItemList() []*Item {
	return r.responseItemList
}

func (r *RequestContext) SetResponseItemList(responseItemList []*Item) {
	r.responseItemList = responseItemList
}

func (r *RequestContext) LastResponseItem() *Item {
	response := r.responseItemList
	if len(response) == 0 {
		return nil
	}

	return response[len(response)-1]
}

func (r *RequestContext) AppendResponseItem(item *Item) {
	r.responseItemList = append(r.responseItemList, item)
}

func (r *RequestContext) GetSessionId() int64 {
	return r.sessionId
}

func (r *RequestContext) AuthorInfo() *User {
	return r.authorInfo
}

func (r *RequestContext) SetAuthorInfo(authorInfo *User) {
	r.authorInfo = authorInfo
}

// sourceMap get and set
func (r *RequestContext) GetSourceMap() map[string]*req_macro.SourceInfo {
	return r.sourceMap
}

func (r *RequestContext) SetSourceMap(sourceMap map[string]*req_macro.SourceInfo) {
	r.sourceMap = sourceMap
}

func (r *RequestContext) GetSearchSourceMap() map[string][]*req_macro.SourceInfo {
	return r.searchSourceMap
}

func (r *RequestContext) PutSearchSourceMap(source string, sourceInfo *req_macro.SourceInfo) {
	r.searchSourceMap[source] = append(r.searchSourceMap[source], sourceInfo)
}

func (r *RequestContext) SetSearchSourceMap(sourceMap map[string][]*req_macro.SourceInfo) {
	r.searchSourceMap = sourceMap
}

func (r *RequestContext) GetDeepSearchContext() *DeepSearchContext {
	return r.deepSearchContext
}

func (r *RequestContext) SetDeepSearchContext(deepSearchContext *DeepSearchContext) {
	r.deepSearchContext = deepSearchContext
}

func (r *RequestContext) SetIsExemptSecurity(isExemptSecurity bool) {
	r.IsExemptSecurity = isExemptSecurity
}

func (r *RequestContext) GetIsExemptSecurity() bool {
	return r.IsExemptSecurity
}

func (r *RequestContext) ProductContext() ProductContext {
	return r.productContext
}

func (r *RequestContext) SetProductContext(productContext ProductContext) *RequestContext {
	r.productContext = productContext
	return r
}

func (r *RequestContext) RespMessageId() string {
	return r.respMessageId
}

func (r *RequestContext) SetRespMessageId(respMessageId string) *RequestContext {
	r.respMessageId = respMessageId
	return r
}

func (r *RequestContext) MemberId() int64 {
	return r.memberId
}

func (r *RequestContext) RequestHeader() *proto.RequestHeader {
	if r.requestHeader == nil {
		r.requestHeader = &proto.RequestHeader{}
	}
	return r.requestHeader
}

// AddABContext 支持向 flowContext 中一次性添加多个 ab 上下文
func (r *RequestContext) AddABContext(zlabContexts ...*zlab.ZlabABContext) {
	for _, zlabContext := range zlabContexts {
		r.abContext[zlabContext.GetSceneId()] = zlabContext
	}
}

func (r *RequestContext) GetABContext(sceneId zlab.SceneId) *zlab.ZlabABContext {
	if abContext, exist := r.abContext[sceneId]; exist {
		return abContext
	}
	// 不存在将导致获取的所有实验都只返回默认值
	log.Warnf(context.TODO(), "scene %s is wrong or not exist!", sceneId)
	return new(zlab.ZlabABContext)
}

// 设置指定的 ab value，不去调用 ab 平台，仅用于跑 case
func (r *RequestContext) SetAbGivenValue(sceneId zlab.SceneId, abParamMap map[string]string) {
	zlabContext := r.GetABContext(sceneId)
	zlabContext.SetParamsMap(abParamMap)
}

// ===================== 对话消息历史

func (r *RequestContext) SetCorrelation(correlation enums.CorrelationType) {
	r.correlation = correlation
}

func (r *RequestContext) GetCorrelation() enums.CorrelationType {
	return r.correlation
}

func (r *RequestContext) SetQueryMerge(queryMerge *Item) {
	r.queryMerge = queryMerge
}

// GetQueryMerge 获得QueryMerge 结果
func (r *RequestContext) GetQueryMerge() *Item {
	return r.queryMerge
}

// queryMergeList
func (r *RequestContext) AddQueryMergeList(item *Item) {
	if r.queryMergeList == nil {
		r.queryMergeList = []*Item{}
	}
	r.queryMergeList = append(r.queryMergeList, item)
}

// GetQueryMergeList 获得 QueryMerge 的结果列表
func (r *RequestContext) GetQueryMergeList() []*Item {
	if r.queryMergeList == nil {
		return []*Item{}
	}
	return r.queryMergeList
}

// GetQueryMergeText 获得 QueryMerge 的文本内容
func (r *RequestContext) GetQueryMergeText() string {
	if r.queryMerge == nil {
		return ""
	}
	return r.queryMerge.Text
}

func (r *RequestContext) SetIntention(intention *proto.Intention) {
	r.intention = intention
}

// GetIntention 获得当前意图识别结果
func (r *RequestContext) GetIntention() *proto.Intention {
	return r.intention
}

func (r *RequestContext) ProcessTracing() *ProcessTracing {
	return r.processTracing
}

func (r *RequestContext) GetMiddleProcess() *proto.TracingMiddleProcess {
	return r.middleProcess
}

func (r *RequestContext) SetRagRecallItems(ragRecallItems []*Item) {
	r.ragRecallItems = ragRecallItems
}

// RagRecallItems rag索引召回内容
func (r *RequestContext) RagRecallItems() []*Item {
	return r.ragRecallItems
}

// AddLogicTracing 存入算子 tracing，同步 map
func (r *RequestContext) AddLogicTracing(logicName string, result *proto.LogicTracing) {
	r.logicTracing.Store(logicName, result)
}

func (r *RequestContext) GetLogicTracingMap() map[string]*proto.LogicTracing {
	var result = make(map[string]*proto.LogicTracing)
	r.logicTracing.Range(func(key, value interface{}) bool {
		result[key.(string)] = value.(*proto.LogicTracing)
		return true
	})
	return result
}

func (r *RequestContext) Tracing() *proto.Tracing {
	return r.tracing
}

func (r *RequestContext) SetAbParamMap(abParamMap map[zlab.SceneId][]zlab.ZlabValue) {
	r.abParam.abParamMap = abParamMap
}

func (r *RequestContext) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return r.abParam.abParamMap
}

func (r *RequestContext) AddAbParamValue(sceneId zlab.SceneId, abParamKey string, abParamValue string) {
	if _, exist := r.abParam.abParamValue[sceneId]; !exist {
		r.abParam.abParamValue[sceneId] = map[string]string{}
	}
	if _, exist := r.abParam.abParamValue[sceneId][abParamKey]; !exist {
		r.abParam.abParamValue[sceneId][abParamKey] = abParamValue
		r.abParam.abParamStrSlice = append(r.abParam.abParamStrSlice, fmt.Sprintf("%s-%s", abParamKey, abParamValue))
	}

	// 如果命中实验组，并非是默认组或0，则塞到 abParamValueWithoutDefault 里
	if zlabValues, exist := r.abParam.abParamMap[sceneId]; exist {
		for _, zlabValue := range zlabValues {
			if zlabValue.Key == abParamKey {
				if abParamValue != zlabValue.DefaultValue && abParamValue != "0" {
					if _, exist := r.abParam.abParamValueWithoutDefault[sceneId]; !exist {
						r.abParam.abParamValueWithoutDefault[sceneId] = map[string]string{}
					}
					r.abParam.abParamValueWithoutDefault[sceneId][abParamKey] = abParamValue
				}
				break
			}
		}
	}
}

func (r *RequestContext) GetAbParamValue(sceneId zlab.SceneId, abParamKey string) (string, bool) {
	if _, exist := r.abParam.abParamValue[sceneId]; !exist {
		r.abParam.abParamValue[sceneId] = map[string]string{}
	}
	abValue, flag := r.abParam.abParamValue[sceneId][abParamKey]
	return abValue, flag
}

func (r *RequestContext) GetAbParamAllValue() map[zlab.SceneId]map[string]string {
	return r.abParam.abParamValue
}

func (r *RequestContext) GetAbParamAllValueWithoutDefault() map[zlab.SceneId]map[string]string {
	return r.abParam.abParamValueWithoutDefault
}

func (r *RequestContext) GetAbParamAllValueWithoutDefaultFlattened() map[string]string {
	result := make(map[string]string)
	for _, innerMap := range r.abParam.abParamValueWithoutDefault {
		for k, v := range innerMap {
			result[k] = v
		}
	}
	return result
}

func (r *RequestContext) GetAbParamValueStrSlice() []string {
	return r.abParam.abParamStrSlice
}

func (r *RequestContext) GetClientSource() proto.ClientSource {
	return r.RequestHeader().GetClientSource()
}

func (r *RequestContext) GetTrafficSource() proto.TrafficSource {
	return r.RequestHeader().GetTrafficSource()
}

// GetCurrentDialogue 获得 当前会话 的 Query 和 Answer
func (r *RequestContext) GetCurrentDialogue() *message.DialogueWrapper {
	if r.currentDialogue == nil {
		r.currentDialogue = &message.DialogueWrapper{Query: &model.DialogRecord{}, Answer: &model.DialogRecord{}}
	}
	return r.currentDialogue
}

// GetCurrentQueryMergeDialogue 获得 QueryMerge 后的 Query 和 Answer
func (r *RequestContext) GetCurrentQueryMergeDialogue() *message.DialogueWrapper {
	if r.currentDialogue == nil {
		r.currentDialogue = &message.DialogueWrapper{}
	}

	var query = &model.DialogRecord{}
	if r.currentDialogue.Query != nil {
		query = NewQueryDialogFormQuery(
			r.reqInfo,
			r.bizType,
		)

		query.MessageContent = r.GetQueryMergeText()
	}

	return &message.DialogueWrapper{
		Query:  query,
		Answer: r.currentDialogue.Answer,
	}
}

func (r *RequestContext) SetCurrentDialogueByQuery(dialog *model.DialogRecord) {
	dialogue := r.GetCurrentDialogue()
	dialogue.Query = dialog
}

func (r *RequestContext) SetCurrentDialogueByAnswer(dialog *model.DialogRecord) {
	dialogue := r.GetCurrentDialogue()
	dialogue.Answer = dialog
}

func (r *RequestContext) SetHistoryDialogue(historyDialogue []*message.DialogueWrapper) {
	if historyDialogue == nil {
		historyDialogue = []*message.DialogueWrapper{}
		return
	}
	r.historyDialogue = historyDialogue
}

// GetHistoryDialogue 获得所有会话
func (r *RequestContext) GetHistoryDialogue() []*message.DialogueWrapper {
	if r.historyDialogue == nil {
		r.historyDialogue = []*message.DialogueWrapper{}
	}
	return r.historyDialogue
}

// GetRealHistoryDialogue 获得真实的所有会话
func (r *RequestContext) GetRealHistoryDialogue() []*message.DialogueWrapper {
	if r.historyDialogue == nil {
		r.historyDialogue = []*message.DialogueWrapper{}
	}
	realHistory := lo.Filter(r.historyDialogue, func(item *message.DialogueWrapper, index int) bool {
		if item.Query.CreateType == model.DialogCreateTypeTmp.ToConvert() ||
			item.Answer.CreateType == model.DialogCreateTypeTmp.ToConvert() {
			return false
		}
		return true
	})
	return realHistory
}

// GetAllHistoryDialogue 获得所有会话(包含当前会话)
func (r *RequestContext) GetAllHistoryDialogue() []*message.DialogueWrapper {
	return append(r.GetHistoryDialogue(), r.GetCurrentDialogue())
}

// GetAllHistoryDialogueByQueryMerge 获得所有会话(包含当前QueryMerge会话)
func (r *RequestContext) GetAllHistoryDialogueByQueryMerge() []*message.DialogueWrapper {
	return append(r.GetHistoryDialogue(), r.GetCurrentQueryMergeDialogue())
}

func (r *RequestContext) GetApi() string {
	return r.api
}

func (r *RequestContext) GetBizType() string {
	return r.bizType
}

func (r *RequestContext) GetLogicConfigMap() map[string]map[string]string {
	r.logicConfigLock.RLock()
	defer r.logicConfigLock.RUnlock()
	// config 深拷贝 防止外部修改
	resMap := make(map[string]map[string]string)
	for logicName, logicConfig := range r.logicConfigMap {
		resMap[logicName] = make(map[string]string)
		for logicConfigKey, logicConfigValue := range logicConfig {
			resMap[logicName][logicConfigKey] = logicConfigValue
		}
	}
	return resMap
}

func (r *RequestContext) SetLogicConfig(logicName string, configKey string, configValue string) {
	r.logicConfigLock.Lock()
	defer r.logicConfigLock.Unlock()
	_, isExist := r.logicConfigMap[logicName]
	if !isExist {
		r.logicConfigMap[logicName] = make(map[string]string)
	}
	r.logicConfigMap[logicName][configKey] = configValue
}

func (r *RequestContext) SetLogicConfigMap(logicConfigMap map[string]map[string]string) {
	r.logicConfigLock.Lock()
	defer r.logicConfigLock.Unlock()
	// 注意 这里不要直接调用 SetLogicConfig 在go中lock是不可重入锁
	for logicName, logicConfig := range logicConfigMap {
		_, isExist := r.logicConfigMap[logicName]
		if !isExist {
			r.logicConfigMap[logicName] = make(map[string]string)
		}
		for logicConfigKey, logicConfigValue := range logicConfig {
			r.logicConfigMap[logicName][logicConfigKey] = logicConfigValue
		}
	}
}

func (r *RequestContext) GetLogicConfig(logicName string, configName string) string {
	r.logicConfigLock.RLock()
	defer r.logicConfigLock.RUnlock()
	if configMap, exist := r.logicConfigMap[logicName]; exist {
		return configMap[configName]
	}
	return ""
}

func (r *RequestContext) SetRunCaseConfig(runCaseConfig RunCaseConfig) {
	r.runCaseConfig = runCaseConfig
}

func (r *RequestContext) GetRunCaseConfig() RunCaseConfig {
	return r.runCaseConfig
}

func (r *RequestContext) SetRunCaseAffectedLogics(affectedLogics []string) {
	r.runCaseConfig.AffectedLogics = affectedLogics
}

func (r *RequestContext) SetIsTest(isTest bool) {
	r.isTest = isTest
}

func (r *RequestContext) GetIsTest() bool {
	return r.isTest
}

func (r *RequestContext) SetRecallItems(recallItems []*Item) {
	r.recallItems = recallItems
}

func (r *RequestContext) GetRecallItems() []*Item {
	return r.recallItems
}

func (r *RequestContext) ABCommit() {
	// 异步上报
	safe_group.SafeGo(func() error {
		for _, abContext := range r.abContext {
			abContext.Commit()
		}
		return nil
	}, "ab_commit")
}

func (r *RequestContext) GetChatStyle() proto.ChatStyle {
	return r.chatStyle
}

func (r *RequestContext) SetChatStyle(chatStyle proto.ChatStyle) {
	r.chatStyle = chatStyle
}

// NewQueryDialogFormProtoChatRequest 新建Query 消息
func NewQueryDialogFormProtoChatRequest(request *proto.ChatRequest) *model.DialogRecord {

	requestMessage := formatRequestMessage(request.GetInfo().GetMessage())

	return &model.DialogRecord{
		Scene:     request.GetType().String(),
		RoleType:  model.RoleTypeUser.ToConvert(),
		MemberId:  request.GetInfo().GetMemberId(),
		AiId:      macro.DefAiUserAiAndSearchTab,
		SessionId: cast.ToInt64(request.GetInfo().GetSessionId()),
		MessageId: requestMessage.GetMessageId(),
		// 1期 默认都是 Text
		MessageType:    int64(proto.ChatMessageType_TEXT),
		MessageContent: requestMessage.GetText(),
		CreateType:     model.DialogCreateTypeInput.ToConvert(),
		ErrorType:      model.DialogErrorTypeNormal.ToConvert(),
	}
}

func formatRequestMessage(sourceMsg *proto.ChatMessage) *proto.ChatMessage {
	if sourceMsg == nil {
		return &proto.ChatMessage{}
	}
	return &proto.ChatMessage{
		MessageId:   sourceMsg.GetMessageId(),
		TimestampMs: sourceMsg.GetTimestampMs(),
		Type:        sourceMsg.GetType(),
		Text:        strings.TrimSpace(sourceMsg.GetText()),
	}
}

func (r *RequestContext) InitChatEvent(callback func(eventDate *chat_event.EventInfo)) {
	r.chatEvent2ResponseHandler = chat_event.NewChatEventResponse(cast.ToString(r.sessionId), r.respMessageId)
	r.chatEvent = chat_event.NewChatEvent(context.Background(), callback)
}

func (r *RequestContext) GetChatEvent() *chat_event.ChatEvent {
	return r.chatEvent
}

func (r *RequestContext) GetChatEventResponseHandler() *chat_event.ChatEventResponse {
	return r.chatEvent2ResponseHandler
}

// NewQueryDialogFormQuery 新建Query 消息
func NewQueryDialogFormQuery(info *proto.RequestInfo, bizType string) *model.DialogRecord {
	requestMessage := formatRequestMessage(info.GetMessage())

	return &model.DialogRecord{
		Scene:     bizType,
		RoleType:  model.RoleTypeUser.ToConvert(),
		MemberId:  info.GetMemberId(),
		AiId:      macro.DefAiUserAiAndSearchTab,
		SessionId: cast.ToInt64(info.GetSessionId()),
		MessageId: requestMessage.GetMessageId(),
		// 1期 默认都是 Text
		MessageType:    int64(requestMessage.GetType()),
		MessageContent: requestMessage.GetText(),
		RecordAt:       time.Now(),
		CreateType:     model.DialogCreateTypeInput.ToConvert(),
		ErrorType:      model.DialogErrorTypeNormal.ToConvert(),
	}
}

// NewAnswerDialogFormProtoChatRequest 新建Answer 消息
func NewAnswerDialogFormProtoChatRequest(r *RequestContext, messageText string, createType model.DialogCreateType, errorType model.DialogErrorType) *model.DialogRecord {
	requestMessage := formatRequestMessage(r.RequestMessage())

	return &model.DialogRecord{
		Scene:           r.bizType,
		RoleType:        model.RoleTypeAI.ToConvert(),
		MemberId:        r.RequestInfo().GetMemberId(),
		AiId:            macro.DefAiUserAiAndSearchTab,
		SessionId:       cast.ToInt64(r.RequestInfo().GetSessionId()),
		ParentMessageId: requestMessage.GetMessageId(),
		MessageId:       r.respMessageId,
		// 1期 默认都是 Text
		MessageType:    int64(proto.ChatMessageType_TEXT),
		MessageContent: messageText,
		RecordAt:       time.Now(),
		CreateType:     createType.ToConvert(),
		ErrorType:      errorType.ToConvert(),
	}
}

func BuildGraphScene(api string, bizType string) string {
	return api + "." + bizType
}

func getRecallContentIds(request *proto.ChatRequest) []string {
	var recallContentIds []string
	assignmentDocs := request.GetAssignmentDocs()
	if assignmentDocs != nil && len(assignmentDocs) > 0 {
		for _, assignmentDoc := range assignmentDocs {
			if assignmentDoc.GetDocType() == proto.DocType_UNKNOWN_DOCTYPE {
				continue
			}

			// 通用站外
			if assignmentDoc.GetDocType() == proto.DocType_UNIVERSAL_OFFSITE {
				recallContentIds = append(recallContentIds, GetRecallContentId(0, aiContent.DocType_Unknown, assignmentDoc.GetDocId()))
				continue
			}
			// 内容平台
			zhiDaModel, isOk := model.NewContentWithZhiDaDocType(assignmentDoc.GetDocId(), assignmentDoc.GetDocType())
			if !isOk {
				continue
			}
			recallContentIds = append(recallContentIds, GetRecallContentId(zhiDaModel.ContentID, zhiDaModel.GetDocType(), ""))
		}
	}
	return recallContentIds
}

// 深拷贝一份 RequestContext
func (r *RequestContext) DeepCopy() *RequestContext {
	// 创建一个新的 RequestContext 实例
	copy := &RequestContext{}
	copy.initContext()

	// 深拷贝简单类型字段
	copy.scenes = r.scenes
	copy.api = r.api
	copy.bizType = r.bizType
	copy.sessionId = r.sessionId
	copy.memberId = r.memberId
	copy.respMessageId = r.respMessageId
	copy.IsExemptSecurity = r.IsExemptSecurity
	copy.isTest = r.isTest
	copy.summaryRecallEmbeddingBatchSize = r.summaryRecallEmbeddingBatchSize
	copy.summaryRecallReRankBatchSize = r.summaryRecallReRankBatchSize
	copy.isEnableCache = r.isEnableCache
	copy.isHitCache = r.isHitCache
	copy.isRequestIllegal = r.isRequestIllegal
	copy.isMountPureDoc = r.isMountPureDoc
	copy.zhiDaProSourceType = r.zhiDaProSourceType
	copy.securityZhiDaProSourceType = r.securityZhiDaProSourceType

	// 深拷贝复杂类型字段
	copy.suggestQueriesType = r.suggestQueriesType
	copy.chatStyle = r.chatStyle
	copy.timeliness = r.timeliness
	copy.buildQueryType = r.buildQueryType
	copy.correlation = r.correlation

	// 深拷贝字段 export 的结构体
	if r.reqInfo != nil {
		copy.reqInfo = util.DeepCopyByJSONAndReturn(r.reqInfo).(*proto.RequestInfo)
	}
	if r.requestMessage != nil {
		copy.requestMessage = util.DeepCopyByJSONAndReturn(r.requestMessage).(*proto.ChatMessage)
	}
	if r.requestHeader != nil {
		copy.requestHeader = util.DeepCopyByJSONAndReturn(r.requestHeader).(*proto.RequestHeader)
	}
	if r.chatExtraInfo != nil {
		copy.chatExtraInfo = util.DeepCopyByJSONAndReturn(r.chatExtraInfo).(*proto.ChatExtraInfo)
	}
	if r.extraInfo != nil {
		copy.extraInfo = util.DeepCopyByJSONAndReturn(r.extraInfo).(*proto.ExtraInfo)
	}
	if r.intention != nil {
		copy.intention = util.DeepCopyByJSONAndReturn(r.intention).(*proto.Intention)
	}
	if r.tracing != nil {
		copy.tracing = util.DeepCopyByJSONAndReturn(r.tracing).(*proto.Tracing)
	}
	if r.middleProcess != nil {
		copy.middleProcess = util.DeepCopyByJSONAndReturn(r.middleProcess).(*proto.TracingMiddleProcess)
	}
	if r.hitCacheResp != nil {
		copy.hitCacheResp = util.DeepCopyByJSONAndReturn(r.hitCacheResp).(*proto.ChatResponse)
	}
	if r.queryMerge != nil {
		copy.queryMerge = util.DeepCopyByJSONAndReturn(r.queryMerge).(*Item)
	}
	if r.docAboutQueriesRequest != nil {
		copy.docAboutQueriesRequest = util.DeepCopyByJSONAndReturn(r.docAboutQueriesRequest).(*proto.DocAboutQueriesRequest)
	}

	// 深拷贝字段私有的结构体
	if r.specifiedDocAboutQueriesRequest != nil {
		copy.specifiedDocAboutQueriesRequest = util.DeepCopy(r.specifiedDocAboutQueriesRequest).([]*proto.DocAboutQueriesRequest)
	}
	if r.queryDefinition != nil {
		copy.queryDefinition = util.DeepCopy(r.queryDefinition).(*QueryDefinition)
	}
	if r.brandExternalInfo != nil {
		copy.brandExternalInfo = util.DeepCopy(r.brandExternalInfo).(*brandai.ExtraInfo)
	}
	if r.recallContentIds != nil {
		copy.recallContentIds = util.DeepCopy(r.recallContentIds).([]string)
	}
	if r.recallItems != nil {
		copy.recallItems = util.DeepCopy(r.recallItems).([]*Item)
	}
	if r.ragRecallItems != nil {
		copy.ragRecallItems = util.DeepCopy(r.ragRecallItems).([]*Item)
	}
	if r.assignmentDocs != nil {
		copy.assignmentDocs = util.DeepCopy(r.assignmentDocs).([]*proto.ChatCardProRelevantSource)
	}
	if r.assignmentDocKnowledgeBase != nil {
		copy.assignmentDocKnowledgeBase = util.DeepCopy(r.assignmentDocKnowledgeBase).([]proto.DocKnowledgeBase)
	}
	if r.assignmentPersonalKnowledgeBase != nil {
		copy.assignmentPersonalKnowledgeBase = util.DeepCopy(r.assignmentPersonalKnowledgeBase).([]*proto.PersonalKnowledgeBase)
	}
	if r.knowledgeBases != nil {
		copy.knowledgeBases = util.DeepCopy(r.knowledgeBases).([]proto.KnowledgeBaseType)
	}
	if r.historyDialogue != nil {
		copy.historyDialogue = util.DeepCopy(r.historyDialogue).([]*message.DialogueWrapper)
	}
	if r.responseItemList != nil {
		copy.responseItemList = util.DeepCopy(r.responseItemList).([]*Item)
	}
	if r.currentDialogue != nil {
		copy.currentDialogue = util.DeepCopy(r.currentDialogue).(*message.DialogueWrapper)
	}
	if r.currReferenceMount != nil {
		copy.currReferenceMount = util.DeepCopy(r.currReferenceMount).(*RefMountData)
	}
	if r.historyReferenceMount != nil {
		copy.historyReferenceMount = util.DeepCopy(r.historyReferenceMount).(*RefMountData)
	}
	if r.playlistRequest != nil {
		copy.playlistRequest = util.DeepCopy(r.playlistRequest).(*ai_daily_model.QueryPlaylistRequest)
	}
	if r.playlistData != nil {
		copy.playlistData = util.DeepCopy(r.playlistData).(*ai_daily_model.PlayListData)
	}
	if r.chatEvent != nil {
		copy.chatEvent = util.DeepCopy(r.chatEvent).(*chat_event.ChatEvent)
	}
	if r.authorInfo != nil {
		copy.authorInfo = util.DeepCopy(r.authorInfo).(*User)
	}
	requestContextInfo := util.DeepCopy(r.requestContextInfo).(*RequestContextInfo)
	if requestContextInfo != nil {
		copy.requestContextInfo = *requestContextInfo
	}

	// 深拷贝 map 类型字段
	copy.logicConfigMap = util.DeepCopy(r.logicConfigMap).(map[string]map[string]string)
	copy.trafficSourceChatCacheSecTTLMap = util.DeepCopy(r.trafficSourceChatCacheSecTTLMap).(map[string]int)

	// 不做深拷贝字段
	copy.abContext = r.abContext                   // ab 后期只读，不需要深拷贝
	copy.dynamicStageConfig = r.dynamicStageConfig // interface，不需要深拷贝
	copy.runCaseConfig = r.runCaseConfig           // 只读，不需要深拷贝

	return copy
}
