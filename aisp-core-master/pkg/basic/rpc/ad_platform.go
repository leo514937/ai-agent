package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-bidding_xg_tools/brandai"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type AdPlatFormRPC interface {
	// 获取召回结果
	GetRecallList(ctx context.Context, query string, queryMerge string, memberId int64, sessionId string, messageId string, extraInfo *brandai.ExtraInfo) []*model.ItemMeta
}

var AdContentTypeMap = map[brandai.BrandAiQaDocType]content.DocType_Type{
	brandai.BrandAiQaDocType_Question: content.DocType_Question,
	brandai.BrandAiQaDocType_Answer:   content.DocType_Answer,
	brandai.BrandAiQaDocType_Article:  content.DocType_Article,
	brandai.BrandAiQaDocType_ZVideo:   content.DocType_ZVideo,
	brandai.BrandAiQaDocType_Pin:      content.DocType_Pin,
	brandai.BrandAiQaDocType_Text:     content.DocType_Text,
}
