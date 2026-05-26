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

// type RequestCtx[C any] data_frame.RequestContext[C, U, entities.Item]

type ConsumerLogicDecorator[C, U any] struct {
	*framework.ConsumeLogic[C, U, entities.Item]

	RealDoFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item], user *data_frame.UserData[U]) error

	inputNames  []string
	outputNames []string

	PreProcessFunc  func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item], user *data_frame.UserData[U]) error
	PostProcessFunc func(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item], user *data_frame.UserData[U]) error
}

func NewConsumerLogicDecorator[C, U any](name string, config map[string]string) *ConsumerLogicDecorator[C, U] {
	res := &ConsumerLogicDecorator[C, U]{
		ConsumeLogic: framework.NewConsumeLogic[C, U, entities.Item](name, config),
	}
	res.ConsumeFunc = res.consumeFunc

	// 目前框架不支持获取inputNames和outputNames，业务算子这里支持下，是个临时方案
	res.inputNames = util.SplitNamesStringToArray(config[conf.ConfigInputNames])
	res.outputNames = util.SplitNamesStringToArray(config[conf.ConfigOutputNames])

	res.PreProcessFunc = res.defaultPreProcess
	res.PostProcessFunc = res.defaultPostProcess
	return res
}

func (b *ConsumerLogicDecorator[C, U]) GetInputName(index int) string {
	if index < 0 || index >= len(b.inputNames) {
		return ""
	}

	return b.inputNames[index]
}

func (b *ConsumerLogicDecorator[C, U]) GetInputSize() int {
	return len(b.inputNames)
}

func (b *ConsumerLogicDecorator[C, U]) InputNamesLength() int {
	return len(b.inputNames)
}

func (b *ConsumerLogicDecorator[C, U]) GetOutputName(index int) string {
	if index < 0 || index >= len(b.outputNames) {
		return ""
	}

	return b.outputNames[index]
}

func (b *ConsumerLogicDecorator[C, U]) consumeFunc(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item],
	user *data_frame.UserData[U]) error {
	if b.RealDoFunc == nil {
		panic("implement RealConsumeFunc")
	}

	if b.PreProcessFunc != nil {
		err := b.PreProcessFunc(ctx, requestCtx, user)
		if err != nil {
			log.WithError(ctx, err)
		}
	}

	realDoResult := b.RealDoFunc(ctx, requestCtx, user)

	if b.PostProcessFunc != nil {
		err := b.PostProcessFunc(ctx, requestCtx, user)
		if err != nil {
			log.WithError(ctx, err)
		}
	}

	return realDoResult
}

func (b *ConsumerLogicDecorator[C, U]) defaultPreProcess(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item], user *data_frame.UserData[U]) error {
	return nil
}

func (b *ConsumerLogicDecorator[C, U]) defaultPostProcess(ctx context.Context, requestCtx *data_frame.RequestContext[C, U, entities.Item], user *data_frame.UserData[U]) error {
	return nil
}
