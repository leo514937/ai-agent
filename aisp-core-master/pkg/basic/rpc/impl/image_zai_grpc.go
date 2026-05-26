package impl

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

type ImageZaiGrpcImpl struct {
	timeout              time.Duration
	imagePlanTextClient  content_grpc.PluginServiceClient
	imageVulgarClient    content_grpc.PluginServiceClient
	imageEmbeddingClient content_grpc.EmbeddingServiceClient
	textEmbeddingClient  content_grpc.EmbeddingServiceClient
}

var DefaultImageZaiGrpcImpl rpc.ImageZaiGrpc

func init() {
	DefaultImageZaiGrpcImpl = NewImageZaiGrpcImpl()
}
func NewImageZaiGrpcImpl() *ImageZaiGrpcImpl {
	imagePlanTextConn, textErr := grpc.DialContext(context.Background(), "zai-image-plaintext-v2")
	imageVulgarConn, vulgarErr := grpc.DialContext(context.Background(), "zai-image-vulgar-v2")
	imageEmbeddingConn, imageEmbeddingErr := grpc.DialContext(context.Background(), "zai-clip-image-embedding")
	textEmbeddingConn, textEmbeddingErr := grpc.DialContext(context.Background(), "zai-clip-text-embedding")

	if textErr != nil {
		log.Errorf(context.Background(), "dial zai-image-plaintext-v2 failed. err: %+v", textErr)
		panic(textErr)
	}
	if vulgarErr != nil {
		log.Errorf(context.Background(), "dial zai-image-vulgar-v failed. err: %+v", vulgarErr)
		panic(vulgarErr)
	}
	if imageEmbeddingErr != nil {
		log.Errorf(context.Background(), "dial zai-clip-image-embedding failed. err: %+v", imageEmbeddingErr)
		panic(imageEmbeddingErr)
	}
	if textEmbeddingErr != nil {
		log.Errorf(context.Background(), "dial zai-clip-text-embedding failed. err: %+v", textEmbeddingErr)
		panic(textEmbeddingErr)
	}

	return &ImageZaiGrpcImpl{
		timeout:              1000 * time.Millisecond,
		imagePlanTextClient:  content_grpc.NewPluginServiceClient(imagePlanTextConn),
		imageVulgarClient:    content_grpc.NewPluginServiceClient(imageVulgarConn),
		imageEmbeddingClient: content_grpc.NewEmbeddingServiceClient(imageEmbeddingConn),
		textEmbeddingClient:  content_grpc.NewEmbeddingServiceClient(textEmbeddingConn),
	}
}

// 图片是文字图
func (i *ImageZaiGrpcImpl) ConcurrentIsImagePlanText(ctx context.Context, imageTokens []string, concurrency int) map[string]bool {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentIsImagePlanText", 2000).SetLimit(concurrency)
	for _, imageToken := range imageTokens {
		imageToken := imageToken
		group.Go(func() error {
			resultMap.Store(imageToken, i.IsImagePlanText(ctx, imageToken))
			return nil
		})
	}
	_ = group.Wait()

	result := map[string]bool{}
	for _, imageToken := range imageTokens {
		if res, ok := resultMap.Load(imageToken); ok {
			result[imageToken] = res.(bool)
		} else {
			result[imageToken] = false
		}
	}

	return result
}

func (i *ImageZaiGrpcImpl) IsImagePlanText(ctx context.Context, imageToken string) bool {
	var res bool
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, i.timeout)
		defer cancel()

		request := &content_grpc.PluginRequest{
			Identifier: &content.DocIdentity{
				DocType: content.DocType_Image,
				Token:   imageToken,
			},
		}
		resp, err := i.imagePlanTextClient.BatchGet(newCtx, &content_grpc.PluginRequests{Request: []*content_grpc.PluginRequest{request}})
		if err != nil || len(resp.GetResponse()) == 0 {
			log.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		if len(resp.GetResponse()[0].GetItem()) > 0 {
			res = tag2bool(resp.GetResponse()[0].GetItem()[0].GetName())
		}
		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func tag2bool(tagName string) bool {
	switch tagName {
	case "YES":
		return true
	case "NO":
		return false
	default:
		return false
	}
}

// 图片低俗擦边
func (i *ImageZaiGrpcImpl) ConcurrentIsImageVulgar(ctx context.Context, imageTokens []string, concurrency int) map[string]bool {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentIsImageVulgar", 2000).SetLimit(concurrency)
	for _, imageToken := range imageTokens {
		imageToken := imageToken
		group.Go(func() error {
			resultMap.Store(imageToken, i.IsImageVulgar(ctx, imageToken))
			return nil
		})
	}
	_ = group.Wait()

	result := map[string]bool{}
	for _, imageToken := range imageTokens {
		if res, ok := resultMap.Load(imageToken); ok {
			result[imageToken] = res.(bool)
		} else {
			result[imageToken] = false
		}
	}

	return result
}

func (i *ImageZaiGrpcImpl) IsImageVulgar(ctx context.Context, imageToken string) bool {
	var res bool
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, i.timeout)
		defer cancel()

		request := &content_grpc.PluginRequest{
			Identifier: &content.DocIdentity{
				DocType: content.DocType_Image,
				Token:   imageToken,
			},
		}
		resp, err := i.imageVulgarClient.BatchGet(newCtx, &content_grpc.PluginRequests{Request: []*content_grpc.PluginRequest{request}})
		if err != nil || len(resp.GetResponse()) == 0 {
			log.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		if len(resp.GetResponse()[0].GetItem()) > 0 {
			res = resp.GetResponse()[0].GetItem()[0].GetScore() >= 0.167
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

// 获取图片 embedding
func (i *ImageZaiGrpcImpl) ConcurrentGetImageEmbedding(ctx context.Context, imageTokens []string, concurrency int) map[string][]float32 {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetImageEmbedding", 2000).SetLimit(concurrency)
	for _, imageToken := range imageTokens {
		imageToken := imageToken
		group.Go(func() error {
			resultMap.Store(imageToken, i.getImageEmbedding(ctx, imageToken))
			return nil
		})
	}
	_ = group.Wait()

	result := map[string][]float32{}
	for _, imageToken := range imageTokens {
		if res, ok := resultMap.Load(imageToken); ok {
			result[imageToken] = res.([]float32)
		}
	}

	return result
}

func (i *ImageZaiGrpcImpl) getImageEmbedding(ctx context.Context, imageToken string) []float32 {
	var res []float32

	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, i.timeout)
		defer cancel()

		request := &content_grpc.EmbeddingRequest{
			DocType:  content.DocType_Image,
			UrlToken: imageToken,
		}

		resp, err := i.imageEmbeddingClient.Embedding(newCtx, request)
		if err != nil {
			log.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		res = resp.GetDocEmbedding().GetEmbedding().GetEmbedding()

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

// 获取文字 embedding
func (i *ImageZaiGrpcImpl) ConcurrentGetTextEmbedding(ctx context.Context, texts []string, concurrency int) [][]float32 {
	resultMap := sync.Map{}

	var textIndexMap = make(map[int]string)
	for index, text := range texts {
		textIndexMap[index] = text
	}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetTextEmbedding", 2000).SetLimit(concurrency)
	for idx, text := range textIndexMap {
		text := text
		idx := idx
		group.Go(func() error {
			resultMap.Store(idx, i.getTextEmbedding(ctx, text))
			return nil
		})
	}

	_ = group.Wait()

	var result = make([][]float32, len(texts))
	for idx, _ := range texts {
		if res, ok := resultMap.Load(idx); ok {
			result[idx] = res.([]float32)
		} else {
			result[idx] = []float32{}
		}
	}

	return result
}

func (i *ImageZaiGrpcImpl) getTextEmbedding(ctx context.Context, text string) []float32 {
	var res []float32

	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, i.timeout)
		defer cancel()

		request := &content_grpc.EmbeddingRequest{
			DocType: content.DocType_Text,
			Content: text,
		}

		resp, err := i.textEmbeddingClient.Embedding(newCtx, request)
		if err != nil {
			log.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		res = resp.GetDocEmbedding().GetEmbedding().GetEmbedding()

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

var _ rpc.ImageZaiGrpc = (*ImageZaiGrpcImpl)(nil)
