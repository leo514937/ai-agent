package main

import (
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// 使用示例
func main() {
	urls := []string{
		"https://www.example.com/path?q=test",
		"http://blog.example.co.uk/article",
		"sub.domain.github.io",
		"localhost:8080",
		"192.168.1.1",
		"https://www.google.com.hk/search?q=test",
	}

	for _, u := range urls {
		info, err := util.ExtractDomainInfo(u)
		if err != nil {
			fmt.Printf("处理 %s: %v\n", u, err)
			continue
		}
		fmt.Printf("URL: %s\n", u)
		fmt.Printf("  完整域名: %s\n", info.FullDomain)
		fmt.Printf("  一级域名: %s\n\n", info.RootDomain)
	}
}
