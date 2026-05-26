package rpc

import (
	"context"
	"reflect"
	"strings"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"git.in.zhihu.com/zrec/zrec-utils/util"
	"github.com/samber/lo"
)

type TagCoreGRPC interface {

	// BatchGetTag 批量获取标签
	BatchGetTag(ctx context.Context, sceneCode SceneCode, appGroupCode AppGroupCode, itemKeys []model.Content) map[model.Content]*tag_core.ObjectProfile
}

// AppGroupCode GroupCode
type AppGroupCode string

// SceneCode 场景码
type SceneCode string

var TagCoreDefTags = []string{"人文", "娱乐", "数码"}

// 视频相关标签名和标签值
const (
	AppGroupCode_AiUserInterest  AppGroupCode = "ai_user_interest"
	AppGroupCode_AiUserSurvey    AppGroupCode = "ai_user_survey"
	AppGroupCode_AiUserFeature   AppGroupCode = "ai_user_feature"
	AppGroupCode_AiContentTag    AppGroupCode = "ai_content_tag"
	AppGroupCode_AiNewbieFeature AppGroupCode = "ai_newbie_tags"
	AppGroupCode_AiUserRecall    AppGroupCode = "ai_user_for_recall" // aisp 使用场景码
	AppGroupCode_Ai_daily        AppGroupCode = "ailab_core_zhihu_today"
)

// 创作者相关
const (
	TagCoreCreatorDocLevel = "creator_doc_level"
)

// 各类 default 值
const (
	TagCoreDefaultIntTagValue   = 0
	TagCoreDefaultFloatTagValue = 0.0
	TagCoreDefaultStrTagValue   = ""
)

// 内容相关
const (
	TagCoreTheme                        = "theme"                           // theme标签
	TagCoreCodeAiTopic                  = "ai_topic"                        // ai算法为内容打标的话题 对应cp中的aiTopic cp的userTopic、UserTopicV2废弃
	TagCoreCategoryFirst                = "category_first"                  // 内容的一级领域分类
	TagCoreCategorySecond               = "category_second"                 // 内容的二级领域分类
	TagCoreBayesFirstCategory           = "bayes_firstcategory"             // bayes 一级领域分类
	TagCoreBayesSecondCategory          = "bayes_secondcategory"            // bayes 二级领域分类
	TagCoreContentInformation           = "content_information"             // 内容信息量
	TagCoreInterestWord                 = "interest_word"                   // 兴趣关键词interest_word
	TagCoreUserGuide                    = "newuserguide_pin"                // 新手引导-自动生成想法
	TagCoreAnniversary                  = "anniversary_pin"                 // 周年贴
	TagCoreGeneralStoryUnfinishedStatus = "general_story_unfinished_status" // 社区故事内容未完结状态
	TagCoreGeneralStoryUnfinished       = "general_story_unfinished"        // 社区故事内容未完结状态
	TagCoreGeneralStory                 = "general_story"                   // 社区故事内容

	TagCoreSchoolName = "school_name"                     // 问题中包含学校名称
	BusinessTag       = "commercial_content_business_tag" //商业类型

	TagCoreJobSeasonQuestionType = "question_type_zhichang" // 职场季问题类型标签
	TagCoreOpRecRecallQuestion   = "op_question_rec_recall" // 运营打标问题标签

	TagCoreContentTrafficControl    = "content_traffic_control" // 红绿区流通等级的标识
	TagCoreContentTrafficControlT1  = 1
	TagCoreContentTrafficControlT2  = 2
	TagCoreContentTrafficControlT99 = 99

	TagCoreContentSubjectiveLevel   = "content_subjective_level" // 内容分级标签
	TagCoreContentSubjectiveLevelA1 = 1
	TagCoreContentSubjectiveLevelA2 = 2
	TagCoreContentSubjectiveLevelA3 = 3
	TagCoreContentSubjectiveLevelA4 = 4
	TagCoreContentSubjectiveLevelA5 = 5

	TagCoreMaybeCreatedByAI = "maybe_created_by_ai" // 可能由AI生成的内容

	//answer_property
	TagCoreAnswerProperty         = "answer_property" // 回答者属性，包括「亲自答」「相关方答」「官方回应」「知友辟谣」
	TagCoreAnswerPropertyInPerson = "亲自答"             // 回答者属性，包括「亲自答」「相关方答」「官方回应」「知友辟谣」
)

// 图片相关
const (
	TagCoreImgUncomfortable = "img_uncomfortable" // 图片引人不适
	TagCoreImgQrcode        = "img_qrcode"        // 图片是二维码
	TagCoreImgEmoji         = "img_emoji"         // 图片是表情包
)

const (
	TagCoreYesValue = "YES"
	TagCoreNoValue  = "NO"
)

// 短内容相关
const (
	TagCoreLimitPin              = "limit_recommend_pin"             // 打标为限制流通的短内容
	TagCoreRecommendPin          = "recommend_pin"                   // 可公域流通短内容
	TagCoreFollowerRecommendPin  = "follower_recommend_pin"          // 只能在关注群体流通的短内容
	TagCoreRecommendHighPin      = "recommend_high_pin"              // 可加量流通短内容
	TagCoreRecommendAvailablePin = "recommend_avail_pin"             // 可用流通短内容
	TagCorePinSelected           = "pin_selected"                    // 精选优质内容
	TagCoreImageClarity          = "short_content_image_clarity"     // 图片清晰度
	TagCoreFaceExist             = "short_content_image_face_exists" // 图片人脸个数
	TagCoreImageMainColor        = "short_content_image_main_color"  // 图片主色调
	TagCoreImageClarityHigh      = "high"                            // 高清晰度
	TagCoreImageClarityMedium    = "medium"                          // 中清晰素
	TagCoreImageClarityLow       = "low"                             // 低清晰度
	TagCoreMainColorCold         = "cold"                            // 冷
	TagCoreMainColorWarm         = "warm"                            // 中
	TagCoreMainColorMiddle       = "middle"                          // 暖
	TagCoreNonFace               = 0                                 // 无人脸
	TagCoreOneFace               = 1                                 // 一人脸
	TagCoreMultiFace             = 2                                 // 多人脸
)

// 用户相关
const (
	TagCoreTextThemeLongTerm  = "text_theme_long_term"  // 图文长期兴趣 theme
	TagCoreTextThemeRealTime  = "text_theme_realtime"   // 图文实时兴趣 theme
	TagCoreTextThemeShortTerm = "text_theme_short_term" // 图文短期兴趣 theme

	TagCoreZvideoLongTermAffinity     = "zvideo_long_term_affinity"      // 视频长期用户亲密度
	TagCoreZvideoRealtimeAffinity     = "zvideo_realtime_affinity"       // 视频实时用户亲密度
	TagCoreTextLongTermAffinity       = "text_long_term_affinity"        // 图文长期用户亲密度
	TagCoreTextRealtimeAffinity       = "text_realtime_affinity"         // 图文短期用户亲密度
	TagCoreTextLongTermAiTopic        = "text_long_term_ai_topic"        // 图文话题长期兴趣 ai topic
	TagCoreTextRealtimeAiTopic        = "text_realtime_ai_topic"         // 图文话题短期兴趣 ai topic
	TagCoreTextRealtimeCategoryFirst  = "text_realtime_category_first"   // 图文实时一级兴趣领域
	TagCoreTextLongTermCategoryFirst  = "text_long_term_category_first"  // 图文长期一级兴趣领域
	TagCoreTextRealtimeCategorySecond = "text_realtime_category_second"  // 用户图文二级领域实时兴趣
	TagCoreTextLongTermCategorySecond = "text_long_term_category_second" // 用户图文二级领域长期兴趣
	TagCoreTextBayesFirstLongTerm     = "text_bayes_first_long_term"     // 贝叶斯一级图文长期兴趣
	TagCoreTextBayesFirstShortTerm    = "text_bayes_first_short_term"    // 贝叶斯一级图文短期兴趣
	TagCoreTextBayesFirstRealtime     = "text_bayes_first_realtime"      // 贝叶斯一级图文实时兴趣

	TagCoreCreateLongTermCategoryFirst  = "create_long_term_category_first"  // 用户创作一级领域兴趣
	TagCoreCreateLongTermCategorySecond = "create_long_term_category_second" // 用户创作二级领域兴趣
	TagCoreCreateLongTermAiTopic        = "create_long_term_ai_topic"        // 用户创作话题兴趣
	TagCoreCreateThemeShortTerm         = "create_theme_short_term"
	TagCoreCreateThemeLongTerm          = "create_theme_long_term"
	TagCoreCreateInterestWordLongTerm   = "create_interest_word_long_term"
	TagCoreCreateInterestWordShortTerm  = "create_interest_word_short_term"

	TagCoreAge             = "ai_user_age"     // 用户年龄
	TagCoreJuvenile        = "Juvenile"        // 18 岁以下
	TagCoreSmallYoungster  = "SmallYoungster"  // 18-24岁
	TagCoreMiddleYoungster = "MiddleYoungster" // 24-30岁
	TagCoreBigYoungster    = "BigYoungster"    // 30-40岁
	TagCoreMiddleAge       = "MiddleAge"       // 40 岁以上

	TagCoreGender = "ai_user_gender" // 用户性别
	TagCoreFemale = "Female"         // 女性
	TagCoreMale   = "Male"           // 男性

	TagCoreResidentCity = "user_resident_city" // 用户城市等级

	TagCoreUmengGaokaoIdentity          = "umeng_gaokao_identity"           // 友盟高考身份
	TagCoreSelfProductionGaokaoIdentity = "self_production_gaokao_identity" // 增长侧高考身份（自产 ）
	TagCoreGaokaoIdentityStudent        = "student"                         // 高考身份标签值 - 学生
	TagCoreGaokaoIdentityParent         = "parent"                          // 高考身份标签值 - 家长

	TagCoreTimelinessInterest = "timeliness_interest" // 用户对时效内容的兴趣打分

	TagCoreFollowPushBlackUser = "follow_push_black_user" // 关注推荐-作弊用户（需要过滤）
	TagCoreFollowPushRiskUSer  = "follow_push_risk_user"  // 关注推荐作弊用户（需要降权分发）

	TagCoreUserProvince              = "ocation_province"       // 用户 地理位置&省份
	TagCoreUserCampus                = "user_campus"            // 校园用户
	TagCoreUserCampusGradJobTagValue = "应届找工作"                  // 校园用户标签值: 应届找工作
	TagCoreGaokaoCreator             = "gk_creator"             // 高考潜力创作者标签
	TagCoreNoSupportGKQuestion       = "no_support_gk_question" // 不扶持高考问题

	// 高考潜力用户扶持退场标签及标签值
	TagCoreGaokaoCreatorExit           = "gk_creator_exit" // 高考潜力用户扶持退场标签
	GaokaoCreatorExitLowWeightTagValue = "低权重扶持"           // 权重扶持
	GaokaoCreatorExitNoSupportTagValue = "完全不扶持"           // 低权重扶持

	// 路由职场季用户标签
	TagCoreJobSeasonCreatorOut = "user_zhichang_out" // 「职场季」活动退场用户
)

// 商业标记
const (
	TagCoreGoodPriceNews           = "good_price_news"                 // 好价爆料
	TagCoreOwnBrandOnlineRetailers = "own_brand_online_retailers"      // 自有品牌电商
	TagCorePrivateOnlineRetailers  = "private_online_retailers"        // 自营电商
	TagCoreEducationContent        = "education_content"               // 教育内容
	TagCoreZhiPlusOptional         = "zhi_plus_optional"               // 知 + 自选
	TagCoreShoppingGuideContents   = "shopping_guide_contents"         // 好物推荐
	TagCoreCommercialContent       = "commercial_content_business_tag" //商业内容标识
	TagCoreValueCommercialCheese   = "invite"                          //商业内容-「芝士」
	TagCoreValueCommercialRecruit  = "recruit"                         //商业内容-「招募」
)

// 视频用户消费等级标签值
const (
	TagCoreVideoConsumeHeavyUser    = "1" // 视频重度用户
	TagCoreVideoConsumePreferUser   = "2" // 视频偏好用户
	TagCoreVideoConsumeActionUser   = "3" // 视频互动性用户
	TagCoreVideoConsumeMiddleUser   = "4" // 视频中度用户
	TagCoreVideoConsumeShallowUser  = "5" // 视频浅消费用户
	TagCoreVideoConsumeNegativeUser = "6" // 视频被动用户
)

// 图文相关标签名和标签值
const (
	TagCoreKnowledgeAcquisitionContent  = "knowledge_acquisition_content"  // 知识类获得感
	TagCoreOpinionAcquisitionContent    = "opinion_acquisition_content"    // 见解类获得感
	TagCoreExperienceAcquisitionContent = "experience_acquisition_content" // 经历类获得感
	TagCoreNoAcquisitionContent         = "no_acquisition_content"         // 非获得感内容
)

// TODO 后续需要考虑 是否需要过滤字段
//var TagNeedFilterFields = mapset.NewSet()

const (
	SceneCode_AiUserInterest SceneCode = "ai_user_interest"
	SceneCode_Ai_Daily       SceneCode = "ai_community_integration"
)

// todo 目前视频回答无专门的DocType, 无法映射到ObjType
var DocTypeToObjTypeMap = map[content.DocType_Type]tag_core.ObjType_Type{
	content.DocType_Unknown:     tag_core.ObjType_Unknown,
	content.DocType_Member:      tag_core.ObjType_User,
	content.DocType_Topic:       tag_core.ObjType_Topic,
	content.DocType_Question:    tag_core.ObjType_Question,
	content.DocType_Answer:      tag_core.ObjType_Answer,
	content.DocType_Column:      tag_core.ObjType_Column,
	content.DocType_Article:     tag_core.ObjType_Article,
	content.DocType_Comment:     tag_core.ObjType_Comment,
	content.DocType_RoundTable:  tag_core.ObjType_RoundTable,
	content.DocType_ZVideo:      tag_core.ObjType_ZVideo,
	content.DocType_Video:       tag_core.ObjType_Video,
	content.DocType_Image:       tag_core.ObjType_Image,
	content.DocType_Club:        tag_core.ObjType_Club,
	content.DocType_Drama:       tag_core.ObjType_Drama,
	content.DocType_EBook:       tag_core.ObjType_Ebook,
	content.DocType_PaidMagzine: tag_core.ObjType_PaidMagzine,
	content.DocType_Ad:          tag_core.ObjType_AD,
	content.DocType_Pin:         tag_core.ObjType_Pin,
	content.DocType_EduSection:  tag_core.ObjType_EduSection,
	content.DocType_Query:       tag_core.ObjType_Query,
}

var DocTypeToObjTypeRevertMap map[tag_core.ObjType_Type]content.DocType_Type

func DocTypeToObjType(docType content.DocType_Type) tag_core.ObjType_Type {
	if objType, exists := DocTypeToObjTypeMap[docType]; exists {
		return objType
	}
	return tag_core.ObjType_Unknown
}

func ObjTypeToDocType(objType tag_core.ObjType_Type) content.DocType_Type {
	if docType, exists := DocTypeToObjTypeRevertMap[objType]; exists {
		return docType
	}
	return content.DocType_Unknown
}

// 解析某个 tagcode 对应的 tagValues
func GetTagValues(tags *tag_core.Tags, singleTagTopK int) []string {

	if tags == nil {
		return []string{}
	}

	items := (*tags).TagItems
	if items == nil || len(items) == 0 {
		return []string{}
	}

	infos := items[0].TagValueInfos
	if infos == nil || len(infos) == 0 {
		return []string{}
	}

	defaultTopK := len(infos)
	if singleTagTopK > 0 {
		defaultTopK = zrecUtil.Min(singleTagTopK, len(infos))
	}

	infos = infos[:defaultTopK]
	tagsArr := lo.Map(infos, func(item *tag_core.TagValueInfo, index int) string {
		return item.TagValue
	})
	return lo.Filter(tagsArr, func(item string, _ int) bool {
		return strings.TrimSpace(item) != ""
	})
}

func GetSingleValueByTagNameWithDefaultValue(tagsMap map[string]*tag_core.Tags, tagName string, defaultValue interface{}) interface{} {
	return GetSingleValueByTagNameAndVerWithDefaultValue(tagsMap, tagName, "", defaultValue)
}

func GetSingleValueByTagNameAndVerWithDefaultValue(tagsMap map[string]*tag_core.Tags, tagName string, tagVersion string, defaultValue interface{}) interface{} {
	if len(tagsMap) == 0 {
		return defaultValue
	}
	if _, exist := tagsMap[tagName]; !exist { // 标签不存在
		return defaultValue
	}

	tagItems := tagsMap[tagName].GetTagItems()
	if len(tagItems) == 0 {
		return defaultValue
	}

	var tagValueInfos []*tag_core.TagValueInfo
	if tagVersion == "" {
		tagValueInfos = tagItems[0].GetTagValueInfos() // 单item的valueInfo获取
	} else {
		for _, tagItem := range tagItems {
			if tagItem.GetTagVersion() == tagVersion {
				tagValueInfos = tagItem.GetTagValueInfos()
				break
			}
		}
	}

	if len(tagValueInfos) == 0 {
		return defaultValue
	}

	tagValue := tagValueInfos[0].GetTagValue()
	defaultValueT := reflect.ValueOf(defaultValue)
	switch defaultValueT.Kind() {
	case reflect.String:
		return tagValue
	case reflect.Int:
		value, err := util.String2Int(tagValue)
		if err != nil {
			return defaultValue
		}
		return value
	case reflect.Float64:
		value, err := util.String2Float64(tagValue)
		if err != nil {
			return defaultValue
		}
		return value
	default:
		return tagValue // 默认返回 string
	}
}
func init() {
	DocTypeToObjTypeRevertMap = make(map[tag_core.ObjType_Type]content.DocType_Type)
	for key, value := range DocTypeToObjTypeMap {
		DocTypeToObjTypeRevertMap[value] = key
	}

	// 初始化需要过滤的字段
	//TagNeedFilterFields.Add("category_first")
	//TagNeedFilterFields.Add("category_second")
	//TagNeedFilterFields.Add("interest_word")
	//TagNeedFilterFields.Add("theme")
	//TagNeedFilterFields.Add("ai_topic")
}
