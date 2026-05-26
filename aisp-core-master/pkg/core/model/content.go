package model

import (
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"github.com/spf13/cast"
)

type Content struct {
	ContentID    int64
	URLToken     string
	ContentType  content.DocType_Type
	ZhiDaDocType proto.DocType
}

func (d *Content) String() string {
	return fmt.Sprintf("%s:%d:%s", d.ContentType.String(), cast.ToInt64(d.ContentID), d.URLToken)
}

func (d *Content) GetContentType() string {
	return GetContentType(d.GetDocType())
}
func (d *Content) GetDocType() content.DocType_Type {
	return d.ContentType
}

func (d *Content) GetZhiDaDocType() proto.DocType {
	return GetZhiDaDocType(d.GetDocType())
}

func NewContent(contentId int64, contentType content.DocType_Type, urlToken string) Content {
	return Content{
		ContentID:   contentId,
		ContentType: contentType,
		URLToken:    urlToken,
	}
}

var contentCoreContentTypeMap = map[content.DocType_Type]string{
	content.DocType_Question:        content_core_thrift.ContentTypeQuestion,
	content.DocType_Answer:          content_core_thrift.ContentTypeAnswer,
	content.DocType_Article:         content_core_thrift.ContentTypeArticle,
	content.DocType_ZVideo:          content_core_thrift.ContentTypeZVideo,
	content.DocType_Topic:           content_core_thrift.ContentTypeTopic,
	content.DocType_Pin:             content_core_thrift.ContentTypePin,
	content.DocType_EduSection:      content_core_thrift.ContentTypeEduSection,
	content.DocType_AiPrefabWord:    content_core_thrift.ContentTypeAIPredefinedWord,
	content.DocType_Paper:           content_core_thrift.ContentTypePaper,
	content.DocType_ZhiDaUserUpload: content_core_thrift.ContentTypeZhiDaUserUpload,
	content.DocType_Webpage:         content_core_thrift.ContentTypeExternalWebpage,
	content.DocType_CrawlerWebpage:  content_core_thrift.ContentTypeCrawlerWebpage,
}
var contentCoreContentTypeReverseMap map[string]content.DocType_Type

var searchVerticalAndContentTypeMap = map[search_service_thrift.Vertical]string{
	search_service_thrift.Vertical_QUESTION: content_core_thrift.ContentTypeQuestion,
	search_service_thrift.Vertical_ZVIDEO:   content_core_thrift.ContentTypeZVideo,
	search_service_thrift.Vertical_TOPIC:    content_core_thrift.ContentTypeTopic,
	search_service_thrift.Vertical_PIN:      content_core_thrift.ContentTypePin,
}
var searchVerticalAndContentTypeReverseMap map[string]search_service_thrift.Vertical

var zhiDaDocTypeMap = map[content.DocType_Type]proto.DocType{
	content.DocType_Answer:           proto.DocType_ANSWER,
	content.DocType_Article:          proto.DocType_ARTICLE,
	content.DocType_Knowledge:        proto.DocType_USER_KNOWLEDGE,
	content.DocType_UniversalOffSite: proto.DocType_UNIVERSAL_OFFSITE,
	content.DocType_Paper:            proto.DocType_PAPER,
	content.DocType_ZhiDaUserUpload:  proto.DocType_ZHI_DA_USER_UPLOAD,
	content.DocType_Comment:          proto.DocType_COMMENT,
	content.DocType_Webpage:          proto.DocType_EXTERNAL_WEBPAGE,
	content.DocType_InternalDoc:      proto.DocType_INTERNAL_DOC,
	content.DocType_AispUserUpload:   proto.DocType_AISP_USER_UPLOAD,
}
var zhiDaDocTypeAndContentTypeReverseMap map[proto.DocType]content.DocType_Type

var docTypeNameMap = map[content.DocType_Type]string{
	content.DocType_Question:        "问题",
	content.DocType_Answer:          "回答",
	content.DocType_Article:         "文章",
	content.DocType_ZVideo:          "视频",
	content.DocType_Pin:             "想法",
	content.DocType_Paper:           "论文",
	content.DocType_ZhiDaUserUpload: "用户上传文件",
	content.DocType_AispUserUpload:  "上传文件",
	content.DocType_Webpage:         "网页",
	content.DocType_Link:            "网页",
}
var docTypeNameMapReverseMap map[string]content.DocType_Type

func init() {
	contentCoreContentTypeReverseMap = make(map[string]content.DocType_Type)
	for key, value := range contentCoreContentTypeMap {
		contentCoreContentTypeReverseMap[value] = key
	}

	searchVerticalAndContentTypeReverseMap = make(map[string]search_service_thrift.Vertical)
	for key, value := range searchVerticalAndContentTypeMap {
		searchVerticalAndContentTypeReverseMap[value] = key
	}

	zhiDaDocTypeAndContentTypeReverseMap = make(map[proto.DocType]content.DocType_Type)
	for key, value := range zhiDaDocTypeMap {
		zhiDaDocTypeAndContentTypeReverseMap[value] = key
	}

	docTypeNameMapReverseMap = make(map[string]content.DocType_Type)
	for key, value := range docTypeNameMap {
		docTypeNameMapReverseMap[value] = key
	}
}

func NewContentWithDocType(contentId int64, docType content.DocType_Type) Content {
	return Content{
		ContentID:   contentId,
		ContentType: docType,
	}
}
func NewContentWithContentType(contentId int64, contentType string) Content {
	return Content{
		ContentID:   contentId,
		ContentType: GetDocType(contentType),
	}
}
func NewContentWithToken(urlToken string, contentType string) Content {
	return Content{
		URLToken:    urlToken,
		ContentType: GetDocType(contentType),
	}
}
func NewContentWithZhiDaDocType(contentId string, zhiDaDocType proto.DocType) (Content, bool) {
	docType := GetDocTypeByZhiDaType(zhiDaDocType)
	if docType == content.DocType_Unknown {
		return Content{}, false
	}

	contentIdInt, err := cast.ToInt64E(contentId)
	if err != nil {
		return Content{}, false
	}
	return NewContentWithDocType(contentIdInt, docType), true
}

func GetDocType(contentType string) content.DocType_Type {
	docType, isOk := contentCoreContentTypeReverseMap[contentType]
	if !isOk {
		docType = content.DocType_Unknown
	}
	return docType
}

func GetDocTypeFromStr(docTypeStr string) content.DocType_Type {
	return content.DocType_Type(content.DocType_Type_value[docTypeStr])
}

func GetContentType(docType content.DocType_Type) string {
	contentType, isOK := contentCoreContentTypeMap[docType]
	if !isOK {
		contentType = "UNKNOWN"
	}
	return contentType
}

func GetZhiDaDocType(docType content.DocType_Type) proto.DocType {
	zhiDaDocType, isOK := zhiDaDocTypeMap[docType]
	if !isOK {
		zhiDaDocType = proto.DocType_UNKNOWN_DOCTYPE
	}
	return zhiDaDocType
}

func GetDocTypeByZhiDaType(zhiDaDocType proto.DocType) content.DocType_Type {
	docType, isOK := zhiDaDocTypeAndContentTypeReverseMap[zhiDaDocType]
	if !isOK {
		docType = content.DocType_Unknown
	}
	return docType
}

func GetDocTypeName(docType content.DocType_Type) string {
	docTypeName, isOK := docTypeNameMap[docType]
	if !isOK {
		docTypeName = ""
	}
	return docTypeName
}
