package macro

import "git.in.zhihu.com/go/cafe/config"

type IntentionType string

const (
	// queryIntentionTypeNo 无意图
	queryIntentionTypeNo IntentionType = "<option_0>"
	// queryIntentionTypeYes 有意图
	queryIntentionTypeYes IntentionType = "<option_1>"
	// Empty
	queryRouteEmpty IntentionType = ""
	// 模型自我介绍
	queryRouteIdentity IntentionType = "模型自我介绍"
	// 模型直接回答
	queryRouteDirect IntentionType = "模型直接回答"
	// 知乎答主查询
	queryRouteAuthor IntentionType = "知乎答主查询"
	// 知识查询
	queryRouteSearch IntentionType = "知识查询"
	// 数学意图
	queryRouteMath IntentionType = "数学类查询"
	// 计算机类查询
	queryRouteCode IntentionType = "计算机类查询"
	// 竞对类查询
	queryRouteCompetitor IntentionType = "竞对类查询"
)

type TimelinessType string

const (
	TimelinessShort  TimelinessType = "短时效"
	TimelinessMiddle TimelinessType = "中时效"
)

// 无意图
func GetQueryIntentionTypeNo() IntentionType {
	return IntentionType(config.GetString("intention_type.query_intention_type_no", string(queryIntentionTypeNo)))
}

// 有意图
func GetQueryIntentionTypeYes() IntentionType {
	return IntentionType(config.GetString("intention_type.query_intention_type_yes", string(queryIntentionTypeYes)))
}

// Empty
func GetQueryRouteEmpty() IntentionType {
	return IntentionType(config.GetString("intention_type.query_route_empty", string(queryRouteEmpty)))
}

// 模型自我介绍
func GetQueryRouteIdentity() IntentionType {
	return IntentionType(config.GetString("intention_type.query_route_identity", string(queryRouteIdentity)))
}

// 模型直接回答
func GetQueryRouteDirect() IntentionType {
	return IntentionType(config.GetString("intention_type.query_route_direct", string(queryRouteDirect)))
}

// 知乎答主查询
func GetQueryRouteAuthor() IntentionType {
	return IntentionType(config.GetString("intention_type.query_route_author", string(queryRouteAuthor)))
}

// 知识查询
func GetQueryRouteSearch() IntentionType {
	return IntentionType(config.GetString("intention_type.query_route_search", string(queryRouteSearch)))
}

// 数学查询
func GetQueryRouteMath() IntentionType {
	return IntentionType(config.GetString("intention_type.math", string(queryRouteMath)))
}

// 计算机类查询
func GetQueryRouteCode() IntentionType {
	return IntentionType(config.GetString("intention_type.code", string(queryRouteCode)))
}

// 提及竞对类查询
func GetQueryRouteCompetitor() IntentionType {
	return IntentionType(config.GetStringByNamespace(ZplusApolloNamespace,
		"intention_type.query_route_competitor", string(queryRouteCompetitor)))
}

func (i IntentionType) String() string {
	return string(i)
}

func (i IntentionType) Name() string {
	switch i {
	case GetQueryRouteEmpty():
		return "QueryRouteEmpty"
	case GetQueryRouteIdentity():
		return "QueryRouteIdentity"
	case GetQueryRouteDirect():
		return "QueryRouteDirect"
	case GetQueryRouteAuthor():
		return "QueryRouteAuthor"
	case GetQueryRouteSearch():
		return "QueryRouteSearch"
	case GetQueryRouteMath():
		return "queryRouteMath"
	case GetQueryRouteCode():
		return "queryRouteCode"
	case GetQueryRouteCompetitor():
		return "queryRouteCompetitor"
	default:
		return "Unknown"
	}
}

const AuthorSelf = "authorSelf"
const ReAnswerAuthorSelf = "reAnswerAuthorSelf"
const EmptyRecall = "emptyRecall"
const EmptyRecallNoChat = "emptyRecallNoChat"
const DeepThinking = "deepThinking"
const DeepThinkingEmptyRecall = "deepThinkingEmptyRecall"
const ZplusBrand = "zplusBrand"

const (
	EndNode      = "end"
	ResponseNode = "buildResponse"
)

const (
	IsUnRegisterNotPrefabWord   = "IsUnRegisterNotPrefabWord"
	IsBlockedUser               = "IsBlockedUser"
	IsUserQpsOverLimit          = "IsUserQpsOverLimit"
	IsNotHasKbOrPersonalKbOrDoc = "IsNotHasKbOrPersonalKbOrDoc"
)

var (
	SecurityReviewFailed = "安全拦截"
	Redline              = "红线必答"
	Faq                  = "FAQ匹配"
	KnowledgeEnhance     = "知识增强"
)
