package main

import (
	"context"
	"fmt"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
)

func main() {
	ctx := context.Background()
	oss := impl.DefaultFileManagementDAO

	ossPath := "ai-platform/aisp/synonyms/template.xlsx"

	// 读取本地文件到bytes中
	bytes, err := os.ReadFile("/data/apps/aisp-core/同义词模板.xlsx")
	if err != nil {
		fmt.Println(fmt.Sprintf("ReadFile error: %v", err))
		panic(err)
	}
	err = oss.UploadFile(ctx, bytes, ossPath)
	if err != nil {
		fmt.Println(fmt.Sprintf("UploadFile error: %v", err))
	}

	url, err := oss.GenerateFileUrl(ctx, ossPath, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	if err != nil {
		fmt.Println(fmt.Sprintf("GenerateFileUrl error: %v", err))
	}

	fmt.Println(fmt.Sprintf("GenerateFileUrl url: %v", url))
}
