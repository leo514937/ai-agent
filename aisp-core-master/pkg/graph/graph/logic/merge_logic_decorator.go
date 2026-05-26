package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics"
	core_merger "git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

// MergeLogicDecorator MergeLogic framework算子的装饰器，新增关于input、output的方法。适用于logic迁移过程中兼容。全部迁移BaseLogic后，不应该再使用
type MergeLogicDecorator[C, U, I any] struct {
	*core_merger.ReduceLogic[C, U, I]
	MergeFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I],
		user *data_frame.UserData[U], itemLists [][]*data_frame.ItemData[I]) ([]*data_frame.ItemData[I], error)

	inputNames  []string
	outputNames []string
}

func NewMergeLogicDecorator[C, U, I any](name string, config map[string]string) *MergeLogicDecorator[C, U, I] {
	l := &MergeLogicDecorator[C, U, I]{
		ReduceLogic: core_merger.NewReduceLogic[C, U, I](name, config),
	}
	l.ReduceFunc = l.reduce

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	return l
}

func (r *MergeLogicDecorator[C, U, I]) reduce(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I],
	user *data_frame.UserData[U], itemLists [][]*data_frame.ItemData[I]) ([]*data_frame.ItemData[I], error) {

	var items []*data_frame.ItemData[I]
	var err error
	err = safe_group.SafeGoWait(r.OriginName(), func() error {
		items, err = r.MergeFunc(ctx, requestCtx, user, itemLists)
		return err
	})

	if err != nil {
		log.RecordErrStack(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), err)
	}

	log.RecordInt64(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), "before.size", int64(util.SizeOf(itemLists)))
	log.RecordInt64(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), "after.size", int64(len(items)))

	return items, nil
}

func (r *MergeLogicDecorator[C, U, I]) GetInputName(index int) string {
	if index < 0 || index >= len(r.inputNames) {
		return ""
	}

	return r.inputNames[index]
}

func (r *MergeLogicDecorator[C, U, I]) InputNamesLength() int {
	return len(r.inputNames)
}

func (r *MergeLogicDecorator[C, U, I]) GetOutputName(index int) string {
	if index < 0 || index >= len(r.outputNames) {
		return ""
	}

	return r.outputNames[index]
}

var _ logics.ReduceProcess[float64, float64, float64] = (*MergeLogicDecorator[float64, float64, float64])(nil)
