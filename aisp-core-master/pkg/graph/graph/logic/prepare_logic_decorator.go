package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zag-driver/pkg/core/driver/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

// PreparerLogicDecorator framework.PrepareLogic算子的装饰器，新增关于input、output的方法。适用于logic迁移过程中兼容。全部迁移BaseLogic后，不应该再使用
type PreparerLogicDecorator[C, U, I, R any] struct {
	*framework.UserLogic[C, U, I]

	FillUserFunc  func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I], user *data_frame.UserData[U]) (R, error)
	MergeUserFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I], user *data_frame.UserData[U], res R) error

	inputNames  []string
	outputNames []string
}

func NewPreparerLogicDecorator[C, U, I, R any](name string, config map[string]string) *PreparerLogicDecorator[C, U, I, R] {
	l := &PreparerLogicDecorator[C, U, I, R]{
		UserLogic: framework.NewUserLogic[C, U, I](name, config),
	}
	l.UserFunc = l.User
	l.BizNodeType = "preparer"

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])
	return l
}

func (r *PreparerLogicDecorator[C, U, I, R]) User(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I], user *data_frame.UserData[U]) error {

	var err error
	err = safe_group.SafeGoWait(r.OriginName(), func() error {
		res, e := r.FillUserFunc(ctx, requestCtx, user)
		if e == nil {
			e = r.MergeUserFunc(ctx, requestCtx, user, res)
		}
		return e
	})
	if err != nil {
		log.RecordErrStack(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), err)
	}
	return nil
}

func (r *PreparerLogicDecorator[C, U, I, R]) GetInputName(index int) string {
	if index < 0 || index >= len(r.inputNames) {
		return ""
	}

	return r.inputNames[index]
}

func (r *PreparerLogicDecorator[C, U, I, R]) InputNamesLength() int {
	return len(r.inputNames)
}

func (r *PreparerLogicDecorator[C, U, I, R]) GetOutputName(index int) string {
	if index < 0 || index >= len(r.outputNames) {
		return ""
	}

	return r.outputNames[index]
}

var _ logics.UserProcess[data_frame.MockC, data_frame.MockU, data_frame.MockI] = (*PreparerLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI, data_frame.MockR])(nil)
var _ entities.NodeOperator[logics.GenericType] = (*PreparerLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI, data_frame.MockR])(nil)
