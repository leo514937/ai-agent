package logic

import (
	"context"

	graph_entities "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zag-driver/pkg/core/driver/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame/consts"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

var filterRequireKey = []string{consts.ItemListIn_key, consts.ItemListOut_key}

// FilterLogicDecorator 输入输出 key 相同
type FilterLogicDecorator[C, U, I any] struct {
	*logics.BasicLogic[C, U, I]

	itemListIn  string
	itemListOut string

	FilterFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[graph_entities.RequestContext, U, I], user *data_frame.UserData[U], items []*data_frame.ItemData[I]) ([]*data_frame.ItemData[I], error)

	inputNames  []string
	outputNames []string
}

func NewFilterLogicDecorator[U, I any](name string, config map[string]string) *FilterLogicDecorator[graph_entities.RequestContext, U, I] {
	logics.RequireKeyCheck(mappingRequireKey, config)
	l := &FilterLogicDecorator[graph_entities.RequestContext, U, I]{
		BasicLogic:  logics.NewBasicLogic[graph_entities.RequestContext, U, I](name, config),
		itemListIn:  config[consts.ItemListIn_key],
		itemListOut: config[consts.ItemListOut_key],
	}
	l.BizNodeType = "filter"
	l.RealExecFunc = l.RealExec
	l.ConditionCallback = func(ctx context.Context, requestCtx *data_frame.RequestContext[graph_entities.RequestContext, U, I], res bool) {
		if !res {
			requestCtx.GetCommonContext().TransferLogicData(l.itemListIn, l.itemListOut)
		}
	}

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	return l
}

func (r *FilterLogicDecorator[C, U, I]) Filter(ctx context.Context, requestCtx *data_frame.RequestContext[graph_entities.RequestContext, U, I],
	user *data_frame.UserData[U], items []*data_frame.ItemData[I]) (res []*data_frame.ItemData[I], err error) {

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", r.GetName())
		return items, nil
	}

	errPanic := safe_group.SafeGoWait(r.GetName(), func() error {
		res, err = r.FilterFunc(ctx, requestCtx, user, items)
		return err
	})
	if errPanic != nil {
		return items, errPanic
	}
	return
}

func (r *FilterLogicDecorator[C, U, I]) RealExec(ctx context.Context, requestCtx *data_frame.RequestContext[graph_entities.RequestContext, U, I]) error {
	user := requestCtx.GetCommonContext().GetLogicData(consts.User_key).(*data_frame.UserData[U])
	// items 可能 null，说明上游算子未返回数据
	items, _ := requestCtx.GetCommonContext().GetLogicData(r.itemListIn).([]*data_frame.ItemData[I])
	itemList, err := r.Filter(ctx, requestCtx, user, items)
	requestCtx.GetCommonContext().SetLogicData(r.itemListOut, itemList)
	return err
}

func (r *FilterLogicDecorator[C, U, I]) GetInputName(index int) string {
	if index < 0 || index >= len(r.inputNames) {
		return ""
	}

	return r.inputNames[index]
}

func (r *FilterLogicDecorator[C, U, I]) InputNamesLength() int {
	return len(r.inputNames)
}

func (r *FilterLogicDecorator[C, U, I]) GetOutputName(index int) string {
	if index < 0 || index >= len(r.outputNames) {
		return ""
	}

	return r.outputNames[index]
}

var _ logics.FilterProcess[graph_entities.RequestContext, data_frame.MockU, data_frame.MockI] = (*FilterLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI])(nil)
var _ entities.NodeOperator[logics.GenericType] = (*FilterLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI])(nil)
