package rpc

import "context"

// 可信全网搜 KexinRPC 封装对 ZSearch RootService 的检索调用
// 返回站外召回统一结果结构，便于与其他搜索源对齐
type KexinRPC interface {
	Search(ctx context.Context, query string, topK int32, traceId string) ([]*OutSiteSearchRecallAnswerResult, error)
}
