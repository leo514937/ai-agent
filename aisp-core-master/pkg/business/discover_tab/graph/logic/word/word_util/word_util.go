package word_util

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

func WordDocType2DocType(pDocType proto.DocType) content.DocType_Type {
	docType := content.DocType_Unknown
	switch pDocType {
	case proto.DocType_ANSWER:
		docType = content.DocType_Answer
	case proto.DocType_ARTICLE:
		docType = content.DocType_Article
	default:
	}
	return docType
}
