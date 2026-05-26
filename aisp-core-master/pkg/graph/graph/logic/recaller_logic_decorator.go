package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	biz_log "git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/zreclog"
	"github.com/spf13/cast"
)

type DefaultRecallerDecorator[C, U, I any] struct {
	*framework.GetListLogic[C, U, I]

	RecallFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, U, I], user *data_frame.UserData[U]) ([]*data_frame.ItemData[I], error)

	inputNames  []string
	outputNames []string
}

func NewDefaultRecallerDecorator[C, U, I any](name string, config map[string]string) *DefaultRecallerDecorator[entities.RequestContext, U, I] {
	l := &DefaultRecallerDecorator[entities.RequestContext, U, I]{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, U, I](name, config),
	}
	l.GetListFunc = l.GetList
	l.BizNodeType = "recall"

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	return l
}

func (r *DefaultRecallerDecorator[C, U, I]) GetList(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, U, I], user *data_frame.UserData[U]) ([]*data_frame.ItemData[I], error) {
	var items []*data_frame.ItemData[I]

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.BaseConfigSkip))
	if skip {
		biz_log.Infof(ctx, "logic execute skip: %s", r.GetName())
		return items, nil
	}

	var err error
	err = safe_group.SafeGoWait(r.OriginName(), func() error {
		items, err = r.RecallFunc(ctx, requestCtx, user)
		return err
	})

	if err != nil {
		log.RecordErrStack(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), err)
	}

	log.RecordInt64(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), "recall_size", int64(len(items)))

	if len(items) == 0 {
		log.RecordCount(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName()+".recall_empty")
	}

	zreclog.Debugf(ctx, "recall %s size= %d", r.Name, len(items))

	return items, err
}

// var _ logics.GetListProcess[data_frame.MockC, data_frame.MockU, data_frame.MockI] = (*DefaultRecallerDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI])(nil)
