package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type FetcherLogicDecorator[C, U, I, R any] struct {
	*framework.MappingLogic[C, U, I]

	FetchFunc     func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I], user *data_frame.UserData[U], items []*data_frame.ItemData[I]) (map[data_frame.UniqueId]R, error)
	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[I], res R) error

	inputNames  []string
	outputNames []string
}

func NewFetcherLogicDecorator[C, U, I, R any](name string, config map[string]string) *FetcherLogicDecorator[C, U, I, R] {
	l := &FetcherLogicDecorator[C, U, I, R]{
		MappingLogic: framework.NewMappingLogic[C, U, I](name, config),
	}
	l.MappingFunc = l.fetch
	l.BizNodeType = "fetch"

	l.inputNames = util2.SplitNamesStringToArray(config[conf.ConfigInputNames])
	l.outputNames = util2.SplitNamesStringToArray(config[conf.ConfigOutputNames])
	return l
}

func (r *FetcherLogicDecorator[C, U, I, R]) fetch(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, I],
	user *data_frame.UserData[U], itemList []*data_frame.ItemData[I]) ([]*data_frame.ItemData[I], error) {

	var resMap map[data_frame.UniqueId]R
	var err error

	err = safe_group.SafeGoWait(r.OriginName(), func() error {
		resMap, err = r.FetchFunc(ctx, requestCtx, user, itemList)
		return err
	})

	if err != nil {
		log.RecordErrStack(requestCtx.GetCommonContext(), r.GetBizNodeType(), r.OriginName(), err)
		return itemList, nil
	}

	for _, item := range itemList {
		if res, ok := resMap[*item.GetCommonItem().GetUniqueId()]; ok {
			_ = r.ItemMergeFunc(ctx, item, res)
		}
	}

	return itemList, nil
}

func (r *FetcherLogicDecorator[C, U, I, R]) GetInputName(index int) string {
	if index < 0 || index >= len(r.inputNames) {
		return ""
	}

	return r.inputNames[index]
}

func (r *FetcherLogicDecorator[C, U, I, R]) InputNamesLength() int {
	return len(r.inputNames)
}

func (r *FetcherLogicDecorator[C, U, I, R]) GetOutputName(index int) string {
	if index < 0 || index >= len(r.outputNames) {
		return ""
	}

	return r.outputNames[index]
}

var _ logics.MappingProcess[data_frame.MockC, data_frame.MockU, data_frame.MockI] = (*FetcherLogicDecorator[data_frame.MockC, data_frame.MockU, data_frame.MockI, data_frame.MockR])(nil)
