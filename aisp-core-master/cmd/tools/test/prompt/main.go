package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
)

func main() {
	text, err := service.DefaultPromptMapperService.FormatPromptById(context.Background(),
		macro.PromptQueryIntention, map[string]string{
			"Content": "你好啊小姐姐，请问你芳龄多大？",
		})
	if err != nil {
		fmt.Println("转换错误")
	} else {
		fmt.Println(text)
	}
}
