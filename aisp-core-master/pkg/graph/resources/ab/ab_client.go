package ab

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

// 布谷实验平台

var ZlabRecommendMemberStategyClient = zlab.NewZlabABClient(macro.ZlabSceneIdRecommendMemberStrategyDomain)

var ZlabAiRecMemberStategyClient = zlab.NewZlabABClient(macro.ZlabSceneIdAiRecDomain)

var ZlabWebStandardClient = zlab.NewZlabABClient(macro.ZlabSceneIdWebStandardDomain)

var ZlabGrowthClient = zlab.NewZlabABClient(macro.ZlabSceneIdAiGrowthDomain)

var ZlabSearchClient = zlab.NewZlabABClient(macro.ZlabSceneIdSearchDomain)
