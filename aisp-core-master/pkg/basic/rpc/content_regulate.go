package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content-regulate-core/content_regulate_core_thrift"
	regulate "git.in.zhihu.com/one-rpc-go/thrift-content-regulate-core/content_regulate_core_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

const (
	// 场景码
	SceneCodeRAI              = "AI_EXPANSION_SUMMARY"   // AI 摘要生成管控场景，AI 拓展词生成规则+会员/商广内容过滤
	SceneCodeSearch           = "SEARCH"                 // 搜索场景
	SceneCommercialCodeSearch = "SEARCH_COMMERCIAL"      // 搜索商业场景
	SceneCodeAiTabPrefabWord  = "AI_TAB_PREDEFINED_WORD" // 预制词

	// 子场景码
	SubSceneCodeDEFAULT = "default" // 默认都用 default。只有在 ab 试验等特殊情况会用其他的

	// 访客流通指令
	VisitorCirculate = "visitor_circulate"
	// 访客流通指令 - 不需要回源删除
	VisitorCirculateWithoutDel = "visitor_circulate_without_del"
	VisitorCirculateCommercial = "visitor_circulate_commercial"

	// 不可流通
	InstructionValueDisable = content_regulate_core_thrift.InstructionValue_DISABLE
)

type ContentRegulateRPC interface {
	BatchGetValidInstruction(ctx context.Context, sceneCode string, subSceneCode string, allKeys []model.Content) map[model.Content]map[string]string
}

var RegulateContentTypeMap = map[content.DocType_Type]string{
	content.DocType_Question:     regulate.ContentTypeQuestion,
	content.DocType_Answer:       regulate.ContentTypeAnswer,
	content.DocType_Article:      regulate.ContentTypeArticle,
	content.DocType_ZVideo:       regulate.ContentTypeZVideo,
	content.DocType_Club:         regulate.ContentTypeClub,
	content.DocType_Column:       regulate.ContentTypeColumn,
	content.DocType_Topic:        regulate.ContentTypeTopic,
	content.DocType_Pin:          regulate.ContentTypePin,
	content.DocType_EduSection:   regulate.ContentTypeEduSection,
	content.DocType_AiPrefabWord: regulate.ContentTypeAIPredefinedWord,
}

var RegulateContentTypeRevertMap map[string]content.DocType_Type

func init() {
	RegulateContentTypeRevertMap = make(map[string]content.DocType_Type)
	for key, value := range RegulateContentTypeMap {
		RegulateContentTypeRevertMap[value] = key
	}
}
