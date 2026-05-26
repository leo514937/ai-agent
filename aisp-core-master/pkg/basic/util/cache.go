package util

import (
	"time"

	"git.in.zhihu.com/zrec/zrec-utils/cache"
)

// 缓存 item key 生成函数，缓存格式为 keyOption.CacheName() + keyGeneratorFunc()
var StringKeyGeneratorFunc = func(i interface{}) string { return i.(string) }

// redis local cache key option
var SuggestQueriesKeyOption = cache.NewKeyOption("SuggestQueries", 10000, true, 1*time.Hour)
var TracingLogIdsKeyOption = cache.NewKeyOption("TracingLogIds", 1000000, false, 3*time.Minute)
var RemovedWordsKeyOption = cache.NewKeyOption("RemovedWords", 100, false, 1*time.Hour)
var ModelLevelKeyOption = cache.NewKeyOption("ModelLevel", 1000, true, 1*time.Hour)
var SkuAliasKeyOption = cache.NewKeyOption("SkuAlias", 1000, true, 1*time.Hour)
var SkuAliasRealTimeKeyOption = cache.NewKeyOption("SkuAliasRealTime", 1000, true, 1*time.Hour)
var SystemPromptPrefixCacheOption = cache.NewKeyOption("SystemPromptPrefixCache", 10, true, 2*time.Hour)
