package main

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/search_recall"
	"github.com/olekukonko/tablewriter"
	"go.uber.org/ratelimit"
)

// 性能测试结果
type PerformanceResult struct {
	SearchType    search_recall.OutSiteSearchRecallType
	TotalRequests int64
	SuccessCount  int64
	ErrorCount    int64
	MinLatency    time.Duration
	MaxLatency    time.Duration
	AvgLatency    time.Duration
	P50Latency    time.Duration
	P90Latency    time.Duration
	P99Latency    time.Duration
	TotalDuration time.Duration
}

func main() {
	// 解析命令行参数
	var (
		text        string
		qps         int
		concurrency int
		duration    int
	)

	flag.StringVar(&text, "text", "闵行爆炸", "搜索文本")
	flag.IntVar(&qps, "qps", 10, "每秒请求数")
	flag.IntVar(&duration, "duration", 10, "测试持续时间(秒)")
	flag.Parse()

	searchTypes := []search_recall.OutSiteSearchRecallType{
		//search_recall.OutSiteSearchRecallTypeBing,
		//search_recall.OutSiteSearchRecallTypeCloudSwayBing,
		search_recall.OutSiteSearchRecallTypeCloudSwaySerp,
		//search_recall.OutSiteSearchRecallTypeQuark,
	}

	// 初始化服务
	recallService := search_recall.NewOutSiteSearchRecallService()

	// 设置上下文，支持取消
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 捕获退出信号
	signalChan := make(chan os.Signal, 1)
	signal.Notify(signalChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-signalChan
		fmt.Println("\n接收到退出信号，正在优雅关闭...")
		cancel()
	}()

	// 对每种搜索类型进行测试
	for _, searchType := range searchTypes {
		fmt.Printf("开始测试 %s 搜索引擎 (QPS: %d, 并发: %d, 持续: %d秒)...\n",
			searchType, qps, concurrency, duration)

		result := runPerformanceTest(ctx, recallService, searchType, text, qps, qps, duration)
		printResult(result)

		// 等待一下再测试下一个搜索类型
		time.Sleep(2 * time.Second)
	}
}

func runPerformanceTest(
	ctx context.Context,
	service search_recall.OutSiteSearchRecallService,
	searchType search_recall.OutSiteSearchRecallType,
	query string,
	qps int,
	concurrency int,
	durationSeconds int,
) *PerformanceResult {
	var (
		wg             sync.WaitGroup
		totalRequests  int64
		successCount   int64
		errorCount     int64
		totalLatency   int64
		activeRequests int32 // 当前活跃请求计数

		// 使用互斥锁保护以下变量
		mu         sync.Mutex
		minLatency time.Duration = time.Hour
		maxLatency time.Duration
		latencies  []time.Duration
	)

	queryGenerator := NewUniqueQueryGenerator(query, qps, durationSeconds)

	// 使用令牌桶限制QPS
	limiter := ratelimit.New(qps)

	// 创建工作通道
	jobChan := make(chan struct{}, qps*2)

	// 创建一个信号通道，用于通知所有活跃请求已完成
	doneChan := make(chan struct{})

	// 测试结束标志
	var testFinished atomic.Bool
	testFinished.Store(false)

	// 标记测试开始时间
	startTime := time.Now()

	// 创建上下文，但不再使用超时取消
	testCtx, testCancel := context.WithCancel(ctx)
	defer testCancel()

	// 启动一个协程来监控测试持续时间
	go func() {
		// 等待指定的测试时间
		select {
		case <-ctx.Done():
			// 外部上下文被取消
		case <-time.After(time.Duration(durationSeconds) * time.Second):
			// 测试时间到达
		}

		// 标记测试结束，不再接受新的任务
		testFinished.Store(true)
		testCancel() // 取消测试上下文，但不强制中断正在进行的请求

		// 等待所有活跃请求完成
		for {
			if atomic.LoadInt32(&activeRequests) == 0 {
				close(doneChan)
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
	}()

	// 启动消费者协程
	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()

			for range jobChan {
				// 如果测试已结束，不处理新任务
				if testFinished.Load() {
					continue
				}

				// 增加活跃请求计数
				atomic.AddInt32(&activeRequests, 1)

				// 为每个请求生成唯一的跟踪ID
				traceID := fmt.Sprintf("%s-%d", searchType, atomic.AddInt64(&totalRequests, 1))

				// 记录开始时间
				start := time.Now()

				// 创建一个专用于此请求的上下文，不使用测试的超时上下文
				reqCtx := context.Background()

				// 执行搜索
				result := service.OutSiteSearchRecall(reqCtx, searchType, queryGenerator.Next(), 5, traceID, nil)

				// 计算延迟
				latency := time.Since(start)

				mu.Lock()
				if len(result) > 0 {
					atomic.AddInt64(&successCount, 1)
				} else {
					atomic.AddInt64(&errorCount, 1)
				}

				// 更新延迟统计
				if latency < minLatency {
					minLatency = latency
				}
				if latency > maxLatency {
					maxLatency = latency
				}
				atomic.AddInt64(&totalLatency, int64(latency))
				latencies = append(latencies, latency)
				mu.Unlock()

				// 减少活跃请求计数
				atomic.AddInt32(&activeRequests, -1)
			}
		}()
	}

	// 生产者协程 - 按照指定QPS发送请求
	go func() {
		defer close(jobChan)

		for {
			select {
			case <-testCtx.Done():
				return
			default:
				limiter.Take() // 限制QPS

				// 检查测试是否已结束
				if testFinished.Load() {
					return
				}

				select {
				case jobChan <- struct{}{}:
				case <-testCtx.Done():
					return
				}
			}
		}
	}()

	// 等待所有请求完成
	<-doneChan
	testDuration := time.Since(startTime)

	// 计算百分位数
	mu.Lock()
	// 排序延迟数组以计算百分位
	p50, p90, p99 := calculatePercentiles(latencies)
	mu.Unlock()

	total := atomic.LoadInt64(&totalRequests)
	// 如果没有请求，避免除以零
	avgLatency := time.Duration(0)
	if total > 0 {
		avgLatency = time.Duration(atomic.LoadInt64(&totalLatency) / total)
	}

	return &PerformanceResult{
		SearchType:    searchType,
		TotalRequests: total,
		SuccessCount:  atomic.LoadInt64(&successCount),
		ErrorCount:    atomic.LoadInt64(&errorCount),
		MinLatency:    minLatency,
		MaxLatency:    maxLatency,
		AvgLatency:    avgLatency,
		P50Latency:    p50,
		P90Latency:    p90,
		P99Latency:    p99,
		TotalDuration: testDuration,
	}
}

// 计算百分位数
func calculatePercentiles(latencies []time.Duration) (p50, p90, p99 time.Duration) {
	if len(latencies) == 0 {
		return 0, 0, 0
	}

	// 排序
	timeSlice(latencies).Sort()

	// 计算索引
	p50Index := int(float64(len(latencies)) * 0.5)
	p90Index := int(float64(len(latencies)) * 0.9)
	p99Index := int(float64(len(latencies)) * 0.99)

	// 边界检查
	if p50Index >= len(latencies) {
		p50Index = len(latencies) - 1
	}
	if p90Index >= len(latencies) {
		p90Index = len(latencies) - 1
	}
	if p99Index >= len(latencies) {
		p99Index = len(latencies) - 1
	}

	return latencies[p50Index], latencies[p90Index], latencies[p99Index]
}

// 用于排序的辅助类型
type timeSlice []time.Duration

func (s timeSlice) Len() int           { return len(s) }
func (s timeSlice) Less(i, j int) bool { return s[i] < s[j] }
func (s timeSlice) Swap(i, j int)      { s[i], s[j] = s[j], s[i] }
func (s timeSlice) Sort()              { s.quickSort(0, len(s)-1) }

// 快速排序实现
func (s timeSlice) quickSort(low, high int) {
	if low < high {
		pivot := s.partition(low, high)
		s.quickSort(low, pivot-1)
		s.quickSort(pivot+1, high)
	}
}

func (s timeSlice) partition(low, high int) int {
	pivot := s[high]
	i := low - 1

	for j := low; j < high; j++ {
		if s[j] <= pivot {
			i++
			s[i], s[j] = s[j], s[i]
		}
	}

	s[i+1], s[high] = s[high], s[i+1]
	return i + 1
}

// 打印测试结果
func printResult(result *PerformanceResult) {
	table := tablewriter.NewWriter(os.Stdout)
	table.SetHeader([]string{"指标", "值"})

	table.Append([]string{"搜索类型", string(result.SearchType)})
	table.Append([]string{"总请求数", fmt.Sprintf("%d", result.TotalRequests)})
	table.Append([]string{"成功数", fmt.Sprintf("%d", result.SuccessCount)})
	table.Append([]string{"失败数", fmt.Sprintf("%d", result.ErrorCount)})

	if result.TotalRequests > 0 {
		table.Append([]string{"成功率", fmt.Sprintf("%.2f%%", float64(result.SuccessCount)*100/float64(result.TotalRequests))})
	}

	table.Append([]string{"最小延迟", result.MinLatency.String()})
	table.Append([]string{"最大延迟", result.MaxLatency.String()})
	table.Append([]string{"平均延迟", result.AvgLatency.String()})
	table.Append([]string{"P50延迟", result.P50Latency.String()})
	table.Append([]string{"P90延迟", result.P90Latency.String()})
	table.Append([]string{"P99延迟", result.P99Latency.String()})

	table.Append([]string{"测试持续时间", result.TotalDuration.String()})
	table.Append([]string{"实际QPS", fmt.Sprintf("%.2f", float64(result.TotalRequests)/result.TotalDuration.Seconds())})

	table.Render()
	fmt.Println()
}

// 计算理论上需要的查询数量
func calculateRequiredQueries(qps, durationSeconds int) int {
	// 计算理论上的请求总数
	theoreticalTotal := qps * durationSeconds

	// 增加50%的缓冲，确保绝对不会重复
	requiredQueries := int(float64(theoreticalTotal) * 1.5)

	// 设置最小和最大值限制
	if requiredQueries < 1000 {
		requiredQueries = 1000 // 至少生成1000个
	}
	if requiredQueries > 50000 {
		requiredQueries = 50000 // 最多生成50000个，避免内存过大
	}

	return requiredQueries
}

// 高级不重复查询生成器
type UniqueQueryGenerator struct {
	baseQuery     string
	queries       []string
	index         int32
	mu            sync.RWMutex
	queryLimit    int
	randomStrings []string
}

func NewUniqueQueryGenerator(baseQuery string, qps, durationSeconds int) *UniqueQueryGenerator {
	if baseQuery == "" {
		baseQuery = "搜索"
	}

	// 计算需要预生成的查询数量
	queryLimit := calculateRequiredQueries(qps, durationSeconds)

	// 预生成一些随机字符串用于组合
	randomStrings := makeRandomStrings(500)

	// 预先构建10000条查询
	gen := &UniqueQueryGenerator{
		baseQuery:     baseQuery,
		queryLimit:    queryLimit,
		randomStrings: randomStrings,
	}

	// 预生成查询
	fmt.Println("预生成10000条不重复查询中...")
	start := time.Now()
	gen.generateQueries()
	fmt.Printf("查询生成完成，用时: %v\n", time.Since(start))

	return gen
}

// 生成不重复的随机字符串
func makeRandomStrings(count int) []string {
	result := make([]string, count)
	words := []string{
		"时间", "空间", "气候", "服务", "经济", "政治", "文化", "科技", "教育", "健康",
		"医疗", "交通", "安全", "食品", "环境", "能源", "数据", "通信", "媒体", "网络",
		"城市", "乡村", "公司", "市场", "社区", "家庭", "学校", "医院", "商店", "餐厅",
		"酒店", "公园", "道路", "建筑", "设计", "艺术", "音乐", "电影", "书籍", "游戏",
		"旅行", "运动", "饮食", "时尚", "历史", "未来", "问题", "解决", "挑战", "机会",
	}

	prefixes := []string{
		"新", "老", "大", "小", "高", "低", "快", "慢", "好", "坏",
		"热", "冷", "硬", "软", "轻", "重", "深", "浅", "宽", "窄",
	}

	suffixes := []string{
		"的情况", "的问题", "的变化", "的发展", "的趋势", "的影响", "的原因", "的结果", "的方法", "的技术",
		"的计划", "的策略", "的研究", "的报告", "的分析", "的评估", "的建议", "的解决", "的管理", "的应用",
	}

	for i := 0; i < count; i++ {
		word1 := words[rand.Intn(len(words))]
		word2 := words[rand.Intn(len(words))]
		prefix := prefixes[rand.Intn(len(prefixes))]
		suffix := suffixes[rand.Intn(len(suffixes))]

		// 确保word1和word2不相同
		for word1 == word2 {
			word2 = words[rand.Intn(len(words))]
		}

		// 随机组合方式
		switch rand.Intn(5) {
		case 0:
			result[i] = prefix + word1 + word2
		case 1:
			result[i] = word1 + word2 + suffix
		case 2:
			result[i] = prefix + word1 + "和" + word2
		case 3:
			result[i] = word1 + "对" + word2 + suffix
		case 4:
			result[i] = prefix + word1 + "的" + word2
		}
	}

	return result
}

// 预生成所有查询
func (g *UniqueQueryGenerator) generateQueries() {
	g.mu.Lock()
	defer g.mu.Unlock()

	// 使用map确保唯一性
	queryMap := make(map[string]struct{})

	// 创建多样化的查询
	for len(queryMap) < g.queryLimit {
		query := g.createRandomQuery()
		queryMap[query] = struct{}{}
	}

	// 将map转换为切片
	g.queries = make([]string, 0, len(queryMap))
	for q := range queryMap {
		g.queries = append(g.queries, q)
	}

	// 打乱顺序
	rand.Shuffle(len(g.queries), func(i, j int) {
		g.queries[i], g.queries[j] = g.queries[j], g.queries[i]
	})
}

// 创建随机查询
func (g *UniqueQueryGenerator) createRandomQuery() string {
	// 50%的概率使用基础查询
	if rand.Intn(2) == 0 && g.baseQuery != "" {
		// 基于基础查询构建变体
		randStr1 := g.randomStrings[rand.Intn(len(g.randomStrings))]
		randStr2 := g.randomStrings[rand.Intn(len(g.randomStrings))]

		switch rand.Intn(5) {
		case 0:
			return g.baseQuery + "相关" + randStr1
		case 1:
			return randStr1 + "中的" + g.baseQuery
		case 2:
			return g.baseQuery + "和" + randStr1 + "的关系"
		case 3:
			return randStr1 + g.baseQuery + randStr2
		case 4:
			return "关于" + g.baseQuery + "的" + randStr1
		}
	}

	// 使用随机组合
	randStr1 := g.randomStrings[rand.Intn(len(g.randomStrings))]
	randStr2 := g.randomStrings[rand.Intn(len(g.randomStrings))]

	// 确保两个字符串不同
	for randStr1 == randStr2 {
		randStr2 = g.randomStrings[rand.Intn(len(g.randomStrings))]
	}

	// 当前时间戳（微秒级）作为后缀，确保唯一性
	timestamp := strconv.FormatInt(time.Now().UnixNano()/1000, 10)
	hash := md5.Sum([]byte(timestamp + randStr1 + randStr2))
	uniqueSuffix := hex.EncodeToString(hash[:])[:6]

	switch rand.Intn(6) {
	case 0:
		return randStr1 + "的" + randStr2 + uniqueSuffix
	case 1:
		return randStr1 + "如何影响" + randStr2 + uniqueSuffix
	case 2:
		return randStr1 + "和" + randStr2 + "的区别" + uniqueSuffix
	case 3:
		return "为什么" + randStr1 + "会导致" + randStr2 + uniqueSuffix
	case 4:
		return randStr1 + "在" + randStr2 + "中的应用" + uniqueSuffix
	default:
		return "探讨" + randStr1 + "与" + randStr2 + "的关系" + uniqueSuffix
	}
}

// 获取下一个查询
func (g *UniqueQueryGenerator) Next() string {
	// 快速路径：直接读取
	g.mu.RLock()
	idx := atomic.AddInt32(&g.index, 1) - 1
	if int(idx) < len(g.queries) {
		result := g.queries[idx]
		g.mu.RUnlock()
		return result
	}
	g.mu.RUnlock()

	// 慢路径：需要重新分配索引
	g.mu.Lock()
	defer g.mu.Unlock()

	// 循环使用预生成的查询
	idx = atomic.LoadInt32(&g.index)
	if int(idx) >= len(g.queries) {
		atomic.StoreInt32(&g.index, 0)
		idx = 0
	}

	// 随机混淆一些查询，保持新鲜度
	mixinIndex := rand.Intn(len(g.queries))
	g.queries[mixinIndex] = g.createRandomQuery()

	result := g.queries[idx]
	atomic.AddInt32(&g.index, 1)
	return result
}
