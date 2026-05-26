package root

import (
	"context"
	"strings"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 查找用户当前的tags

// tagMemberLogic 配置
type tagMemberLogicConfig struct {
	// 场景码
	sceneCode rpc.SceneCode
	// appGroup
	appGroupCode rpc.AppGroupCode
	// contentType
	contentType content.DocType_Type
	// limit 数量
	limit int
}

func (c *tagMemberLogicConfig) ToJsonString() string {
	marshal, err := util.JsonMarshalByIgnoreHTML(c)
	if err != nil {
		return ""
	}
	return string(marshal)
}

// TagMemberLogic 用户标签
type TagMemberLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, []string]
	tagGrpcClient rpc.TagCoreGRPC
	config        *tagMemberLogicConfig
}

func NewTagMemberLogic(name string, config map[string]string) *TagMemberLogic {
	res := &TagMemberLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, []string](name, config),
	}

	res.FillUserFunc = res.getMemberTag
	res.MergeUserFunc = res.setMemberTag
	res.tagGrpcClient = rpcImpl.NewTagCoreGrpcImpl()

	res.config = &tagMemberLogicConfig{
		sceneCode:    rpc.SceneCode_AiUserInterest,
		appGroupCode: rpc.AppGroupCode_AiUserRecall,
		contentType:  content.DocType_Member,
		limit:        20,
	}
	return res
}

func (b *TagMemberLogic) getMemberTag(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.TagMemberLogic.getMemberTag")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "getMemberTag",
	})
	logger.Debugf(ctx, "getTag 算子开始执行 config => %s", b.config.ToJsonString())

	modelContent := model.Content{
		ContentID:   requestCtx.GetBizContext().RequestInfo().GetMemberId(),
		ContentType: b.config.contentType,
	}

	tagMap := b.tagGrpcClient.BatchGetTag(
		ctx,
		b.config.sceneCode,
		b.config.appGroupCode,
		[]model.Content{modelContent})
	tagProfile := tagMap[modelContent]
	if tagProfile == nil {
		return []string{}, nil
	}

	// 过滤标签
	tags := filterTagMap(tagProfile, b.config.limit)
	return tags, nil
}

func (b *TagMemberLogic) setMemberTag(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], tags []string) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.TagMemberLogic.setMemberTag")
	defer span.Finish()
	span.LogFields(log.Message("start."),
		entities.LogUser(user),
		log.Int64("tags_len", int64(len(tags))),
		log.OmittedString("tags", strings.Join(tags, ",")),
	)

	// 设置用户标签到 user meta
	user.GetBizUser().UserMeta().SetTags(tags)
	return nil
}

// 过滤标签
func filterTagMap(tagObjProfile *tag_core.ObjectProfile, limit int) []string {
	if tagObjProfile == nil {
		return rpc.TagCoreDefTags
	}

	// tagsMap
	tagsMap := tagObjProfile.Tags

	// 过滤
	tagThemeLongTermArr := rpc.GetTagValues(tagsMap[rpc.TagCoreTextThemeLongTerm], 10)
	tagThemeShortTermArr := rpc.GetTagValues(tagsMap[rpc.TagCoreTextThemeShortTerm], 10)
	tagThemeRealTimeArr := rpc.GetTagValues(tagsMap[rpc.TagCoreTextThemeRealTime], 20)
	// 标签去重合并
	tags := lo.Union(tagThemeLongTermArr, tagThemeShortTermArr, tagThemeRealTimeArr)
	if len(tags) == 0 {
		return rpc.TagCoreDefTags
	}

	// 随机抽取指定个数的 tag
	return util.RandomPick(tags, limit)
}
