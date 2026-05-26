package query_merge

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"github.com/pkg/errors"
)

// BuildQueryMergeToProto 转化为 ProtoBuf
func BuildQueryMergeToProto(ctx context.Context, req *proto.BuildQueryRequest) (p *proto.BuildQueryResponse, ex error) {
	defer func() {
		if r := recover(); r != nil {
			ex = errors.Errorf("执行BuildQueryMergeToProto发生异常 => %v", r)
		}
	}()

	query, err := buildQueryMerge(req)
	if err != nil {
		return nil, err
	}

	// 组装 Response消息
	response := proto.BuildQueryResponse{
		Query: &proto.Query{
			Query: query,
		},
	}
	return &response, nil
}

// buildQueryMerge TODO 下游接口未提供 暂时Mock数据
func buildQueryMerge(req *proto.BuildQueryRequest) (resStr string, ex error) {
	defer func() {
		if r := recover(); r != nil {
			resStr = "错误"
			ex = errors.Errorf("执行buildQueryMerge发生异常 => %v", r)
		}
	}()

	switch req.Type {
	case proto.BuildQueryType_SEARCH_TAB_SEARCH_CARD:
		// TODO 是否根据 sessionId 查询历史内容 构建QueryMerge词
		// TODO 模拟QueryMerge生成
		// requestInfo := req.Info()
		return req.GetInfo().GetMessage().Text, nil
	default:
		return "", errors.Errorf("请求类型未定义或类型未匹配 => %v", req.Type)
	}
}
