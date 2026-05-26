package macro

import (
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

const (
	CardAbstractLimit int = 100
)

var docType2CardDocTypeMap = map[content.DocType_Type]string{
	content.DocType_Answer:          content_core_thrift.ContentTypeAnswer,
	content.DocType_Article:         content_core_thrift.ContentTypeArticle,
	content.DocType_Paper:           content_core_thrift.ContentTypePaper,
	content.DocType_ZhiDaUserUpload: content_core_thrift.ContentTypeZhiDaUserUpload,
	content.DocType_Webpage:         content_core_thrift.ContentTypeExternalWebpage,
	content.DocType_Member:          "MEMBER",
}
var docType2CardDocTypeReverseMap map[string]content.DocType_Type

func init() {
	docType2CardDocTypeReverseMap = make(map[string]content.DocType_Type)
	for key, value := range docType2CardDocTypeMap {
		docType2CardDocTypeReverseMap[value] = key
	}
}

func DocType2CardDocType(docType content.DocType_Type) string {
	contentType, isOK := docType2CardDocTypeMap[docType]
	if !isOK {
		contentType = "UNKNOWN"
	}
	return contentType
}

func CardDocType2DocType(cardContentType string) content.DocType_Type {
	contentType, isOK := docType2CardDocTypeReverseMap[cardContentType]
	if !isOK {
		contentType = content.DocType_Unknown
	}
	return contentType
}
