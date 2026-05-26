package req_macro

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

// SourceType 数据源类型枚举
type SourceType string

const (
	SourceTypeSelected      SourceType = "selected"
	SourceTypePortfolio     SourceType = "portfolio"
	SourceTypeKnowledgeBase SourceType = "knowledge_base"
	SourceTypeIndex         SourceType = "index"
)

// SourceMeta 数据源元信息
type SourceMeta struct {
	ID                int64                           `json:"id"`
	DocType           aiContent.DocType_Type          `json:"docType"`
	KnowledgeBaseType proto.PersonalKnowledgeBaseType `json:"knowledgeBaseType"`
	Name              string                          `json:"name"`
}

// SourceInfo 数据源信息
type SourceInfo struct {
	Type        SourceType `json:"type"`
	TypeStr     string     `json:"type_str"`
	Meta        SourceMeta `json:"meta"`
	Description string     `json:"description"`
}

var SourceTypeStr = map[SourceType]string{
	SourceTypeSelected:      "用户选中",
	SourceTypePortfolio:     "知乎创作",
	SourceTypeKnowledgeBase: "知识库",
	SourceTypeIndex:         "搜索索引",
}
