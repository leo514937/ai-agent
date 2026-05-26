package ai_daily_rpc

import (
	"context"
	"flag"
	"fmt"
	"testing"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/ai_daily"
)

// 测试 go test -v ./cmd/ai-daily-rpc -run TestAiDailyRecommendService_AiDailyRecommend -args date=2025-09-25
func printAiDailyRecommendResponse(response *ai_daily.AiDailyRecommendResponse) {

	fmt.Println("AI Daily Recommend Response Details:")

	// 基本信息
	fmt.Printf("Code: %d\n", response.GetCode())
	fmt.Printf("Message: %s\n", response.GetMessage())

	// 播放列表数据
	playlistData := response.GetPlaylistData()
	if playlistData != nil {
		fmt.Println("\n--- Playlist Data ---")
		fmt.Printf("Title: %s\n", playlistData.GetTitle())
		fmt.Printf("Date: %s\n", playlistData.GetDate())
		fmt.Printf("Share Token: %s\n", playlistData.GetShareToken())

		// 内容项数组
		contents := playlistData.GetContents()
		if len(contents) > 0 {
			fmt.Printf("\n--- Question Contents (Total: %d) ---\n", len(contents))

			for i, content := range contents {
				fmt.Printf("\n[%d] Question Item:\n", i+1)
				fmt.Printf("  Doc Type: %s\n", content.GetDocType())
				fmt.Printf("  Title: %s\n", content.GetTitle())
				fmt.Printf("  Detail: %s\n", content.GetDetail())
				fmt.Printf("  URL: %s\n", content.GetURL())
				fmt.Printf("  URL Token: %s\n", content.GetURLToken())

				// 答案项数组
				answerItems := content.GetItems()
				if len(answerItems) > 0 {
					fmt.Printf("  --- Answer Items (Total: %d) ---\n", len(answerItems))
					for j, answerItem := range answerItems {
						fmt.Printf("    [%d] Answer Item:\n", j+1)
						fmt.Printf("      Doc Type: %s\n", answerItem.GetDocType())
						fmt.Printf("      Author Name: %s\n", answerItem.GetAuthorName())
						fmt.Printf("      Author URL: %s\n", answerItem.GetAuthorURL())
						fmt.Printf("      Author Hash ID: %s\n", answerItem.GetAuthorHashID())
						fmt.Printf("      Detail: %s\n", answerItem.GetDetail())
						fmt.Printf("      URL: %s\n", answerItem.GetURL())
						fmt.Printf("      URL Token: %s\n", answerItem.GetURLToken())
					}
				} else {
					fmt.Printf("  --- Answer Items: empty ---\n")
				}
			}
		} else {
			fmt.Println("\n--- Question Contents: empty ---")
		}
	} else {
		fmt.Println("\n--- Playlist Data: nil ---")
	}

}

var date = flag.String("date", "2025-09-25", "")

func TestAiDailyRecommendService_AiDailyRecommend(t *testing.T) {
	if !flag.Parsed() {
		flag.Parse()
	}
	flag.Parse()
	source := "push"
	request := &ai_daily.AiDailyRecommendRequest{
		UserID: 84876692,
		Date:   date,
		Source: &source,
	}

	ctx := context.Background()

	aiDailyClient := ai_daily.NewAiDailyRecommendServiceClient(
		tzone.NewClient(
			"AiDailyRecommendService",
			tzone.Timeout(1000*time.Millisecond),
			tzone.HostPort("localhost", "9999"),
			tzone.TargetName("aisp-ai-daily-rpc"),
		))

	response, err := aiDailyClient.AiDailyRecommend(ctx, request)
	if err != nil {
		fmt.Printf("error: %v", err)
	}
	printAiDailyRecommendResponse(response)
}
