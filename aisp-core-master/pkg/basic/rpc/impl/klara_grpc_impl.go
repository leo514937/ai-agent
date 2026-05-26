package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	trition_client "git.in.zhihu.com/one-rpc-go/grpc-aisp_triton_inference/inference"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/impl"
	rpc2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

const textMaxLength = 512
const maxBatchSize = 1

var modelNameToConfig map[string]*modelConfig

var klaraRpcClientMap map[string]rpc.KlaraRpcClient

func init() {
	modelNameToConfig = map[string]*modelConfig{
		"ensemble": {
			input:   "input_text",
			output:  "embedding",
			target:  "bge-large-embeddig.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout: time.Millisecond * 1000,
		},
		"bge-embedding-ai-zhida-online": {
			input:    "input_text",
			realName: "ensemble",
			output:   "embedding",
			target:   "bge-embedding-ai-zhida-online.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 1000,
		},
		"bge-m3-common-for-zhida-online": { // bge m3 在线服务
			input:    "input_text",
			realName: "ensemble",
			output:   "dense_vecs",
			target:   "bge-m3-common-for-zhida-online.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 1000,
		},
		"bge-m3-common-for-zhida": { // bge m3 离线服务
			input:    "input_text",
			realName: "ensemble",
			output:   "dense_vecs",
			target:   "bge-m3-common-for-zhida.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 1000,
		},
		"ensemble_offline": {
			input:    "input_text",
			realName: "ensemble",
			output:   "embedding",
			target:   "bge-embedding-for-hot-contents.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 1000,
		},
		"bge-reranker": {
			input:    "input_text_pair",
			realName: "ensemble",
			output:   "scores",
			target:   "bge-reranker-ai-zhida-online.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 3000,
		},
		"bge-reranker-pro": {
			input:    "input_text_pair",
			realName: "ensemble",
			output:   "scores",
			target:   "bge-reranker-zhida-125k.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 5000,
		},
		"image-visual-embedding": {
			input:    "input_pair",
			realName: "ensemble",
			output:   "embedding",
			target:   "bge-visual-m3-image.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 2000,
		},
		"text-visual-embedding": {
			input:    "input_text",
			realName: "ensemble",
			output:   "embedding",
			target:   "bge-visual-m3-text.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 2000,
		},
		"bge-m3-token": {
			realName: "ensemble",
			target:   "bge-m3-token.jeeves-agi.klara.pek02.rack.zhihu.com:8080",
			timeout:  time.Millisecond * 2000,
		},
	}

	klaraRpcClientMap = make(map[string]rpc.KlaraRpcClient)
	for modelName := range modelNameToConfig {
		klaraRpcClientMap[modelName] = newDefaultKlaraGrpcClient(modelName)
	}
}

func GetBgeEmbeddingClient(modelName string) rpc.KlaraRpcClient {
	client := klaraRpcClientMap[modelName]
	if client == nil {
		client = klaraRpcClientMap["ensemble"]
	}

	return client
}

type modelConfig struct {
	input    string
	output   string
	target   string
	realName string
	timeout  time.Duration
}

type KlaraGrpcClient struct {
	grpcClient trition_client.GRPCInferenceServiceClient
	prometheus rpc2.Prometheus
	modelName  string
}

func newDefaultKlaraGrpcClient(modelName string) rpc.KlaraRpcClient {
	ctx := context.Background()
	config, ok := modelNameToConfig[modelName]
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", modelName)
		return nil
	}

	dialCtx, err := grpc.DialContext(ctx, config.target)
	if err != nil {
		log.Errorf(ctx, "dial %s failed. err: %+v", config.target, err)

		panic(err)
	}

	return &KlaraGrpcClient{
		grpcClient: trition_client.NewGRPCInferenceServiceClient(dialCtx),
		prometheus: impl.DefaultPrometheusImpl,
		modelName:  modelName,
	}
}

type Pair struct {
	First  string
	Second string
}

// BatchInferPairwiseScore texts 里每一个元素 []string 都是一个 pair
func (k *KlaraGrpcClient) BatchInferPairwiseScore(ctx context.Context, textsSlice [][]string) []float32 {
	return k.BatchInferPairwiseScoreBySize(ctx, textsSlice, 1)
}

func (k *KlaraGrpcClient) BatchInferPairwiseScoreBySize(ctx context.Context, textsSlice [][]string, batchSize int) []float32 {
	config, ok := modelNameToConfig[k.modelName]
	var inferResult = make([]float32, len(textsSlice))
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", k.modelName)
		return inferResult
	}
	// 只支持 pairwise
	if config.input != "input_text_pair" {
		log.Errorf(ctx, "func support input type input_text_pair only. but is %s", config.input)
		return inferResult
	}
	// 输入的每一个 pair 必须长度为 2，例如[["a","b"]]
	var inputPair []Pair
	for _, pair := range textsSlice {
		if len(pair) != 2 {
			log.Errorf(ctx, "pair's length must be 2. but is %d", len(pair))
			return inferResult
		}
		inputPair = append(inputPair, Pair{
			First:  pair[0],
			Second: pair[1],
		})
	}

	resultMap := map[Pair]float32{}
	safe_group.BatchGet(batchSize, inputPair, func(texts interface{}) interface{} {
		textsInput := texts.([]Pair)

		inferContents := &trition_client.InferTensorContents{
			BytesContents: lo.Flatten(lo.Map(textsInput, func(pair Pair, _ int) [][]byte {
				var result [][]byte
				result = append(result, []byte(pair.First))
				result = append(result, []byte(pair.Second))
				return result
			})),
		}

		inferNormalize := &trition_client.InferTensorContents{
			BoolContents: lo.RepeatBy(len(textsInput), func(index int) bool { return true }),
		}

		// Create request input tensors
		inferInputs := []*trition_client.ModelInferRequest_InferInputTensor{
			{
				Name:     config.input,
				Datatype: "BYTES",
				Shape:    []int64{int64(len(textsInput)), 2},
				Contents: inferContents,
			},
			{
				Name:     "normalize",
				Datatype: "BOOL",
				Shape:    []int64{int64(len(textsInput)), 1},
				Contents: inferNormalize,
			},
		}

		inferOutputs := []*trition_client.ModelInferRequest_InferRequestedOutputTensor{
			{
				Name: config.output,
			},
		}

		modelRealName := k.modelName
		if config.realName != "" {
			modelRealName = config.realName
		}
		modelInferRequest := &trition_client.ModelInferRequest{
			ModelName: modelRealName,
			Inputs:    inferInputs,
			Outputs:   inferOutputs,
		}

		newCtx, cancel := context.WithTimeout(ctx, config.timeout)
		defer cancel()
		startTime := time.Now()
		response, err := k.grpcClient.ModelInfer(newCtx, modelInferRequest)
		k.statsKlaraRequest(ctx, startTime, err != nil, config.target)

		if err != nil || response == nil || len(response.RawOutputContents) != 1 {
			log.WithError(ctx, err).Errorf(ctx, "c=%s", k.modelName)
			return nil
		}

		result := map[Pair]float32{}
		scores, err := util.ConvertFp16ByteToFloat32(response.RawOutputContents[0])
		if len(scores) != len(textsInput) {
			return nil
		}
		for idx, score := range scores {
			result[textsInput[idx]] = score
		}
		return result
	}, &resultMap)

	for idx, texts := range textsSlice {
		inferResult[idx] = resultMap[Pair{
			First:  texts[0],
			Second: texts[1],
		}]
	}

	return inferResult
}

func (k *KlaraGrpcClient) BatchInferBgeM3DenseEmb(ctx context.Context, contentSlice []string) [][]float32 {
	config, ok := modelNameToConfig[k.modelName]
	var inferResult = make([][]float32, len(contentSlice))
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", k.modelName)
		return inferResult
	}

	inferContents := &trition_client.InferTensorContents{
		BytesContents: lo.Map(contentSlice, func(text string, _ int) []byte {
			return []byte(text)
		}),
	}

	inferTrue := &trition_client.InferTensorContents{
		BoolContents: lo.RepeatBy(len(contentSlice), func(index int) bool { return true }),
	}

	inferFalse := &trition_client.InferTensorContents{
		BoolContents: lo.RepeatBy(len(contentSlice), func(index int) bool { return false }),
	}

	// Create request input tensors
	inferInputs := []*trition_client.ModelInferRequest_InferInputTensor{
		{
			Name:     "input_text",
			Datatype: "BYTES",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferContents,
		},
		{
			Name:     "return_dense",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferTrue,
		},
		{
			Name:     "return_sparse",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferFalse,
		},
		{
			Name:     "return_colbert",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferFalse,
		},
	}

	inferOutputs := []*trition_client.ModelInferRequest_InferRequestedOutputTensor{
		{
			Name: config.output,
		},
	}

	modelRealName := k.modelName
	if config.realName != "" {
		modelRealName = config.realName
	}
	modelInferRequest := &trition_client.ModelInferRequest{
		ModelName: modelRealName,
		Inputs:    inferInputs,
		Outputs:   inferOutputs,
	}

	newCtx, cancel := context.WithTimeout(ctx, config.timeout)
	defer cancel()
	startTime := time.Now()
	response, err := k.grpcClient.ModelInfer(newCtx, modelInferRequest)
	k.statsKlaraRequest(ctx, startTime, err != nil, config.target)

	if err != nil || response == nil || len(response.RawOutputContents) != 1 {
		log.WithError(ctx, err).Errorf(ctx, "c=%s", k.modelName)
		return nil
	}

	res := parseResponseSliceFloat(ctx, len(contentSlice), response.Outputs[0], response.RawOutputContents[0])

	return res
}

func (k *KlaraGrpcClient) BatchInferBgeM3Sparse(ctx context.Context, contentSlice []string) [][]rpc.SegWord {
	config, ok := modelNameToConfig[k.modelName]
	var inferResult = make([][]rpc.SegWord, len(contentSlice))
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", k.modelName)
		return inferResult
	}

	inferContents := &trition_client.InferTensorContents{
		BytesContents: lo.Map(contentSlice, func(text string, _ int) []byte {
			return []byte(text)
		}),
	}

	inferTrue := &trition_client.InferTensorContents{
		BoolContents: lo.RepeatBy(len(contentSlice), func(index int) bool { return true }),
	}

	inferFalse := &trition_client.InferTensorContents{
		BoolContents: lo.RepeatBy(len(contentSlice), func(index int) bool { return false }),
	}

	// Create request input tensors
	inferInputs := []*trition_client.ModelInferRequest_InferInputTensor{
		{
			Name:     "input_text",
			Datatype: "BYTES",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferContents,
		},
		{
			Name:     "return_dense",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferFalse,
		},
		{
			Name:     "return_sparse",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferTrue,
		},
		{
			Name:     "return_colbert",
			Datatype: "BOOL",
			Shape:    []int64{int64(len(contentSlice)), 1},
			Contents: inferFalse,
		},
	}

	inferOutputs := []*trition_client.ModelInferRequest_InferRequestedOutputTensor{
		{
			Name: "sparse_ids",
		},
		{
			Name: "sparse_vecs",
		},
		{
			Name: "sparse_tokens",
		},
	}

	modelRealName := k.modelName
	if config.realName != "" {
		modelRealName = config.realName
	}
	modelInferRequest := &trition_client.ModelInferRequest{
		ModelName: modelRealName,
		Inputs:    inferInputs,
		Outputs:   inferOutputs,
	}

	newCtx, cancel := context.WithTimeout(ctx, config.timeout)
	defer cancel()
	startTime := time.Now()
	response, err := k.grpcClient.ModelInfer(newCtx, modelInferRequest)
	k.statsKlaraRequest(ctx, startTime, err != nil, config.target)

	if err != nil || response == nil || len(response.RawOutputContents) == 0 {
		log.WithError(ctx, err).Errorf(ctx, "c=%s", k.modelName)
		return nil
	}

	tokenSlice := make([][]string, len(contentSlice))
	idSlicce := make([][]int64, len(contentSlice))
	scoreSlice := make([][]float32, len(contentSlice))

	for idx, output := range response.GetOutputs() {
		if output.GetName() == "sparse_tokens" {
			tokenSlice = parseResponsseSliceString(ctx, len(contentSlice), output, response.RawOutputContents[idx])
		}
		if output.GetName() == "sparse_ids" {
			idSlicce = parseResponsseSliceInt64(ctx, len(contentSlice), output, response.RawOutputContents[idx])
		}
		if output.GetName() == "sparse_vecs" {
			scoreSlice = parseResponseSliceFloat(ctx, len(contentSlice), output, response.RawOutputContents[idx])
		}
	}
	if !checkShapeEqual(tokenSlice, idSlicce, scoreSlice) {
		log.Errorf(ctx, "The shapes of tokenSlice, idSlicce, and scoreSlice are not equal.")
		return inferResult
	}

	// for 循环 tokenSlice、idSlicce、scoreSlice 组装成 [][]rpc.SegWord
	for i := range tokenSlice {
		var segWords []rpc.SegWord
		for j := range tokenSlice[i] {
			segWords = append(segWords, rpc.SegWord{
				Id:     idSlicce[i][j],
				Word:   tokenSlice[i][j],
				Weight: scoreSlice[i][j],
			})
		}
		inferResult[i] = segWords
	}

	return inferResult
}

func checkShapeEqual(arr1 [][]string, arr2 [][]int64, arr3 [][]float32) bool {
	if len(arr1) != len(arr2) || len(arr2) != len(arr3) {
		return false
	}
	for i := range arr1 {
		if len(arr1[i]) != len(arr2[i]) || len(arr2[i]) != len(arr3[i]) {
			return false
		}
	}
	return true
}

func (k *KlaraGrpcClient) BatchInferPairwiseEmbeddingBySize(ctx context.Context, contentSlice [][]string, batchSize int) [][]float32 {
	config, ok := modelNameToConfig[k.modelName]
	var inferResult = make([][]float32, len(contentSlice))
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", k.modelName)
		return inferResult
	}
	// 只支持 pairwise
	if config.input != "input_pair" {
		log.Errorf(ctx, "func support input type input_text_pair only. but is %s", config.input)
		return inferResult
	}
	// 输入的每一个 pair 必须长度为 2，例如[["a","b"]]
	var inputPair []Pair
	for _, pair := range contentSlice {
		if len(pair) != 2 {
			log.Errorf(ctx, "pair's length must be 2. but is %d", len(pair))
			return inferResult
		}
		inputPair = append(inputPair, Pair{
			First:  pair[0],
			Second: pair[1],
		})
	}

	resultMap := map[Pair][]float32{}
	safe_group.BatchGet(batchSize, inputPair, func(contents interface{}) interface{} {
		contentInput := contents.([]Pair)

		inferContents := &trition_client.InferTensorContents{
			BytesContents: lo.Flatten(lo.Map(contentInput, func(pair Pair, _ int) [][]byte {
				var result [][]byte
				result = append(result, []byte(pair.First))
				result = append(result, []byte(pair.Second))
				return result
			})),
		}

		// Create request input tensors
		inferInputs := []*trition_client.ModelInferRequest_InferInputTensor{
			{
				Name:     config.input,
				Datatype: "BYTES",
				Shape:    []int64{int64(len(contentInput)), 2},
				Contents: inferContents,
			},
		}

		inferOutputs := []*trition_client.ModelInferRequest_InferRequestedOutputTensor{
			{
				Name: config.output,
			},
		}

		modelRealName := k.modelName
		if config.realName != "" {
			modelRealName = config.realName
		}
		modelInferRequest := &trition_client.ModelInferRequest{
			ModelName: modelRealName,
			Inputs:    inferInputs,
			Outputs:   inferOutputs,
		}

		newCtx, cancel := context.WithTimeout(ctx, config.timeout)
		defer cancel()
		startTime := time.Now()
		response, err := k.grpcClient.ModelInfer(newCtx, modelInferRequest)
		k.statsKlaraRequest(ctx, startTime, err != nil, config.target)

		if err != nil || response == nil || len(response.RawOutputContents) != 1 {
			log.WithError(ctx, err).Errorf(ctx, "c=%s", k.modelName)
			return nil
		}

		output, index, ok := lo.FindIndexOf(response.Outputs, func(item *trition_client.ModelInferResponse_InferOutputTensor) bool {
			return item.Name == config.output
		})
		if !ok {
			log.WithError(ctx, err).Errorf(ctx, "model infer response error. modelName=%s", k.modelName)
			return nil
		}

		rawOutputContent := response.RawOutputContents[index]

		embeddingResp := parseResponseSliceFloat(ctx, len(contentInput), output, rawOutputContent)
		if len(embeddingResp) != len(contentInput) {
			return nil
		}

		result := map[Pair][]float32{}
		for idx, embedding := range embeddingResp {
			result[contentInput[idx]] = embedding
		}
		return result
	}, &resultMap)

	for idx, content := range contentSlice {
		inferResult[idx] = resultMap[Pair{
			First:  content[0],
			Second: content[1],
		}]
	}

	return inferResult
}

func (k *KlaraGrpcClient) BatchInferEmbedding(ctx context.Context, texts []string) [][]float32 {
	return k.BatchInferEmbeddingBySize(ctx, texts, maxBatchSize)
}

func (k *KlaraGrpcClient) BatchInferEmbeddingBySize(ctx context.Context, texts []string, batchSize int) [][]float32 {
	config, ok := modelNameToConfig[k.modelName]
	if !ok {
		log.Errorf(ctx, "modelName notExists. modelName=%s", k.modelName)
		return nil
	}
	formatTexts := lo.Map(texts, func(text string, _ int) string {
		str := []rune(text)
		return string(str[:zrecUtil.Min(textMaxLength, len(str))])
	})

	var inferResult [][]float32
	if len(texts) == 0 {
		return inferResult
	}

	resMap := map[string][]float32{}
	safe_group.BatchGet(batchSize, formatTexts, func(texts interface{}) interface{} {
		textStrs := texts.([]string)

		inferContents := &trition_client.InferTensorContents{
			BytesContents: lo.Map(textStrs, func(text string, _ int) []byte {
				return []byte(text)
			}),
		}

		batchSize := int64(len(textStrs))
		// Create request input tensors
		inferInputs := []*trition_client.ModelInferRequest_InferInputTensor{
			{
				Name:     config.input,
				Datatype: "BYTES",
				Shape:    []int64{batchSize, 1},
				Contents: inferContents,
			},
		}

		inferOutputs := []*trition_client.ModelInferRequest_InferRequestedOutputTensor{
			{
				Name: config.output,
			},
		}

		modelRealName := k.modelName
		if config.realName != "" {
			modelRealName = config.realName
		}
		modelInferRequest := &trition_client.ModelInferRequest{
			ModelName: modelRealName,
			Inputs:    inferInputs,
			Outputs:   inferOutputs,
		}

		newCtx, cancel := context.WithTimeout(ctx, config.timeout)
		defer cancel()
		startTime := time.Now()
		response, err := k.grpcClient.ModelInfer(newCtx, modelInferRequest)
		k.statsKlaraRequest(ctx, startTime, err != nil, config.target)

		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "model infer error. modelName=%s. error=%v", k.modelName, err)
			return nil
		}

		output, index, ok := lo.FindIndexOf(response.Outputs, func(item *trition_client.ModelInferResponse_InferOutputTensor) bool {
			return item.Name == config.output
		})
		if !ok {
			log.WithError(ctx, err).Errorf(ctx, "model infer response error. modelName=%s", k.modelName)
			return nil
		}

		rawOutputContent := response.RawOutputContents[index]

		return parseResponseMap(ctx, textStrs, output, rawOutputContent)
	}, &resMap)

	for _, text := range formatTexts {
		inferResult = append(inferResult, resMap[text])
	}
	return inferResult
}

func (k *KlaraGrpcClient) statsKlaraRequest(ctx context.Context, startTime time.Time, hasErr bool, url string) {
	isvcName, nameSpace, cluster := util.GetIsvcAndNameSpaceFromKlaraUrl(url)
	level := k.prometheus.CacheGetModelLevel(ctx, isvcName, cluster)

	status := macro.SUCCEED
	if hasErr {
		if ctx.Err() == context.Canceled {
			status = macro.CANCELED
		} else {
			status = macro.FAILED
		}
	}

	// 新
	util.Increment(ctx, macro.KlaraRequestCntStatsFmt, isvcName, nameSpace, status, "0")
	util.Timing(ctx, macro.KlaraRequestTotalTimeStatsFmt, time.Since(startTime), isvcName, nameSpace)

	// 老
	statsd.Increment(fmt.Sprintf(macro.OriginKlaraRequestCntStatsFmt, isvcName, nameSpace, level, status, 0))
	statsd.Timing(fmt.Sprintf(macro.OriginKlaraRequestTotalTimeStatsFmt, isvcName, nameSpace, level), time.Since(startTime))
}

func parseResponseMap(ctx context.Context, textStrs []string, output *trition_client.ModelInferResponse_InferOutputTensor,
	rawOutputContent []byte) map[string][]float32 {
	firstShape := int(output.GetShape()[0])
	secondShape := int(output.GetShape()[1])

	dataType := output.Datatype
	result := map[string][]float32{}
	switch dataType {
	case "FP32":
		float32Value, err := util.ConvertByteArrayToFloat32Array(rawOutputContent)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "ConvertByteArrayToFloat32Array error")
		}

		multiDimValue := util.Split1DArrayToMultiDArray(float32Value, firstShape, secondShape)
		if len(multiDimValue) != len(textStrs) {
			log.Errorf(ctx, "Split1DArrayToMultiDArray not equal")
		}

		for i, text := range textStrs {
			result[text] = multiDimValue[i]
		}
	default:
		log.Errorf(ctx, "error datatype. got dataType=%s", dataType)
	}

	return result
}

func parseResponseSliceFloat(ctx context.Context, inputLen int, output *trition_client.ModelInferResponse_InferOutputTensor,
	rawOutputContent []byte) [][]float32 {
	firstShape := int(output.GetShape()[0])
	secondShape := int(output.GetShape()[1])

	dataType := output.Datatype
	var result = make([][]float32, inputLen)
	switch dataType {
	case "FP32":
		float32Value, err := util.ConvertByteArrayToFloat32Array(rawOutputContent)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "ConvertByteArrayToFloat32Array error")
		}

		multiDimValue := util.Split1DArrayToMultiDArray(float32Value, firstShape, secondShape)
		if len(multiDimValue) != inputLen {
			log.Errorf(ctx, "Split1DArrayToMultiDArray not equal")
		}

		for i := 0; i < inputLen; i++ {
			result[i] = multiDimValue[i]
		}
	default:
		log.Errorf(ctx, "error datatype. got dataType=%s", dataType)
	}

	return result
}

func parseResponsseSliceInt64(ctx context.Context, inputLen int, output *trition_client.ModelInferResponse_InferOutputTensor,
	rawOutputContent []byte) [][]int64 {
	firstShape := int(output.GetShape()[0])
	secondShape := int(output.GetShape()[1])

	dataType := output.Datatype
	var result = make([][]int64, inputLen)
	switch dataType {
	case "INT64":
		int64Value, err := util.ConvertByteArrayToInt64Array(rawOutputContent)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "ConvertByteArrayToInt64Array error")
		}

		multiDimValue := util.Split1DArrayToMultiDArray(int64Value, firstShape, secondShape)
		if len(multiDimValue) != inputLen {
			log.Errorf(ctx, "Split1DArrayToMultiDArray not equal")
		}

		for i := 0; i < inputLen; i++ {
			result[i] = multiDimValue[i]
		}
	default:
		log.Errorf(ctx, "error datatype. got dataType=%s", dataType)
	}

	return result
}

func parseResponsseSliceString(ctx context.Context, inputLen int, output *trition_client.ModelInferResponse_InferOutputTensor, rawOutputContent []byte) [][]string {
	firstShape := int(output.GetShape()[0])
	secondShape := int(output.GetShape()[1])

	dataType := output.Datatype
	var result = make([][]string, inputLen)
	switch dataType {
	case "BYTES":
		stringValue, err := util.ConvertByteArrayToStringArray(rawOutputContent)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "ConvertByteArrayToStringArray error")
		}

		multiDimValue := util.Split1DArrayToMultiDArray(stringValue, firstShape, secondShape)
		if len(multiDimValue) != inputLen {
			log.Errorf(ctx, "Split1DArrayToMultiDArray not equal")
		}

		for i := 0; i < inputLen; i++ {
			result[i] = multiDimValue[i]
		}
	default:
		log.Errorf(ctx, "error datatype. got dataType=%s", dataType)
	}

	return result
}
