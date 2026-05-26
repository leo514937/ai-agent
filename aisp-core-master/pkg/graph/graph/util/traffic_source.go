package util

import proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"

func GetEntityTrafficSources() []proto.TrafficSource {
	return []proto.TrafficSource{proto.TrafficSource_entity_preview, proto.TrafficSource_entity, proto.TrafficSource_search_entity_preview, proto.TrafficSource_comment_entity}
}
