package security

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	frameworkLog "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

// RedLineLogic 红线必答逻辑
// @logicAuthor: wanghao
// @logicInfo: 红线必答
// @logicOutput: 0 | 红线必答的结果，string
type RedLineLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]

	FetchFunc     func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]string, error)
	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[entities.Item], res string) error
}

func NewRedLineLogic(name string, config map[string]string) *RedLineLogic {
	l := &RedLineLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	l.MappingFunc = l.fetchA
	l.BizNodeType = "fetch"

	l.FetchFunc = l.fetch
	l.ItemMergeFunc = l.itemMerge
	return l
}

func (u *RedLineLogic) fetchA(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	var resMap map[data_frame.UniqueId]string
	var err error

	err = safe_group.SafeGoWait(u.OriginName(), func() error {
		resMap, err = u.FetchFunc(ctx, requestCtx, user, itemList)
		return err
	})

	if err != nil {
		frameworkLog.RecordErrStack(requestCtx.GetCommonContext(), u.GetBizNodeType(), u.OriginName(), err)
		return itemList, nil
	}

	for _, item := range itemList {
		if res, ok := resMap[*item.GetCommonItem().GetUniqueId()]; ok {
			_ = u.ItemMergeFunc(ctx, item, res)
		}
	}

	return itemList, nil
}

func (u *RedLineLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]string, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.RedLineLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	// 是否允许被豁免
	allowExempt := true
	if allowExemptStr := requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.ConfigAllowExempt); allowExemptStr != "" {
		allowExempt = cast.ToBool(allowExemptStr)
	}

	resMap := make(map[data_frame.UniqueId]string)
	recordMap := make(map[string]string)
	// 豁免安全的，不过红线必答
	if allowExempt && requestCtx.GetBizContext().GetIsExemptSecurity() {
		constant.DataOutputNodeLog.Infof(logCtx, "豁免")
		return resMap, nil
	}
	for _, item := range items {
		redLine, hit := operation_base.DefaultOperationBaseService.HitRedLineAnswer(ctx, item.GetBizItem().Text)

		if hit {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = redLine
			recordMap[item.GetBizItem().Text] = redLine
			// 兼容下baseLogic
			requestCtx.DataMap().SetString(logCtx, u.GetOutputName(0), redLine)

			log.Infof(ctx, "hit redline answer. answer=%s", redLine)
		}

		log.StatsdCheckItem(ctx, "RedLineLogic.fetch.all", !hit)
	}

	span.LogFields(log.Message("RedLineLogic fetch done."), log.Json("resp", resMap))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(recordMap))

	return resMap, nil
}
func (u *RedLineLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res string) error {
	item.GetBizItem().GetSecurity().RedLine = res
	return nil
}
