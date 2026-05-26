package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

// type RequestCtx[C any] data_frame.RequestContext[C, entities.User, entities.Item]

type BaseLogic[C any] struct {
	*framework.ConsumeLogic[C, entities.User, entities.Item]

	RealDoFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item]) error

	inputNames  []string
	outputNames []string

	PreProcessFunc  func(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item]) error
	PostProcessFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item]) error
}

func NewBaseLogic[C any](name string, config map[string]string) *BaseLogic[C] {
	res := &BaseLogic[C]{
		ConsumeLogic: framework.NewConsumeLogic[C, entities.User, entities.Item](name, config),
	}
	res.ConsumeFunc = res.consumeFunc

	// 目前框架不支持获取inputNames和outputNames，业务算子这里支持下，是个临时方案
	res.inputNames = util.SplitNamesStringToArray(config[conf.ConfigInputNames])
	res.outputNames = util.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	res.PreProcessFunc = res.defaultPreProcess
	res.PostProcessFunc = res.defaultPostProcess
	return res
}

func (b *BaseLogic[C]) GetInputName(index int) string {
	if index < 0 || index >= len(b.inputNames) {
		return ""
	}

	return b.inputNames[index]
}

func (b *BaseLogic[C]) GetInputSize() int {
	return len(b.inputNames)
}

func (b *BaseLogic[C]) InputNamesLength() int {
	return len(b.inputNames)
}

func (b *BaseLogic[C]) GetOutputName(index int) string {
	if index < 0 || index >= len(b.outputNames) {
		return ""
	}

	return b.outputNames[index]
}

func (b *BaseLogic[C]) consumeFunc(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	if b.RealDoFunc == nil {
		panic("implement RealConsumeFunc")
	}

	if b.PreProcessFunc != nil {
		err := b.PreProcessFunc(ctx, requestCtx)
		if err != nil {
			log.WithError(ctx, err)
		}
	}

	realDoResult := b.RealDoFunc(ctx, requestCtx)

	if b.PostProcessFunc != nil {
		err := b.PostProcessFunc(ctx, requestCtx)
		if err != nil {
			log.WithError(ctx, err)
		}
	}

	return realDoResult
}

func (b *BaseLogic[C]) defaultPreProcess(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item]) error {
	return nil
}

func (b *BaseLogic[C]) defaultPostProcess(ctx context.Context, requestCtx *data_frame.RequestContext[C, entities.User, entities.Item]) error {
	return nil
}
