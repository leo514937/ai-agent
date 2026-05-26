package util

import (
	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
)

func GetContentTrafficControlTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreContentTrafficControl, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetGeneralStoryTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreGeneralStory, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetImgUncomfortableTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreImgUncomfortable, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetImgQrcodeTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreImgQrcode, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetImgEmojiTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreImgEmoji, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetContentSubjectiveLevelTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreContentSubjectiveLevel, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetMaybeCreatedByAITagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreMaybeCreatedByAI, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetAnswerPropertyTagValue(tagsMap map[string]*tag_core.Tags) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreAnswerProperty, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetCreatorDocLevelTagValue(tagsMap map[string]*tag_core.Tags) int {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, rpc.TagCoreCreatorDocLevel, rpc.TagCoreDefaultIntTagValue).(int)
}

func GetTagValueString(tagsMap map[string]*tag_core.Tags, tagKey string) string {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, tagKey, rpc.TagCoreDefaultStrTagValue).(string)
}

func GetTagValueInt(tagsMap map[string]*tag_core.Tags, tagKey string) int {
	return rpc.GetSingleValueByTagNameWithDefaultValue(tagsMap, tagKey, rpc.TagCoreDefaultIntTagValue).(int)
}
