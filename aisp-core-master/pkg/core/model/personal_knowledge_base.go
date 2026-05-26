package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
)

type KnowledgeBaseInfo struct {
	KnowledgeBaseId       int64
	KnowledgeBaseName     string
	KnowledgeBaseType     proto.PersonalKnowledgeBaseType
	KnowledgeBaseTypeName string
	Total                 int64
	UserUploadCount       int64
	ZhihuCount            int64
	WebPageCount          int64
	Docs                  []*KbDocMeta
	Description           string
	CreatedAt             string
	UpdatedAt             string
}
type KbDocMeta struct {
	Idx        int
	DocId      int64
	DocType    aiContent.DocType_Type
	DocTypeStr string
	Url        string
	Title      string
	JoinedTime int64
}

type UniversalKnowledgeBaseInfo struct {
	KnowledgeBaseName        string
	KnowledgeBaseDescription string
	KnowledgeBaseType        enums.KnowledgeBaseType
	Order                    int
}

type AuthorInfo struct {
	MemberId          int64
	MemberName        string
	MemberDescription string
}
