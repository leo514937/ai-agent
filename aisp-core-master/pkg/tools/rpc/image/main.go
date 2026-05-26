package main

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

// go run pkg/tools/rpc/image/main.go
func main() {
	ctx := context.Background()
	tokens := []string{
		"v2-4978a7dd7052192425d5f118b0910966",
		"v2-8f675ae2cb37a15ec8f785f52eb3b21a",
		"v2-7571939009f918e6d37825eb1a2120ff",
	}
	descriptions := []string{
		"这是一张猫的图片",
		"这是一张狗的图片",
		"这是一张兔的图片",
	}
	urls := []string{
		"https://pic4.zhimg.com/v2-e71087ac6c0c04460c2ccf1030c5d0c3_b.jpg",
		"https://pic4.zhimg.com/v2-1bae748bd64a33d2f0aa52a5f07a6569_b.jpg",
		"https://pic2.zhimg.com/v2-210acceae1c4dc69491502e7ff22722f_b.jpg",
		"https://picx.zhimg.com/v2-d8cbc3fdcc05f968d52d5201d77485f9_b.jpg",
	}

	// 表情包、令人不适、二维码
	var imageKeys []model.Content
	for _, token := range tokens {
		imageKeys = append(imageKeys, model.NewContent(0, content2.DocType_Image, token))
	}
	tagMap := impl.DefaultTagGrpcImpl.BatchGetTag(ctx, rpc.SceneCode_AiUserInterest, rpc.AppGroupCode_AiUserRecall, imageKeys)
	for k, v := range tagMap {
		fmt.Println(fmt.Sprintf("token:%s, img_emoji:%s", k.URLToken, util2.GetImgEmojiTagValue(v.GetTags())))
		fmt.Println(fmt.Sprintf("token:%s, img_qrcode:%s", k.URLToken, util2.GetImgQrcodeTagValue(v.GetTags())))
		fmt.Println(fmt.Sprintf("token:%s, img_uncomfortable:%s", k.URLToken, util2.GetImgUncomfortableTagValue(v.GetTags())))
	}

	// 低质色情
	isImageVulgar := impl.DefaultImageZaiGrpcImpl.ConcurrentIsImageVulgar(ctx, tokens, 10)
	fmt.Println(fmt.Sprintf("Vulgar result:%v", util.GetJSONIgnoreError(isImageVulgar)))

	// 文字图
	isImagePlanText := impl.DefaultImageZaiGrpcImpl.ConcurrentIsImagePlanText(ctx, tokens, 10)
	fmt.Println(fmt.Sprintf("PlanText result:%v", util.GetJSONIgnoreError(isImagePlanText)))

	// 包含人脸
	hasFace := concurrentGetHasFace(ctx, urls)
	fmt.Println(fmt.Sprintf("hasFace result:%v", util.GetJSONIgnoreError(hasFace)))

	// 图片embedding
	imageEmbedding := impl.DefaultImageZaiGrpcImpl.ConcurrentGetImageEmbedding(ctx, tokens, 5)
	fmt.Println(fmt.Sprintf("imageEmbedding result:%v", util.GetJSONIgnoreError(imageEmbedding)))

	// 文字embedding
	textEmbedding := impl.DefaultImageZaiGrpcImpl.ConcurrentGetTextEmbedding(ctx, descriptions, 5)
	fmt.Println(fmt.Sprintf("textEmbedding result:%v", util.GetJSONIgnoreError(textEmbedding)))

	// 图片加前后描述 embedding
	var inputImageDescription [][]string
	for _, url := range urls {
		imageBase64, _ := impl.DefaultOssImpl.GetFileBase64(ctx, url)
		inputImageDescription = append(inputImageDescription, []string{imageBase64, "我们的快乐生活"})
	}
	imageDescBgeEmbedding := impl.GetBgeEmbeddingClient("image-visual-embedding").BatchInferPairwiseEmbeddingBySize(ctx, inputImageDescription, 2)
	fmt.Println(fmt.Sprintf("imageDescBgeEmbedding result:%v", util.GetJSONIgnoreError(imageDescBgeEmbedding)))

	// 图片不加描述 embedding
	var inputImage [][]string
	for _, url := range urls {
		imageBase64, _ := impl.DefaultOssImpl.GetFileBase64(ctx, url)
		inputImage = append(inputImage, []string{imageBase64, ""})
	}
	imageBgeEmbedding := impl.GetBgeEmbeddingClient("image-visual-embedding").BatchInferPairwiseEmbeddingBySize(ctx, inputImage, 2)
	fmt.Println(fmt.Sprintf("imageBgeEmbedding result:%v", util.GetJSONIgnoreError(imageBgeEmbedding)))

	// 描述 embedding
	descriptionEmbedding := impl.GetBgeEmbeddingClient("text-visual-embedding").BatchInferEmbeddingBySize(ctx, descriptions, 2)
	fmt.Println(fmt.Sprintf("descriptionEmbedding result:%v", util.GetJSONIgnoreError(descriptionEmbedding)))
}

func concurrentGetHasFace(ctx context.Context, urls []string) map[string]bool {
	resultMap := sync.Map{}

	httpImpl := impl.NewKlaraHttpImpl(20 * time.Second)
	group := safe_group.NewGroupWithTimeout("concurrentGetHasFace", 500).SetLimit(5)
	for _, url := range urls {
		url := url
		group.Go(func() error {
			imageBase64, _ := impl.DefaultOssImpl.GetFileBase64(ctx, url)
			body := map[string]interface{}{
				"image_base64": imageBase64,
			}
			jsonBody, _ := json.Marshal(body)
			var result []map[string]interface{}
			httpImpl.InvokePost(ctx, rpc.KlaraServiceUrlImageFace, jsonBody, &result)
			resultMap.Store(url, len(result) > 0)
			return nil
		})
	}
	_ = group.Wait()

	result := map[string]bool{}

	resultMap.Range(func(key, value interface{}) bool {
		result[key.(string)] = value.(bool)
		return true
	})

	return result
}
