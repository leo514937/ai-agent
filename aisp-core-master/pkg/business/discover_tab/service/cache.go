package service

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var zhidaChatTypes = []proto.ChatType{
	proto.ChatType_ZHIDA_TAB, proto.ChatType_ZHIDA_V2, proto.ChatType_ZHIDA_AGENT,
}

func ClearZhidaCache(ctx context.Context, text string) {
	for _, chatType := range zhidaChatTypes {
		DoClearZhidaCache(ctx, chatType, text)
	}
}

func DoClearZhidaCache(ctx context.Context, chatType proto.ChatType, text string) {
	redisDao := impl.DefaultQueryResultDaoImpl

	deletedFlagMap := make(map[string]bool)
	// 目前只删除了 非answer实体词、评论实体词相关词的缓存
	scene := entities.BuildGraphScene(graph_constant.ApiStreamChat, chatType.String())
	for _, clientSourceName := range proto.ClientSource_name {
		if clientSourceName == proto.ClientSource_UNDEFINED_SOURCE.String() {
			continue
		}

		for _, trafficSourceName := range proto.TrafficSource_name {
			if trafficSourceName == proto.TrafficSource_undefined_traffic.String() {
				continue
			}

			for _, chatModelName := range proto.ChatModel_name {
				key := fmt.Sprintf("%s-%s-%s-%s-%s", scene, clientSourceName, trafficSourceName, chatModelName, text)
				isOk := true
				err := redisDao.DeleteResponseInfo(ctx, scene, clientSourceName, trafficSourceName, chatModelName, map[string]string{}, text)
				if err != nil {
					fmt.Printf("deleted err key:[%s] errorMsg: %s", key, err.Error())
					isOk = false
				}
				deletedFlagMap[key] = isOk
			}
		}
	}

	// 输出结果
	log.Infof(ctx, "delete zhida cache. result=%s", util.GetJSONIgnoreError(deletedFlagMap))
}
