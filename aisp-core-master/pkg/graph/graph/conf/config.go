package conf

import (
	"encoding/json"
	"strconv"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/pkg/errors"
	"github.com/samber/lo"
	"golang.org/x/exp/slices"
)

const ConfigInputNames = "__input_names"
const ConfigOutputNames = "__output_names"

const ConfigChatHistoryKey = "chat_history"
const ConfigSourceId = "source_id"

const ConfigModelName = "model_name"

const ConfigApi = "api"

const (
	BaseConfigSkip = "base_config_skip"
	IsEnableLogic  = "is_enable_logic"
)

const EmbeddingModelName = "embedding_model_name"
const EmbeddingType = "embedding_type"
const (
	EmbeddingTypeByBge   string = "bge"
	EmbeddingTypeByBgeM3 string = "bge_m3"
)

// 实验算子 配置
const (
	ConfigExpDomain       = "exp_domain"
	ConfigExpKey          = "exp_key"
	ConfigExpValue        = "exp_value"
	ConfigExpDefaultValue = "exp_default_value"
)

// 索引召回 config
const (
	ConfigIndexLevel  = "index_level"
	ConfigIndexSource = "index_source"
)

const (
	RucenePath  = "rucene_path"
	RuceneIndex = "rucene_index"
)

const ConfigRecallSize = "recall_size"
const KnowledgeBaseType = "knowledge_base_type"
const ConfigLimit = "limit"

// ConfigRecallOrGen
const ConfigRecallOrGen = "recall_or_gen"
const ConfigRecallOrGenByRecall = "recall_or_gen_by_recall"
const ConfigRecallOrGenByGen = "recall_or_gen_by_gen"

const (
	RumTableName = "rum_table_name"
)

const (
	ConfigFaqKey                 = "faq_key"
	ConfigFaqMatchTypeKey        = "faq_match_type"
	ConfigFaqSimilarityThreshold = "faq_similarity_threshold"

	ConfigRegulateFilter = "filterReasonMap"
)

type IndexLevelType string

const (
	IndexLevel0 IndexLevelType = "RequestLevel0"
	IndexLevel1 IndexLevelType = "RequestLevel1"
	IndexLevel2 IndexLevelType = "RequestLevel2"
)

type IndexSourceType string

const (
	IndexSourceZhihu        IndexSourceType = "Zhihu"
	IndexSourceAuthorCustom IndexSourceType = "AuthorCustom"
	IndexSourceLaw          IndexSourceType = "Law"
)

type MessageType string

const (
	MessageTypeQuestion MessageType = "question"
	MessageTypeAnswer   MessageType = "answer"
)
const ConfigMessageType = "message_type"

type FAQConfigKey string

const (
	DigitalAuthorFAQ FAQConfigKey = "digital_author"
	SearchTabFAQ     FAQConfigKey = "search_tab"
	ZhihaituFAQ      FAQConfigKey = "zhihaitu"
)

const RequestLegalityRule string = "request_legality_rule"

const (
	RecallMergeTopK                 string = "recall_merge_topk"
	RecallMergeGuarantee            string = "recall_merge_guarantee"
	RecallMergeModel                string = "recall_merge_model"
	RecallMergeScoreThreshold       string = "recall_merge_score_threshold"        // 召回结果 merge 相似度分数阈值，通用
	RecallMergeScoreSourceThreshold string = "recall_merge_score_source_threshold" // 召回结果 merge 相似度分数阈值，分召回源名称
	RecallMergeScoreTextField       string = "recall_merge_score_text_field"
	RecallMergeScoreTextSourceField string = "recall_merge_score_text_source_field"
	RecallMergeSourceOrderField     string = "recall_merge_source_order_field"
	RecallMergeSortMethodField      string = "recall_merge_sort_method_field"
	RecallMergeMaxTokenField        string = "recall_merge_max_token"
	RecallMergePriorityTagCoreKV    string = "recall_merge_priority_tagcore_kv" // key:value,key:value
)

type SortMethod int

const (
	SortMethodSimilarScore SortMethod = 0 // 根据相似度排序
	SortMethodSourceOrder  SortMethod = 1 // 根据召回队列优先级排序
	SortMethodNone         SortMethod = 2 // 不更改排序
)

const RecallSameQuestionAnswerTopK string = "recall_same_question_answer_topk"

type FaqMatchType int

const (
	FaqMatchTypeEmbeddingUnknown    FaqMatchType = 0
	FaqMatchTypeEmbeddingSimilarity FaqMatchType = 1 // embedding相似度匹配
	FaqMatchTypeFullMatch           FaqMatchType = 2 // 完全匹配
	FaqMatchTypeKeywordMatchAll     FaqMatchType = 3 // 关键词全匹配
	FaqMatchTypeKeywordMatchAny     FaqMatchType = 4 // 关键词任意匹配
)

const ConfigChatMappingType string = "chat_mapping_type"

var faqMatchTypeValues []FaqMatchType
var faqMatchTypeStrs []string

func init() {
	// 下面两个数组顺序是对应的
	faqMatchTypeValues = []FaqMatchType{FaqMatchTypeEmbeddingSimilarity, FaqMatchTypeFullMatch, FaqMatchTypeKeywordMatchAll, FaqMatchTypeKeywordMatchAny}
	faqMatchTypeStrs = []string{"语义相似匹配", "字符完全匹配", "关键词全匹配", "关键词任一匹配"}
}

func FaqMatchTypeValues() []FaqMatchType {
	return faqMatchTypeValues
}

func StringToFaqMatchType(str string) (FaqMatchType, bool) {
	index := lo.IndexOf(faqMatchTypeStrs, str)
	if index == -1 {
		return FaqMatchTypeEmbeddingUnknown, false
	} else {
		return faqMatchTypeValues[index], true
	}
}

func (f FaqMatchType) ConvertToName() string {
	index := lo.IndexOf(faqMatchTypeValues, f)
	if index == -1 {
		return ""
	} else {
		return faqMatchTypeStrs[index]
	}
}

func (f FaqMatchType) Int() int {
	return int(f)
}

func (f FaqMatchType) String() string {
	return strconv.Itoa(f.Int())
}

func ConvertFaqMatchTypeArrayToInt(faqMatchTypes []FaqMatchType) int {
	var value = 0
	for _, matchType := range faqMatchTypes {
		value |= 1 << matchType.Int()
	}

	return value
}

func CreateFaqMatchTypeCombinations(faqMatchTypes []FaqMatchType) []int {
	combinations := []int{}
	allFaqMatchTypeValues := FaqMatchTypeValues()
	for i := 0; i < 2<<len(allFaqMatchTypeValues)-1; i += 2 {
		for _, value := range faqMatchTypes {
			if i&(1<<value.Int()) != 0 {
				combinations = append(combinations, i)
				break
			}
		}
	}
	return combinations
}

func ConvertIntToFaqMatchTypeArray(value int) []FaqMatchType {
	var matchTypes []FaqMatchType
	for _, faqMatchType := range FaqMatchTypeValues() {
		bitValue := 1 << faqMatchType.Int()
		if bitValue&value == bitValue {
			matchTypes = append(matchTypes, faqMatchType)
		}
	}
	return matchTypes
}

func ConvertMatchTypesToStr(matchTypes []FaqMatchType) string {
	return strings.Join(lo.Map(matchTypes, func(item FaqMatchType, _ int) string {
		return item.ConvertToName()
	}), ",")
}

const (
	ConfigPrompt                       = "prompt"
	ConfigPromptID                     = "prompt_id"
	ConfigPromptIdConcise              = "prompt_id_concise"
	ConfigPromptIdElaborated           = "prompt_id_elaborated"
	ConfigPromptType                   = "prompt_type"
	ConfigBusinessStage                = "business_stage"
	ConfigPromptKnowledgeFormatVersion = "prompt_knowledge_format_version"
	ConfigPromptKnowledgePromptId      = "prompt_knowledge_prompt_id"
)

const ConfigRecordState = "record_state"

const ConfigAllowExempt = "allow_exempt"

const (
	ConfigRegulateSceneCode    = "regulate_scene_code"
	ConfigRegulateSubSceneCode = "regulate_sub_scene_code"
	ConfigRegulateKey          = "regulate_key"
)

const (
	// FilterLogicConfByIsCheckFullContent 安全算子 是否检查 全量内容
	FilterLogicConfByIsCheckFullContent = "is_check_full_content"
	// FilterLogicConfByIncludeDocTypeArr 过滤算子 包含docType配置
	FilterLogicConfByIncludeDocTypeArr = "include_doc_type_arr"
	// FilterLogicConfByIncludePaperArr 过滤算子 包含Paper下类型配置
	FilterLogicConfByIncludePaperArr = "include_paper_type_arr"
	// FilterLogicConfByExtraExcludeKbSourceArr 过滤算子 排除召回源配置
	// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
	FilterLogicConfByExtraExcludeKbSourceArr = "exclude_kb_source_arr"
)

type LogicConfigKey string

func (s LogicConfigKey) ToConvert() string {
	return string(s)
}

const (
	// JsonConfigLogicKey Json 配置
	JsonConfigLogicKey LogicConfigKey = "json_config"

	// RiskConfigWordSource 词安全审核场景
	RiskConfigWordSource LogicConfigKey = "risk_config_word_source"

	// SummaryConfigLogicByThreshold Summary 配置
	// SummaryConfigLogicByThreshold Summary similar 相关性阈值
	SummaryConfigLogicByThreshold LogicConfigKey = "summary_config_similar_threshold"
	// SummaryRecallSource 召回源
	SummaryRecallSource LogicConfigKey = "summary_recall_source"
	// SummaryRecallOrderGroup 召回分组排序
	SummaryRecallOrderGroup LogicConfigKey = "summary_recall_order_group"
	// SummaryRecallFilterIo 召回过滤站内外
	SummaryRecallFilterIo LogicConfigKey = "summary_recall_filter_io"
	// SecurityBusinessStage 安全业务阶段
	SecurityBusinessStage LogicConfigKey = "security_business_stage"
	// IsNotAllowReviseSecurityResult 是否不允许校正安全最终结果
	IsNotAllowReviseSecurityResult LogicConfigKey = "is_not_allow_revise_security_result"
	// WordEmbeddingModelName 词 embedding 模型名称
	WordEmbeddingModelName LogicConfigKey = "word_embedding_model_name"
	// WordTopK 获取词数量
	WordTopK LogicConfigKey = "word_top_k"
	// RelatedWordIsUseCache 相关词是否使用缓存
	RelatedWordIsUseCache LogicConfigKey = "related_word_is_use_cache"
	// RelatedWordCacheNilIsGenerate 相关词缓存为空是否继续生成
	RelatedWordCacheNilIsGenerate LogicConfigKey = "related_word_cache_nil_is_generate"
	// ChatQueryCacheIsOnlyPrefabWord 是否只是缓存预制词 bool
	ChatQueryCacheIsOnlyPrefabWord LogicConfigKey = "chat_query_cache_is_only_prefab_word"

	RecallFilterSiteLevelThreshold LogicConfigKey = "recall_filter_site_level_threshold"
	// RecallFilterSimHashThreshold 召回内容相似度过滤阈值 和 上下文长度限制
	RecallFilterSimHashThreshold    LogicConfigKey = "recall_filter_sim_hash_threshold"
	RecallFilterSimHashContentLimit LogicConfigKey = "recall_filter_sim_hash_content_limit"
)

const (
	StreamChatPromptOrder                    = "stream_chat_prompt_order"
	StreamChatPromptContextAssistantResponse = "stream_chat_prompt_context_assistant_response"
	StreamChatDisableReferences              = "stream_chat_disable_references"
	StreamChatIsCitePage                     = "stream_chat_is_cite_page"
	StreamChatIsUseThink                     = "stream_chat_is_use_think"
	StreamChatIsThinkSeparated               = "stream_chat_is_think_separated"
	ChatMessageJsonConfig                    = "chat_message_json_config"
	ChatMessageRouterJsonConfig              = "chat_message_router_json_config"
	ChatDisable                              = "chat_disable"
	Answer2CardEnableAuthorBge               = "answer2card_enable_author_bge"
	Answer2CardContentType                   = "answer2card_content_type"
	Answer2ModelOnlyAuthorSelf               = "stream_chat_answer2model_only_author_self"
	MountStateConfig                         = "specified_doc_mount_state"
)

const (
	TagCoreSceneCode    = "scene_code"
	TagCoreAppGroupCode = "app_group_code"
)

// 条件判断logic相关
const (
	ConditionCondition  = "condition_condition"
	ConditionCompareTo  = "condition_compare_to"
	ConditionIfBranch   = "condition_if_branch"
	ConditionElseBranch = "condition_else_branch"

	ConditionExpression = "condition_expression"
)

// RefuseText 拒绝回答时的文案
const RefuseText = "refuse_text"

const (
	AuthorSearchAgentRankBeta = "author_search_agent_rank_beta"
)

const (
	OverwriteConfigBy       = "overwrite_config_by"
	OverwriteConfigStrategy = "overwrite_config_strategy"
	OverwriteStrategyExp    = "overwrite_strategy_exp"
)

const (
	QueryMergeSkipAndSetAsQuery = "query_merge_skip_and_set_as_query"
	QueryMergeModel             = "query_merge_config_model"
	QueryMergeMaxContextLength  = "query_merge_config_max_context_length"
	QueryMergeDialogMaxCount    = "query_merge_dialog_max_count"
)

const (
	TruncateSize = "truncate_size"
)

const (
	ChatHistorySkip       LogicConfigKey = "chat_history_skip"
	SessionInfoSkip       LogicConfigKey = "session_info_skip"
	KnowledgeBaseInfoSkip LogicConfigKey = "knowledge_base_info_skip"
)

const (
	SkipRuceneTracing LogicConfigKey = "skip_rucene_tracing"
	TracingKafkaTopic LogicConfigKey = "tracing_kafka_topic"
)

type ChatConfig struct {
	ModelName                  string                 `json:"model_name"`      // 模型名称
	AIProfile                  string                 `json:"ai_profile"`      // 默认 system prompt
	IsNeedHistory              bool                   `json:"is_need_history"` // 是否需要对话历史
	SecurityConfig             *SecurityConfig        `json:"security_config"` // 安全配置
	ChatHistoryType            ChatHistoryType        `json:"chat_history_type"`
	TrimPrefix                 string                 `json:"trim_prefix"`          //  去除回答前缀
	IsReferences               bool                   `json:"is_references"`        // 引用角标
	IsCitePage                 bool                   `json:"is_cite_page"`         // 是否单篇角标
	IsCiteV2                   bool                   `json:"is_cite_v2"`           // 是否角标v2
	IsInPersonCiteV2           bool                   `json:"is_in_person_cite_v2"` // 在角标v2下，是否包含亲自答角标
	IsUseThink                 bool                   `json:"is_use_think"`         // 是否使用 think
	IsThinkSeparated           bool                   `json:"is_think_separated"`   // think 是否单独出
	MaxTokens                  *int32                 `json:"max_tokens"`
	Stop                       []string               `json:"stop"`
	Temperature                *float32               `json:"temperature"`
	TopP                       *float32               `json:"top_p"`
	TopK                       *int32                 `json:"top_k"`
	RepetitionPenalty          *float32               `json:"repetition_penalty"`
	PresencePenalty            *float32               `json:"presence_penalty"`
	FrequencyPenalty           *float32               `json:"frequency_penalty"`
	Stage                      proto.BusinessStage    `json:"stage"` // stage 业务阶段，用于tracing
	ChatHistoryRoundLimit      int                    `json:"chat_history_round_limit"`
	ChatHistoryStrLength       int                    `json:"chat_history_str_length"`
	CiteMaxCount               int                    `json:"cite_max_count"`                 // 引用最大数量
	ContextLength              int                    `json:"context_length"`                 // 上下文长度(用于计算喂给模型的内容长度) *** 很重要 必须要配置 新版V2 要基于该字段进行动态配置 ***
	ExtraContextLength         int                    `json:"extra_context_length"`           // 额外上下文长度
	EnableThinking             *bool                  `json:"enable_thinking"`                // 不允许输出思考过程
	ThinkingType               ThinkingType           `json:"thinking_type"`                  // 是否允许输出思考过程类型，https://www.volcengine.com/docs/82379/1494384
	ExtraBody                  map[string]interface{} `json:"extra_body"`                     // 额外body参数，仅
	UseSystemPromptPrefixCache bool                   `json:"use_system_prompt_prefix_cache"` // 是否使用 system prompt 前缀缓存
	ModelApi                   ModelApi               `json:"model_api"`                      // 模型调用api，默认 chat/completions
}

type ModelApi string

const (
	ModelApiChatCompletions ModelApi = "chat/completions"
	ModelApiResponses       ModelApi = "responses"
)

type ThinkingType string

const (
	ThinkingTypeEnabled  ThinkingType = "enabled"  // 允许输出思考过程
	ThinkingTypeDisabled ThinkingType = "disabled" // 禁止输出思考过程
	ThinkingTypeAuto     ThinkingType = "auto"     // 自动判断是否输出思考过程
)

type MsgConfig struct {
	SystemPromptId              string          `json:"system_prompt_id"`               // System Prompt id
	SystemDefaultPromptTemplate string          `json:"system_default_prompt_template"` // System Prompt 默认模板
	SystemPromptTag             string          `json:"system_prompt_tag"`              // System Prompt tag
	ApolloNameSpace             string          `json:"apollo_name_space"`              // apollo namespace
	MsgConfigArr                []ChatMsgConfig `json:"msg_config_arr"`                 // 配置数组
	IsCustom                    bool            `json:"is_custom"`                      // 是否自定义 自定义模式下 深入简略等模式不生效
}

func (c MsgConfig) ToJsonString() string {
	marshal, _ := json.Marshal(c)
	return string(marshal)
}

func (c ChatConfig) ToJsonString() string {
	marshal, _ := json.Marshal(c)
	return string(marshal)
}

func (c ChatConfig) Check() error {
	if c.SecurityConfig == nil {
		return errors.Errorf("SecurityConfig is not null")
	}
	return nil
}

type RouteConfig struct {
	IsEnable              bool                   `json:"is_enable"`                // 是否启用Query路由
	ModelName             string                 `json:"model_name"`               // 模型名称
	SystemPromptKey       string                 `json:"system_prompt_key"`        // 系统提示key(优先取Apollo配置)
	SystemPrompt          string                 `json:"system_prompt"`            // 系统提示
	QueryPromptKey        string                 `json:"query_prompt_key"`         // Query提示key(优先取Apollo配置)
	QueryPrompt           string                 `json:"query_prompt"`             // Query提示
	IsNeedHistory         bool                   `json:"is_need_history"`          // 是否需要对话历史
	ChatHistoryRoundLimit int                    `json:"chat_history_round_limit"` // 对话历史轮次限制
	Timeout               time.Duration          `json:"timeout"`                  // 超时时间
	MaxTokens             *int32                 `json:"max_tokens"`               // 最大生成token数
	Temperature           *float32               `json:"temperature"`              // 温度
	ResponseFormat        *string                `json:"response_format"`          // 返回格式
	GuidedJson            map[string]interface{} `json:"guided_json"`              // 引导json
	GuidedChoice          []macro.IntentionType  `json:"guided_choice"`            // 引导选择
	DefaultChoice         macro.IntentionType    `json:"default_choice"`           // 默认选择
	RouteBiz              string                 `json:"route_biz"`                // 路由业务线
}

func (c RouteConfig) ToJsonString() string {
	marshal, _ := json.Marshal(c)
	return string(marshal)
}

func (c RouteConfig) Check() error {
	if c.ModelName == "" {
		return errors.Errorf("ModelName is empty")
	}
	return nil
}

type SecurityConfig struct {
	SourceId             int64         `json:"source_id"`          // sourceId 安全场景 sourceId
	ChatMappingType      int64         `json:"chat_mapping_type"`  // chatMappingType 会话类型
	Scene                string        `json:"scene"`              // 场景
	StoreSource          LogicStoreKey `json:"store_source"`       // 如果依赖于存储数据 则传输Key，
	ExtraStoreSource     LogicStoreKey `json:"extra_store_source"` // 如果需要额外给定存储数据，则传输key
	SetRedLineAnswer     bool          `json:"set_red_line_answer"`
	SceneContextKey      string        `json:"scene_context_key"`       // scene启动时无法确定，运行时才能确定的场景，从context取
	CallSecurityIfExempt bool          `json:"call_security_if_exempt"` // 当需要豁免安全结果时，如果为true，则仍然会调用安全接口，但是会忽略接口结果
}

func (c SecurityConfig) ToJsonString() string {
	marshal, _ := json.Marshal(c)
	return string(marshal)
}

type ZSearchRecallConfig struct {
	RestrictedScope searchThrift.RestrictedScope
	IndexLevel      IndexLevelType
	Vertical        []searchThrift.Vertical
	OnlyA4p         bool
	// RecallSize 召回条目
	RecallSize int32
	// OrderGroup 召回算子内容排序
	OrderGroup int
	// NeedNotQueryCorrection 是否不需要query 校正
	NeedNotQueryCorrection bool
	// 控制召回内容时间。bing参考：https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/filter-answers#specifying-the-contents-freshness
	Freshness string
	// 控制召回内容的时间在某个时间之前。秒级别时间戳
	TimeBefore int32
	// 知识库类型
	KnowledgeBaseType enums.KnowledgeBaseType
}

type RecallLimitConfig struct {
	// RecallLimitMap 召回源条目最终限制
	RecallLimitMap map[KbSource]int32
}

type RecallChunkReRankConfig struct {
	KeySize   int
	KeyStep   int
	KeyOffset float64
	ValueSize int
	TotalSize int
	// 得分阈值，得分倒序后看分数下降率，距离前面均值超过阈值则丢弃（如果不需要阈值时 请设置小于等于0）
	ScoreThreshold float64
	// 得分加权 score ^ scale 为最终分 进行比较，默认为1 （对于不同召回源加权）
	ScoreScales map[KbSource]float64
	// 边界正则
	BoundaryRegex rerank_util.BoundaryRegexEnum
	// 是否使用 itemMeta.raw 截取 chunk，默认 itemMeta.content
	UseRaw bool
	// 是否运行单item 跳过切chunk
	IsAllowSingleItemSkipChunk bool
	// 直接跳过切chunk
	IsAllowItemSkipChunk bool
	// 是否保量
	EachDocHasChunk            bool
	ActualChunkSizeLimitPerDoc int
	ModelName                  string
	// 根据tag条件对分数应用系数，格式：tagKey1:tagValue1:multiplier1,tagKey2:tagValue2:multiplier2
	// 例如：answer_property:亲自答:1.2,answer_property:相关方答:1.1
	ScoreScaleByTag string
}

func (r RecallChunkReRankConfig) ToJsonString() string {
	marshal, _ := json.Marshal(r)
	return string(marshal)
}

// LogicStoreKey 逻辑节点存储Key =========================
type LogicStoreKey string

func (s LogicStoreKey) String() string {
	return string(s)
}

const (
	// SourceQueryItemLogicStoreKey 原始对话记录
	SourceQueryItemLogicStoreKey LogicStoreKey = "source_query_item"
	RecallCardLogicStoreKey      LogicStoreKey = "recall_card"
	StreamChatResultStoreKey     LogicStoreKey = "stream_chat_result"
)

// KbSource 知识库来源
type KbSource string

func (a KbSource) String() string {
	return string(a)
}

const (
	KbSourceBing                    KbSource = "bing"
	KbSourceSougou                  KbSource = "sougou"
	KbSourceQuark                   KbSource = "quark"
	KbSourceSerper                  KbSource = "serper"
	KbSourceZhihu                   KbSource = "zhihu"
	KbSourceKexin                   KbSource = "kexin"
	KbSourceZhihuSameQuestionAnswer KbSource = "zhihu_same_question_answer"
	KbSourceZhihuKbEnhance          KbSource = "zhihu_kb_enhance"
	KbSourceZhihuA4                 KbSource = "zhihu_a4"
	KbSourceOutSiteRucene           KbSource = "outsite_rucene"
	KbSourceOutSiteRum              KbSource = "outsite_rum"
	KbSourceAuthorBge               KbSource = "author_bge"
	KbSourceAuthorSelf              KbSource = "author_self"
	KbSourceZPlusAutomotive         KbSource = "zplus_automotive"
	KbSourceZhihuArxiv              KbSource = "zhihu_arxiv"
	KbSourceZhihuWeipu              KbSource = "zhihu_weipu"
	KbSourceUserSpecified           KbSource = "user_specified"
	KbSourceEnWikiRum               KbSource = "en_wiki_rum"
	KbSourceZhWikiRum               KbSource = "zh_wiki_rum"
	KbSourceEnWikiRucene            KbSource = "en_wiki_rucene"
	KbSourceZhWikiRucene            KbSource = "zh_wiki_rucene"
	KbSourceMount                   KbSource = "mount"
	PersonalKnowledgeBaseRucene     KbSource = "personal_knowledge_base_rucene"
	PersonalKnowledgeBaseRum        KbSource = "personal_knowledge_base_rum"
	InternalKnowledgeBaseRucene     KbSource = "internal_knowledge_base_rucene"
	InternalKnowledgeBaseRum        KbSource = "internal_knowledge_base_rum"
)

// LimitByKbSourceRes 限制召回数量和长度
type LimitByKbSourceRes struct {
	SearchRecallSourceLimit int
	SearchRecallLimit       int
	StrLengthLimit          int
	IsRecallTest            bool
}

func (l *LimitByKbSourceRes) GetSearchRecallSourceLimit() int {
	if l != nil {
		return l.SearchRecallSourceLimit
	}
	return 0
}
func (l *LimitByKbSourceRes) GetSearchRecallLimit() int {
	if l != nil {
		return l.SearchRecallLimit
	}
	return 0
}
func (l *LimitByKbSourceRes) GetStrLengthLimit() int {
	if l != nil {
		return l.StrLengthLimit
	}
	return 0
}
func (l *LimitByKbSourceRes) GetIsRecallTest() bool {
	if l != nil {
		return l.IsRecallTest
	}
	return false
}

const configArrayValueSep = ","

func BuildConfigArrayValue(values ...string) string {
	return strings.Join(values, configArrayValueSep)
}

func SplitConfigArrayValue(value string) []string {
	return strings.Split(value, configArrayValueSep)
}

type ChatHistoryType string

func (a ChatHistoryType) String() string {
	return string(a)
}

const (
	ChatHistoryNone           ChatHistoryType = "none"
	ChatHistoryStrLengthLimit ChatHistoryType = "str_length_limit"
	ChatHistoryRoundLimit     ChatHistoryType = "round_limit"
)

type ExpConfig struct {
	Domain string
	ZLab   zlab.ZlabValue
}

func (c ExpConfig) Check() error {
	if c.Domain == "" {
		return errors.Errorf("ExpConfig.Domain is null")
	}
	if c.ZLab.Key == "" {
		return errors.Errorf("ExpConfig.ZLab is null")
	}
	return nil
}
func (c ExpConfig) ToJsonString() string {
	marshal, _ := json.Marshal(c)
	return string(marshal)
}

const (
	ConfigSwitchConditionDefaultBranch   = "switch_condition_default_branch"
	ConfigSwitchConditionSwitchBranchMap = "switch_condition_switch_branch_map"
)

func KbSourceSort(kbSources []KbSource) []KbSource {
	hasSelf := false
	for _, kbSource := range kbSources {
		if kbSource == KbSourceAuthorSelf {
			hasSelf = true
			break
		}
	}

	// 不包含搜自己，直接返回
	if !hasSelf {
		return kbSources
	}

	// 包含 author_self 的，把 author_self 源放在最前面
	kbSources = slices.DeleteFunc(kbSources, func(i KbSource) bool {
		return i == KbSourceAuthorSelf
	})
	kbSources = slices.Insert(kbSources, 0, KbSourceAuthorSelf)

	return kbSources
}

type StageType string

func (s StageType) String() string {
	return string(s)
}

const (
	StageTypeConfig     string    = "stage_type_config"
	StageTypeInit       StageType = "init"
	StageTypeRecall     StageType = "recall"
	StageTypeDeepSearch StageType = "deep_search"
	StageTypeReRank     StageType = "rerank"
	StageTypeGenerate   StageType = "generate"
)
