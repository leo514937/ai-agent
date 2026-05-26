package main

import (
	"context"
	"fmt"

	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/similar"
)

func main() {
	similarService := service.NewSimilarService("ensemble")
	scores := similarService.BatchGetSimilarScore(context.Background(), "闵行爆炸", []string{"闵行", "爆炸"})
	fmt.Println(scores)
}
