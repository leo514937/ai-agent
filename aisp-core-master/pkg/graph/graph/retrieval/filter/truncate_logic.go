package filter

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// TruncateLogic  通用的截断算子
// @logicAuthor: quanrui
// @logicInfo: 通用的截断算子
// @logicConfig: 0 | truncate size
type TruncateLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewTruncateLogic(name string, config map[string]string) *TruncateLogic {
	res := &TruncateLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.limit
	return res
}

func (l *TruncateLogic) limit(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	span, ctx, logCtx, _ := logic_context.InitLogicContext(ctx, requestCtx, l.GetName(), "filter.TruncateLogic")

	span, ctx, _ = log.StartChildSpanWithContext(ctx, "filter.TruncateLogic.limit")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	var truncateSize = cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.TruncateSize))

	constant.DataInputNodeLog.Infof(logCtx, "input size: %d. truncate size: %d", len(items), truncateSize)

	if truncateSize != 0 && len(items) > truncateSize {
		items = items[:truncateSize]
	}

	constant.DataOutputNodeLog.Infof(logCtx, "output size: %d", len(items))

	return items, nil
}
