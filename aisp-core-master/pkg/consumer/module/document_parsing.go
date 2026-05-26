package module

import proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"

type DocumentParsingKafkaMsg struct {
	ZhidaRelevantSource proto.ChatCardProRelevantSource `json:"ZhidaRelevantSource"`
}
