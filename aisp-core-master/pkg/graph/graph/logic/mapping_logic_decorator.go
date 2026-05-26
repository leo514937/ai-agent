package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zag-driver/pkg/core/driver/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame/consts"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

var mappingRequireKey = []string{consts.ItemListIn_key, consts.ItemListOut_key}

// MappingLogicDecorator MappingLogic framework算子的装饰器，新增关于input、output的方法。适用于logic迁移过程中兼容。全部迁移BaseLogic后，不应该再使用
type MappingLogicDecorator[C, U, I any] struct {
	*logics.BasicLogic[C, U, I]

	itemListIn  string
	itemListOut string

	MappingFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I], user *data_frame.UserData[U], items []*data_frame.ItemData[I]) ([]*data_frame.ItemData[I], error)

	inputNames  []string
	outputNames []string
}

func NewMappingLogicDecorator[C, U, I any](name string, config map[string]string) *MappingLogicDecorator[C, U, I] {
	logics.RequireKeyCheck(mappingRequireKey, config)
	l := &MappingLogicDecorator[C, U, I]{
		BasicLogic:  logics.NewBasicLogic[C, U, I](name, config),
		itemListIn:  config[consts.ItemListIn_key],
		itemListOut: config[consts.ItemListOut_key],
	}
	l.BizNodeType = "mapping"
	l.RealExecFunc = l.RealExec

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	return l
}

func (r *MappingLogicDecorator[C, U, I]) Mapping(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I],
	user *data_frame.UserData[U], items []*data_frame.ItemData[I]) (res []*data_frame.ItemData[I], err error) {
	errPanic := safe_group.SafeGoWait(r.GetName(), func() error {
		res, err = r.MappingFunc(ctx, requestCtx, user, items)
		return err
	})
	if errPanic != nil {
		return items, errPanic
	}
	return
}

func (r *MappingLogicDecorator[C, U, I]) RealExec(ctx context.Context, param *data_frame.RequestContext[C, U, I]) error {
	user := param.GetCommonContext().GetLogicData(consts.User_key).(*data_frame.UserData[U])
	// itemList 可能 null，说明上游算子未返回数据
	itemList, _ := param.GetCommonContext().GetLogicData(r.itemListIn).([]*data_frame.ItemData[I])
	mappedItems, err := r.Mapping(ctx, param, user, itemList)
	param.GetCommonContext().SetLogicData(r.itemListOut, mappedItems)
	return err
}

func (r *MappingLogicDecorator[C, U, I]) GetInputName(index int) string {
	if index < 0 || index >= len(r.inputNames) {
		return ""
	}

	return r.inputNames[index]
}

func (r *MappingLogicDecorator[C, U, I]) InputNamesLength() int {
	return len(r.inputNames)
}

func (r *MappingLogicDecorator[C, U, I]) GetOutputName(index int) string {
	if index < 0 || index >= len(r.outputNames) {
		return ""
	}

	return r.outputNames[index]
}

func (r *MappingLogicDecorator[C, U, I]) GetOutputSize() int {
	return len(r.outputNames)
}

var _ logics.MappingProcess[data_frame.MockC, data_frame.MockU, data_frame.MockI] = (*MappingLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI])(nil)
var _ entities.NodeOperator[logics.GenericType] = (*framework.ConsumeLogic[data_frame.MockC, data_frame.MockU, data_frame.MockI])(nil)
