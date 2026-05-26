package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type PersonalKnowledgeDoc struct {
	Id                        int64                           `json:"id,omitempty"`
	MemberId                  int64                           `json:"member_id,omitempty"`
	DocId                     int64                           `json:"doc_id,omitempty"`
	DocType                   content.DocType_Type            `json:"doc_type,omitempty"`
	PersonalKnowledgeBaseId   int64                           `json:"personal_knowledge_base_id,omitempty"`
	PersonalKnowledgeBaseType proto.PersonalKnowledgeBaseType `json:"personal_knowledge_base_type,omitempty"`
	Visibility                proto.KnowledgeBaseVisibility   `json:"visibility,omitempty"` // 可见性
	Title                     string                          `json:"title,omitempty"`
	Content                   string                          `json:"content,omitempty"`
	Abstract                  string                          `json:"abstract,omitempty"`
	Tags                      []string                        `json:"tags,omitempty"`
	Scene                     proto.KnowledgeBaseScene        `json:"scene,omitempty"`
	KnowledgeBaseDescription  string                          `json:"knowledge_base_desc,omitempty"`
}

type PersonalKnowledgeBase struct {
	Id                        int64                           `json:"id,omitempty"`
	MemberId                  int64                           `json:"member_id,omitempty"`
	PersonalKnowledgeBaseId   int64                           `json:"personal_knowledge_base_id,omitempty"`
	PersonalKnowledgeBaseType proto.PersonalKnowledgeBaseType `json:"personal_knowledge_base_type,omitempty"`
	PersonalKnowledgeBaseName string                          `json:"personal_knowledge_base_name,omitempty"`
}

type CommonKnowledgeBase struct {
	Id                       int64                           `json:"id,omitempty"`
	MemberId                 int64                           `json:"member_id,omitempty"`
	KnowledgeBaseId          int64                           `json:"knowledge_base_id,omitempty"`
	KnowledgeBaseType        proto.PersonalKnowledgeBaseType `json:"knowledge_base_type,omitempty"`
	KnowledgeBaseName        string                          `json:"knowledge_base_name,omitempty"`
	KnowledgeBaseDescription string                          `json:"knowledge_base_desc,omitempty"`
	KnowledgeBaseVisibility  string                          `json:"knowledge_base_visibility"`
}
