package impl

import (
	"context"
	"os"
	"testing"
	"time"
)

// 集成测试：依赖真实 ZSearch RootService。通过环境变量 RUN_KEXIN_E2E=1 控制是否运行。
func TestKexinSearchRPC(t *testing.T) {
	if os.Getenv("RUN_KEXIN_E2E") != "1" {
		t.Skip("set RUN_KEXIN_E2E=1 to run real RPC test")
	}

	cli := NewKexinSearchRPC()
	if cli == nil {
		t.Fatal("NewKexinSearchRPC returned nil client")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	res, err := cli.Search(ctx, "跑步时手机怎么放", 16, "e2e-trace-id")
	if err != nil {
		t.Fatalf("kexin real rpc error: %v", err)
	}
	if len(res) == 0 {
		t.Fatal("empty result")
	}
	// 打印最终结果
	t.Logf("got %d results", len(res))
	for i, item := range res {
		t.Logf("%02d. name=%q url=%q published=%d", i+1, item.Name, item.Url, item.PublishedTime)
		if item.Snippet != "" {
			t.Logf("    snippet=%q", item.Snippet)
		}
	}
	// 不强制要求非空，避免外部服务波动导致不稳定
}
