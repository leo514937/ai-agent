package main

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	ctx := context.Background()
	rumClient := rpcImpl.DefaultFloat32RumClientImpl
	rumCache := rum_cache.NewRumCache()
	wordWrapperService := word.NewWordMapperService()
	logger := log.WithFields(ctx, map[string]any{
		"func": "RemoveWord",
	})

	removeDocIds := []int64{3600378036922795214, 3602006433972319017, 3602387703321829208, 3603312483638776183}

	for _, docId := range removeDocIds {
		wordInfo, err := wordWrapperService.GetSourceWordInfo(ctx, docId, int32(proto.QueryType_PREFAB_WORD_QUESTION))
		if err != nil {
			logger.Errorf(ctx, "Delted PrefabWordToRum Err docId: %d, wordType:%s | MySQL:%v",
				docId, proto.QueryType_PREFAB_WORD_QUESTION, err)
			continue
		}
		// 删除 rum
		actionRes := rumClient.RumDelete(ctx, macro.AiPrefabWordV2RumTable, docId, "")
		// 删除 MySQL
		_, deleteMySQLErr := wordWrapperService.RemoveWordId(ctx, docId, int32(proto.QueryType_PREFAB_WORD_QUESTION))
		// 清除词缓存（判断是否是预制词）
		resource.RedisLocalCache.BatchDelete(ctx, []string{wordInfo.Word}, util.StringKeyGeneratorFunc, util.SuggestQueriesKeyOption)
		if !actionRes || deleteMySQLErr != nil {
			// 保存删除错误记录到 redis中 便于后期进行后过滤(只有异常情况下才会有记录)
			rumCache.SaveDeleteErrorCache(ctx, docId, macro.AiPrefabWordV2RumTable)
			logger.Errorf(ctx, "Delted PrefabWordToRum Err docId: %d, wordType:%s | MySQL:%v",
				docId, proto.QueryType_PREFAB_WORD_QUESTION, deleteMySQLErr)
		} else {
			logger.Infof(ctx, "Delted PrefabWordToRum Success docId: %d, wordType:%s",
				docId, proto.QueryType_PREFAB_WORD_QUESTION)
		}
	}

}
