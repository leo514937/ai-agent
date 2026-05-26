package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// go run pkg/tools/rpc/klara/main.go
func main() {
	var (
		query        string
		summaryQuery string
	)
	flag.StringVar(&query, "query", "你好，你能陪我聊聊天吗", "user input query")
	flag.StringVar(&summaryQuery, "summaryQuery", "英雄联盟德莱文介绍", "user input summaryQuery")

	ctx := context.Background()

	// rerank
	rerank := impl.GetBgeEmbeddingClient("bge-reranker").BatchInferPairwiseScore(ctx, [][]string{{"iphone", "安卓"}, {"iphone", "手机"}, {"iphone", "苹果"}})
	fmt.Println(rerank)

	// bge-m3 emb
	bgeM3Emb := impl.GetBgeEmbeddingClient("bge-m3-common-for-zhida-online").BatchInferBgeM3DenseEmb(ctx, []string{"分享CCF 第七届AIOps国际挑战赛的季军方案", "私域领域问答的优秀效果说明RAG真的很重要"})
	fmt.Println(bgeM3Emb)

	bgeM3Sparse := impl.GetBgeEmbeddingClient("bge-m3-token").BatchInferBgeM3Sparse(ctx, []string{"2025年01月20日，deepseek 正式发布 DeepSeek-R1", "近年来，LLM 在各个领域都取得了显著进展，但推理能力仍有提升空间"})
	fmt.Println(util.GetJSONIgnoreError(bgeM3Sparse))
}
