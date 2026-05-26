package main

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type Timer struct {
	start time.Time
}

func NewTimer() *Timer {
	return &Timer{start: time.Now()}
}

func (t *Timer) Elapsed() time.Duration {
	return time.Since(t.start)
}

type Config struct {
	QPS         int
	Duration    time.Duration
	Concurrency int
	BatchSize   int
	Query       string
	Chunks      []string
}

func runQPSTest(cfg Config, client rpc.KlaraRpcClient) {
	ctx, cancel := context.WithTimeout(context.Background(), cfg.Duration)
	defer cancel()

	var wg sync.WaitGroup
	var totalRequests int64
	startTime := time.Now()

	// 创建一个带缓冲的通道来控制并发
	semaphore := make(chan struct{}, cfg.Concurrency)
	times := util.NewSyncMap[int64, int64]()

	// 计算每个请求之间的间隔
	interval := time.Second / time.Duration(cfg.QPS)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			wg.Wait()
			duration := time.Since(startTime)
			actualQPS := float64(totalRequests) / duration.Seconds()
			var sum int64
			times.Range(func(key int64, value int64) bool {
				sum += value
				return true
			})
			fmt.Printf("Test completed. Duration: %v, Total Requests: %d, Actual QPS: %.2f, AvgTime: %v\n",
				duration.Round(time.Millisecond), totalRequests, actualQPS, sum/int64(times.Len()))
			return
		case <-ticker.C:
			wg.Add(1)
			go func() {
				defer wg.Done()
				semaphore <- struct{}{}        // 获取信号量
				defer func() { <-semaphore }() // 释放信号量
				timer := NewTimer()
				// 模拟请求处理
				doRun(cfg, client)
				index := atomic.AddInt64(&totalRequests, 1)
				times.Set(index, timer.Elapsed().Milliseconds())
			}()
		}
	}
}

func main() {
	cfg := Config{
		QPS:         2,               // 目标 QPS
		Duration:    1 * time.Minute, // 持续时间
		Concurrency: 3,               // 最大并发数
		BatchSize:   1,
		Query:       "梁朝伟电影",
		Chunks: []string{
			"昨天晚上，我躺在宿舍的上铺，戴着原装耳机，在爱奇艺上观看了一部听说过多次但却一直没有看的电影——《无间道》。\n在此之前，我对于此部影片的印象是——卧底，警察，港片，梁朝伟和刘德华，除此之外便是在网易云上听过它的一个插曲——再见，警察。\n2003年的电影，为什么我2018才看，为什么是这个时间节点？\n原因如下：\n打开爱奇艺，搜索无间道，榜首是无间道3》（能拍3部，说明第一部很火！），例如《叶问》。\n点进《无间道》，评分9.2。嗯，第一印象就不错了。这电影肯定有看头。",
			"港味十足，特别合我口味，例如《杀破狼》。\n导演没话说。作为这样一部“谍性”影片，逻辑性要求高很自然。在我看来，这部影片达到了要求。说到这，我还想到了一部影片《破局》。\n这部影片很简洁。而且不是特别烧脑。\n最大亮点（在我看来）:张力。\n戏剧的张力。\n按照常规，正义与邪恶的对抗最终应该是正义胜利。\n而这部影片，结局是卧底警察死了。",
			"都说梁朝伟帅，以前不觉得，在看这部影片时算是感受到了，不是简单的帅，而是那种气质，给人的那种feeling。\n刘健明说“能不能给个机会，我开始选择做个好人”。\n刘永仁，“对不起，我是个警察”。",
			"点进《无间道》，评分9.2。嗯，第一印象就不错了。这电影肯定有看头。",
			"最终杀了救了自己的人 。他自被迫去警察部当卧底开始，便心里有一股压抑的不爽。导致他也开始变得冷酷，",
			"皆大欢喜多好。\n可现实是残酷的。\n都说梁朝伟帅，以前不觉得，在看这部影片时算是感受到了，不是简单的帅，而是那种气质，给人的那种feeling。",
			"导演没话说。作为这样一部“谍性”影片，逻辑性要求高很自然。在我看来，这部影片达到了要求。说到这，我还想到了一部影片《破局》。\n",
			"最大亮点（在我看来）:张力。\n戏剧的张力。\n按照常规，正义与邪恶的对抗最终应该是正义胜利。\n而这部影片",
			"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb=====================\n港味十足，特别合我口味，例如《杀破狼》。\n导演没话说。作为这样一部“谍性”影片，逻辑性要求高很自然。在我看来，这部影片达到了要求。说到这，我还想到了一部影片《破局》。\n这部影片很简洁。而且不是特别烧脑。",
			"可现实是残酷的。\n都说梁朝伟帅，以前不觉得，在看这部影片时算是感受到了，不是简单的帅，而是那种气质，给人的那种feeling。\n刘健明说“能不能给个机会，我开始选择做个好人”。\n刘永仁，“对不起，我是个警察”。\n明最终杀了救了自己的人 。他自被迫去警察部当卧底开始，便心里有一股压抑的不爽。导致他也开始变得冷酷，他受了琛哥那句“一将成万骨枯”的影响，成了他的信仰，使他成了一个“精致的利己主义者”。\n这很大一部分是不由他控制的，在卧底这种身份上，一开始就临被揭穿的恐惧，而且无时无刻都弥漫在自己周遭，长时间处于高压之下，若一个人没疯，那只有一种可能，走向另一个极端，失去人性，变得冷血无情。\n说起卧底，去年看的《巨额来电》",
			"导演没话说。作为这样一部“谍性”影片，逻辑性要求高很自然。在我看来，这部影片达到了要求。说到这，我还想到了一部影片《破局》。\n这部影片很简洁。而且不是特别烧脑。\n最大亮点（在我看来）:张力。\n戏剧的张力。\n按照常规，正义与邪恶的对抗最终应该是正义胜利。\n而这部影片，结局是卧底警察死了。\n卧底坏人侥幸得以活着风光。\n悲剧结局所产生的悲剧美感，使得影片结尾余味悠长。\n但影片的结尾恰恰照应了开头一段说明影片名由来的文字——何为“无间”，并且补偿了电影悲剧结尾给观众带来的不舒服的缺憾感。\n靠！佛教文化都出来了",
		},
	}
	embeddingClient := impl.GetBgeEmbeddingClient("bge-reranker")
	runQPSTest(cfg, embeddingClient)
}

func doRun(cfg Config, client rpc.KlaraRpcClient) {
	textsSlice := make([][]string, 0)
	for _, chunkText := range cfg.Chunks {
		textsSlice = append(textsSlice, []string{cfg.Query, chunkText})
	}
	scores := client.BatchInferPairwiseScoreBySize(context.Background(), textsSlice, cfg.BatchSize)
	fmt.Printf("输出Scores %v \n", scores)
}
