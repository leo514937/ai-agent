package root

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 获取挂载用户详细信息
type MembersInfoLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.AuthorInfo]
	authorDescService author.AuthorDescService
}

func NewMembersInfoLogic(name string, config map[string]string) *MembersInfoLogic {
	res := &MembersInfoLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.AuthorInfo](name, config),
	}
	res.authorDescService = author.DefaultAuthorDescService
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

func (m *MembersInfoLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) ([]*model.AuthorInfo, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.MembersInfoLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	var result []*model.AuthorInfo
	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(m.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", m.GetName())
		return result, nil
	}

	memberIds := requestCtx.GetBizContext().GetCurrReferenceMount().GetMountMembers()
	memberDetail := m.authorDescService.BatchGetAuthorDetail(ctx, memberIds)

	for _, memberId := range memberIds {
		if _, ok := memberDetail[memberId]; !ok {
			continue
		}
		result = append(result, &model.AuthorInfo{
			MemberId:          memberId,
			MemberName:        memberDetail[memberId].AuthorName,
			MemberDescription: memberDetail[memberId].Description,
		})
	}

	// 保存tracing
	m.saveTracing(startTime, memberIds, result, requestCtx)

	return result, nil
}

func (m *MembersInfoLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], memberMetas []*model.AuthorInfo) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.MembersInfoLogic.realMergeUser")
	defer span.Finish()

	requestCtx.GetBizContext().SetAuthorMetaInfo(memberMetas)
	return nil
}

func (m *MembersInfoLogic) saveTracing(startTime int64, memberIds []int64, result []*model.AuthorInfo, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   m.GetName(),
		LogicInput:  util.Int64SliceToString(memberIds),
		LogicOutput: []string{util.GetJSONIgnoreError(result)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(m.GetName(), logicTracing)
}
