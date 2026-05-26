package macro

const (
	SecurityWhiteListConfigName            = "security_whitelist"
	SecurityAuthorWhiteListConfigName      = "security_author_whitelist"
	AbTestWhiteListConfigName              = "ab_test_whitelist"
	ChatRecallEmbeddingBatchSizeConfigName = "chat_recall_embedding_batch_size"
	ChatRecallReRankBatchSizeConfigName    = "chat_recall_rerank_batch_size"
	ChatEnableCacheConfigName              = "discover_tab_enable_cache"
	ChatCacheDefTTLConfigName              = "chat_cache_def_ttl"
	ChatCacheTTLByTrafficSourceConfigName  = "chat_cache_ttl_by_traffic_source"

	// BingTokenConfigName Bing Token
	BingTokenConfigName      = "bing_token"
	CloudSwayTokenConfigName = "cloud_sway_token"
	// Sougou Token
	SougouSecretIdConfigName  = "sougou_secret_id"
	SougouSecretKeyConfigName = "sougou_secret_key"
	SougouPidConfigName       = "sougou_pid"
	SougouTokenConfigName     = "sougou_token"
	// BoCha Token
	BoChaTokenConfigName = "bocha_token"
	// Serper Token
	SerperTokenConfigName  = "serper_token"
	ABTestCitiesConfigName = "abtest_cities"

	// rucene 地址相关配置
	OnlineRuceneProxyConfigName = "online_rucene_proxy"
	BaiduRuceneProxyConfigName  = "baidu_rucene_proxy"

	OutSiteRecallMergeConfigName = "outsure_recall_merge"

	StreamChatSecurityDurationConfigName = "stream_chat_security_timeout"
	ZhidaStarAuthorsConfigName           = "zhida_star_authors"

	BlockMemberIdConfigName          = "block_memberids"
	RequestIntervalSecondsConfigName = "request_interval_s"
	QueryRouterSwitchConfigName      = "query_router_switch"
	DoubaoSwitchConfigName           = "doubao_switch"
	KexinSwitchConfigName            = "kexin_switch"
	ScoreScaleByTag                  = "score_scale_by_tag"

	ZhidaDisableCacheTrafficSource = "zhida_disable_cache_traffic_source"

	ZplusApolloNamespace       = "zplus.properties"
	BrandDescriptionConfigName = "brand_description"
	BrandQueryRouteConfigName  = "brand_query_route"
	BrandPromptTag             = "brand_prompt_tag"

	UseEasterEgg        = "use_easter_egg"
	DeepThinkingMessage = "deep_thinking_message"
	RetryMessage        = "retry_message"
	BingUseProxy        = "bing_use_proxy"
	OpenPrefixCache     = "open_prefix_cache"

	UniversalKbDescription      = "universal_kb_description"
	UniversalKbAgentDescription = "universal_kb_agent_description"

	RecallBlackListConfigName = "recall_blacklist"

	BrowseRecentLimit     = "browse_recent_limit"
	BrowseAllLimit        = "browse_all_limit"
	SpecificDocTokenLimit = "specific_doc_token_limit"

	NoCacheMemberIds = "no_cache_member_ids"
)
