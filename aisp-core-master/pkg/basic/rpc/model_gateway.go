package rpc

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-model_gateway/model_gateway"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/errors"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/provider" // 保证provider注册
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type ModelGatewayRouter struct {
	provider   *modelapi.ModelRouter
	gatewayrpc modelapi.ModelTarget
	engine     modelapi.ModelTarget
}

func (r ModelGatewayRouter) GenerateImage(ctx context.Context, req *dto.GenerateImageRequest) (*dto.GenerateImageResponse, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.GenerateImage", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	span.LogFields(log.Message("GenerateImage start."), log.Json("req", req))

	endpoint, err := r.GetModelEndpoint(ctx, req.ModelName)
	if err != nil {
		log.Errorf(ctx, "GetModelEndpoint error. err: %+v ", err)
		return nil, err
	}

	if endpoint == nil {
		return r.gatewayrpc.GenerateImage(ctx, req)
	}

	return endpoint.GenerateImage(ctx, req)
}

func (r ModelGatewayRouter) generateImageByChat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.generateImageByChat", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	span.LogFields(log.Message("generateImageByChat start."),
		log.Json("req", req),
	)

	if len(req.Messages) == 0 {
		return nil, errors.ErrInvalidArgument
	}

	generateImageRequest := &dto.GenerateImageRequest{
		ModelName: req.ModelName,
		Prompt:    req.Messages[len(req.Messages)-1].Content,
		Images:    req.Messages[len(req.Messages)-1].Images,
		Hyperparams: dto.GenerateImageHyperparams{
			Size:  "SIZE_1024",
			Count: 1,
			Extra: map[string]interface{}{
				"iw": 2,
			},
		},
	}

	generateImageResponse, err := r.gatewayrpc.GenerateImage(ctx, generateImageRequest)
	if err != nil {
		return nil, err
	}

	resp := &dto.ChatResponse{
		ModelName: req.ModelName,
		Content:   strings.Join(generateImageResponse.Images, "\n"),
		Usage: &dto.ChatResponseUsage{
			InputTokenCount:  1000,
			OutputTokenCount: 1000,
		},
	}

	return resp, nil
}

func (r ModelGatewayRouter) getAIProfile(ctx context.Context, modelName string) string {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "basic.rpc.ModelGatewayRouter.getAIProfile",
		"modelName": modelName,
	})
	rawAIProfileConfig := config.GetString("model_gateway.ai_profile", string(lo.Must(json.Marshal(map[string]string{}))))
	AIProfileConfig := make(map[string]string)
	err := json.Unmarshal([]byte(rawAIProfileConfig), &AIProfileConfig)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to unmarshal system config")
	}
	aiProfile := AIProfileConfig[modelName]
	if aiProfile != "" {
		aiProfile = strings.ReplaceAll(aiProfile, "{{ .current_time_str }}", time.Now().Format("2006年1月2日"))
	}
	return aiProfile
}

func (r ModelGatewayRouter) getTestModelName(ctx context.Context, modelName string) string {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "basic.rpc.ModelGatewayRouter.getTestModelName",
		"modelName": modelName,
	})

	isTest := false
	memberID := log.GetMemberIDFromContext(ctx)
	if memberID == 0 {
		return modelName
	}
	testMemberIDs := config.GetStringArray("model_gateway.test_member_ids", ",", []string{})
	for _, testMemberID := range testMemberIDs {
		if cast.ToInt64(testMemberID) == memberID {
			isTest = true
			break
		}
	}
	if !isTest {
		return modelName
	}

	testModelConfig := make(map[string]string)
	rawTestModelConfig := config.GetString("model_gateway.test_model", "{}")
	err := json.Unmarshal([]byte(rawTestModelConfig), &testModelConfig)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to unmarshal testModelConfig")
		return modelName
	}
	testModelName := testModelConfig[modelName]
	if testModelName == "" {
		return modelName
	}

	return testModelName
}

func (r ModelGatewayRouter) GetModelInfo(ctx context.Context, name string) (*dto.ModelInfo, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.GetModelInfo", log.Tags{
		"model_name": name,
	})
	defer span.Finish()

	allModel := make(map[string]*dto.ModelInfo)
	config.MustGetJson("model_gateway.model", &allModel)
	modelInfo := allModel[name]

	return modelInfo, nil
}

func (r ModelGatewayRouter) GetModelEndpoint(ctx context.Context, name string) (modelapi.ModelTarget, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.GetModelEndpoint", log.Tags{
		"model_name": name,
	})
	defer span.Finish()

	modelInfo, err := r.GetModelInfo(ctx, name)
	if err != nil {
		log.Errorf(ctx, "GetModelInfo error. err: %+v ", err)
		return nil, err
	}

	log.Infof(ctx, "GetModelInfo ok. modelInfo: %+v ", modelInfo)
	span.LogFields(log.Message("GetModelInfo ok."), log.Json("modelInfo", modelInfo))

	if modelInfo == nil {
		return nil, nil
	}

	target := r.provider.GetModelTarget(ctx, modelInfo)
	log.Infof(ctx, "GetModelTarget ok. target: %+v ", target)
	span.LogFields(log.Message("GetModelTarget ok."), log.Json("target", target))

	return target, nil
}

func (r ModelGatewayRouter) Chat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.Chat", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	// span.LogFields(log.Message("Chat start."),
	// 	log.Json("req", req),
	// )

	modelMap := make(map[string]string)
	config.MustGetJson("model_map", &modelMap)
	if modelMap[req.ModelName] != "" {
		req.ModelName = modelMap[req.ModelName]
	}

	waitModelLimiter(ctx, req.ModelName)

	span.LogFields(log.Message("waitModelLimiter done."))

	if aiProfile := r.getAIProfile(ctx, req.ModelName); aiProfile != "" {
		req.AIProfile = aiProfile
	}
	testModelName := r.getTestModelName(ctx, req.ModelName)
	req.ModelName = testModelName

	StatsdChatRequest(ctx, "Chat", req)

	endpoint, err := r.GetModelEndpoint(ctx, req.ModelName)
	if err != nil {
		log.Errorf(ctx, "GetModelEndpoint error. err: %+v ", err)

		log.StatsdError(ctx, "Chat.GetModelEndpoint", req.ModelName, "unknown")

		return nil, err
	}

	modelEngineModels := config.GetStringArray("model_engine_models", ",", []string{})

	var resp *dto.ChatResponse
	if endpoint != nil {
		resp, err = endpoint.Chat(ctx, req)
	} else if _, ok := proto.ChatModel_value[req.ModelName]; ok {
		resp, err = r.gatewayrpc.Chat(ctx, req)
	} else if _, ok := proto.ImageModel_value[req.ModelName]; ok {
		resp, err = r.generateImageByChat(ctx, req)
	} else if lo.Contains(modelEngineModels, req.ModelName) {
		resp, err = r.engine.Chat(ctx, req)
	} else {
		endpoint = r.provider.GetModelProxyTarget(ctx, req.ModelName)
		resp, err = endpoint.Chat(ctx, req)
	}

	if err != nil || resp == nil || (len(resp.Content) == 0 && len(resp.FunctionCallResults) == 0) {
		log.Errorf(ctx, "Chat error. err: %+v ", err)

		log.StatsdError(ctx, "Chat.Chat", req.ModelName, "unknown")

		// 新
		util.Increment(ctx, macro.CommonStatsPrefix+".model.%s.empty_resp.count", req.ModelName)
		// 老
		statsd.Increment(fmt.Sprintf(macro.OriginCommonStatsPrefix+".model.%s.empty_resp.count", log.GetSceneFromContext(ctx), req.ModelName))
		return nil, err
	}

	StatsdChatResponse(ctx, "Chat", resp)

	return resp, nil
}

func (r ModelGatewayRouter) Responses(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.Responses", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	// 获取模型端点
	endpoint, err := r.GetModelEndpoint(ctx, req.ModelName)
	if err != nil {
		log.Errorf(ctx, "GetModelEndpoint error. err: %+v ", err)
		log.StatsdError(ctx, "Responses.GetModelEndpoint", req.ModelName, "unknown")
		return nil, err
	}

	if endpoint == nil {
		log.Errorf(ctx, "GetModelEndpoint returned nil for model: %s", req.ModelName)
		return nil, fmt.Errorf("no endpoint found for model: %s", req.ModelName)
	}

	// 调用端点的 Responses 方法
	resp, err := endpoint.Responses(ctx, req)
	if err != nil {
		log.Errorf(ctx, "Responses error. err: %+v ", err)
		log.StatsdError(ctx, "Responses.Responses", req.ModelName, "unknown")
		return nil, err
	}

	return resp, nil
}

func (r ModelGatewayRouter) StreamResponses(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.StreamResponses", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	// 获取模型端点
	endpoint, err := r.GetModelEndpoint(ctx, req.ModelName)
	if err != nil || endpoint == nil {
		log.Errorf(ctx, "GetModelEndpoint error. err: %+v ", err)

		log.StatsdError(ctx, "StreamResponses.GetModelEndpoint", req.ModelName, "unknown")

		return nil
	}
	StatsdChatRequest(ctx, "StreamResponses", req)

	var innerChan <-chan util.Progress[*dto.ChatResponse]
	innerChan = endpoint.StreamResponses(ctx, req)
	respChan := make(chan util.Progress[*dto.ChatResponse])

	go func() {
		defer close(respChan)

		var lastResp *dto.ChatResponse
		for progress := range innerChan {
			if progress.E != nil {
				log.StatsdError(ctx, "StreamResponses.StreamResponses", req.ModelName, "unknown")
				if progress.E == context.Canceled {
					log.Infof(ctx, "StreamResponses error. err: %+v ", progress.E)
				} else {
					log.Errorf(ctx, "StreamResponses error. err: %+v ", progress.E)
				}
				respChan <- progress
				return
			}

			if progress.V != nil && progress.V.ReasoningContent == "" && progress.V.Content == "" &&
				progress.V.Usage != nil && lastResp != nil {
				lastResp.Usage = progress.V.Usage
				continue
			}

			respChan <- progress
			lastResp = progress.V
		}

		StatsdChatResponse(ctx, "StreamResponses", lastResp)
	}()

	return respChan
}

func StatsdChatRequest(ctx context.Context, op string, req *dto.ChatRequest) {
	if req == nil {
		return
	}

	scene := log.GetSceneFromContext(ctx)

	modelName := req.ModelName
	system := req.AIProfile
	all := system
	last := ""

	for _, message := range req.Messages {
		if message.Role == dto.ChatRequestMessageRoleUser {
			last = message.Content
		}
		all += "\n" + message.Role.ToProto().String() + "\n" + message.Content
	}

	// 老
	prefix := "aisp-core.scene." + scene + ".modelapi." + op + ".model." + modelName + ".input."
	statsd.RecordTime(prefix+"system.byte", int64(len(system)))
	statsd.RecordTime(prefix+"all.byte", int64(len(all)))
	statsd.RecordTime(prefix+"last.byte", int64(len(last)))

	statsd.RecordTime(prefix+"system.rune", int64(utf8.RuneCountInString(system)))
	statsd.RecordTime(prefix+"all.rune", int64(utf8.RuneCountInString(all)))
	statsd.RecordTime(prefix+"last.rune", int64(utf8.RuneCountInString(last)))

	// 新
	prefixNewFmt := "aisp-core.scene.%s.ab.%s.client.%s.traffic.%s.reference.%s.modelapi.%s.model.%s.input."
	util.TimingInMilSec(ctx, prefixNewFmt+"system.byte", float64(len(system)), op, modelName)
	util.TimingInMilSec(ctx, prefixNewFmt+"all.byte", float64(len(all)), op, modelName)
	util.TimingInMilSec(ctx, prefixNewFmt+"last.byte", float64(len(last)), op, modelName)
	util.TimingInMilSec(ctx, prefixNewFmt+"system.rune", float64(utf8.RuneCountInString(system)), op, modelName)
	util.TimingInMilSec(ctx, prefixNewFmt+"all.rune", float64(utf8.RuneCountInString(all)), op, modelName)
	util.TimingInMilSec(ctx, prefixNewFmt+"last.rune", float64(utf8.RuneCountInString(last)), op, modelName)

	log.Infof(ctx, " StatsdChatRequest. scene: %s, modelName: %s, system.rune: %d, all.rune: %d, last.rune: %d",
		scene, modelName, utf8.RuneCountInString(system), utf8.RuneCountInString(all), utf8.RuneCountInString(last))
}

func StatsdChatResponse(ctx context.Context, op string, resp *dto.ChatResponse) {
	scene := log.GetSceneFromContext(ctx)

	modelName := resp.ModelName
	content := resp.Content

	prefix := "aisp-core.scene." + scene + ".modelapi." + op + ".model." + modelName
	bizPrefix := macro.CommonStatsPrefix + ".model." + modelName

	statsd.RecordTime(prefix+".output.content.byte", int64(len(content)))
	statsd.RecordTime(prefix+".output.content.rune", int64(utf8.RuneCountInString(content)))

	if resp.Usage != nil {
		usage := resp.Usage

		inputToken := usage.InputTokenCount
		outputToken := usage.OutputTokenCount
		allToken := inputToken + outputToken

		// 业务token 打点
		util.TimingInMilSec(ctx, bizPrefix+".input.token", float64(inputToken))
		util.TimingInMilSec(ctx, bizPrefix+".output.token", float64(outputToken))
		util.TimingInMilSec(ctx, bizPrefix+".all.token", float64(allToken))

		statsd.RecordTime(prefix+".input.token.count", inputToken)
		statsd.RecordTime(prefix+".output.token.count", outputToken)
		statsd.RecordTime(prefix+".all.token.count", allToken)

		statsd.Count(prefix+".input.token.inc", int(inputToken))
		statsd.Count(prefix+".output.token.inc", int(outputToken))
		statsd.Count(prefix+".all.token.inc", int(allToken))
	}
}

func (r ModelGatewayRouter) StreamChat(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "rpc.ModelGatewayRouter.StreamChat", log.Tags{
		"model_name": req.ModelName,
	})
	defer span.Finish()

	modelMap := make(map[string]string)
	config.MustGetJson("model_map", &modelMap)
	if modelMap[req.ModelName] != "" {
		req.ModelName = modelMap[req.ModelName]
	}

	// span.LogFields(log.Message("StreamChat start."),
	// 	log.Json("req", req),
	// )

	if aiProfile := r.getAIProfile(ctx, req.ModelName); aiProfile != "" {
		req.AIProfile = aiProfile
	}
	testModelName := r.getTestModelName(ctx, req.ModelName)
	req.ModelName = testModelName

	StatsdChatRequest(ctx, "StreamChat", req)

	endpoint, err := r.GetModelEndpoint(ctx, req.ModelName)
	if err != nil {
		log.Errorf(ctx, "GetModelEndpoint error. err: %+v ", err)

		log.StatsdError(ctx, "StreamChat.GetModelEndpoint", req.ModelName, "unknown")

		return nil
	}

	modelEngineModels := config.GetStringArray("model_engine_models", ",", []string{})

	var innerChan <-chan util.Progress[*dto.ChatResponse]
	if endpoint != nil {
		innerChan = endpoint.StreamChat(ctx, req)
	} else if _, ok := proto.ChatModel_value[req.ModelName]; ok {
		innerChan = r.gatewayrpc.StreamChat(ctx, req)
	} else if lo.Contains(modelEngineModels, req.ModelName) {
		innerChan = r.engine.StreamChat(ctx, req)
	} else {
		endpoint = r.provider.GetModelProxyTarget(ctx, req.ModelName)
		innerChan = endpoint.StreamChat(ctx, req)
	}

	respChan := make(chan util.Progress[*dto.ChatResponse])

	go func() {
		defer close(respChan)

		var lastResp *dto.ChatResponse
		for progress := range innerChan {
			if progress.E != nil {
				log.StatsdError(ctx, "StreamChat.StreamChat", req.ModelName, "unknown")
				if progress.E == context.Canceled {
					log.Infof(ctx, "StreamChat error. err: %+v ", progress.E)
				} else {
					log.Errorf(ctx, "StreamChat error. err: %+v ", progress.E)
				}
				respChan <- progress
				return
			}

			// 针对 StreamChat 的特殊处理
			// sglang 部署模型 与 vllm 针对token统计返回结果不太一样
			// vllm Usage 结果会跟随在最后一次token中下发
			// sglang Usage 会额外在模型输出完毕后 在单独发送一次流式的统计消息，这里就简单粗暴的兜了一下
			if progress.V != nil && progress.V.ReasoningContent == "" && progress.V.Content == "" &&
				progress.V.Usage != nil && lastResp != nil {
				lastResp.Usage = progress.V.Usage
				continue
			}

			respChan <- progress
			lastResp = progress.V
		}

		StatsdChatResponse(ctx, "StreamChat", lastResp)
	}()

	return respChan
}

func NewModelGatewayRouter(provider *modelapi.ModelRouter, gatewayrpc, engine modelapi.ModelTarget) *ModelGatewayRouter {
	return &ModelGatewayRouter{
		provider:   provider,
		gatewayrpc: gatewayrpc,
		engine:     engine,
	}
}

var _ modelapi.ModelTarget = (*ModelGatewayRouter)(nil)

var DefaultModelGatewayRouter = NewModelGatewayRouter(modelapi.DefaultModelRouter, modelapi.NewModelGatewayRPC(), modelapi.NewModelEngineRPC())
