package main

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

// go run pkg/tools/rpc/bge_rerank_v2/main.go
func main() {
	ctx := context.Background()
	body := &rpc.KlaraRerankRequest{
		Query: "What is Deep Learning?",
		Texts: []string{
			"Deep Learning is a subset of machine learning that uses artificial neural networks.",
			"Machine learning is the study of computer algorithms that improve automatically through experience.",
		},
		RawScores:  false,
		ReturnText: false,
	}

	httpImpl := impl.NewKlaraHttpImpl(2 * time.Second)

	// rerank1
	scoreBySize1 := httpImpl.BatchInferPairwiseScoreBySize(ctx, rpc.KlaraServiceUrlBgeRerank, rpc.KlaraRerankRequest{
		Query: body.Query,
		Texts: body.Texts,
	}, 1)
	log.Infof(ctx, "result1: %v", util.GetJSONIgnoreError(scoreBySize1))

	// rerank2
	scoreBySize2 := httpImpl.BatchInferPairwiseScoreBySize(ctx, rpc.KlaraServiceUrlZhiRerankMix, rpc.KlaraRerankRequest{
		Query: body.Query,
		Texts: body.Texts,
	}, 1)
	log.Infof(ctx, "result2: %v", util.GetJSONIgnoreError(scoreBySize2))

	// embedding
	res := httpImpl.ConcurrentInferEmbedding(ctx, rpc.KlaraServiceUrlZhiEmb, []string{"输入你的文本", "今天天气", "张三找李四钓鱼", "从前有座山"}, "zhi-embedding-prompt-zhida")
	log.Infof(ctx, "result: %v", util.GetJSONIgnoreError(res))
}
