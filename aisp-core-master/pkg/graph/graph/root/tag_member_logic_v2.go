package root

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 获取用户 tagInfo

// MemberTagCoreV2Logic 用户标签
type MemberTagCoreV2Logic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, map[string]*tag_core.Tags]
	tagCoreRpc rpc.TagCoreGRPC
}

func NewMemberTagCoreV2Logic(name string, config map[string]string) *MemberTagCoreV2Logic {
	res := &MemberTagCoreV2Logic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, map[string]*tag_core.Tags](name, config),
	}
	res.FillUserFunc = res.fetch
	res.MergeUserFunc = res.merge
	res.tagCoreRpc = rpcImpl.NewTagCoreGrpcImpl()
	return res
}

func (m *MemberTagCoreV2Logic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) (map[string]*tag_core.Tags, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.fetch")

	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	resMap := make(map[string]*tag_core.Tags)

	sceneCode := rpc.SceneCode(requestCtx.GetBizContext().GetLogicConfig(m.GetName(), conf.TagCoreSceneCode))
	appGroupCode := rpc.AppGroupCode(requestCtx.GetBizContext().GetLogicConfig(m.GetName(), conf.TagCoreAppGroupCode))

	if sceneCode == "" || appGroupCode == "" {
		return resMap, nil
	}

	item := model.Content{
		ContentID:   requestCtx.GetBizContext().RequestInfo().GetMemberId(),
		ContentType: content2.DocType_Member,
	}
	tagCoreResult := m.tagCoreRpc.BatchGetTag(ctx, sceneCode, appGroupCode, []model.Content{item})
	if tagMap, exist := tagCoreResult[item]; exist {
		resMap = tagMap.GetTags()
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", resMap)

	return resMap, nil
}

func (m *MemberTagCoreV2Logic) merge(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], tags map[string]*tag_core.Tags) error {

	// 设置用户标签到 user meta
	user.GetBizUser().UserMeta().SetTagInfo(tags)
	return nil
}
