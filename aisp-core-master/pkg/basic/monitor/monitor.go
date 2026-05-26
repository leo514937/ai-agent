package monitor

import (
	"fmt"
	"os"
	"os/signal"
	"runtime"
	"runtime/pprof"
	"sort"
	"sync"
	"syscall"
	"time"
)

type MemoryMonitor struct {
	// 配置项
	config struct {
		profileDir      string        // profile文件存储目录
		checkInterval   time.Duration // 检查间隔
		cooldownPeriod  time.Duration // 两次dump之间的冷却时间
		memoryThreshold float64       // 内存使用阈值(0-1)
		maxProfiles     int           // 保留的最大profile数量
	}

	// 运行时状态
	state struct {
		mu           sync.Mutex
		lastDumpTime time.Time
		memoryLimit  uint64
		isMonitoring bool
		dumpCount    int
	}
}

func NewMemoryMonitor(profileDir string) *MemoryMonitor {
	m := &MemoryMonitor{}

	// 设置默认配置
	m.config.profileDir = profileDir
	m.config.checkInterval = 5 * time.Second
	m.config.cooldownPeriod = 1 * time.Minute
	m.config.memoryThreshold = 0.8
	m.config.maxProfiles = 10

	return m
}

// 配置方法
func (m *MemoryMonitor) SetCheckInterval(d time.Duration) *MemoryMonitor {
	m.config.checkInterval = d
	return m
}

func (m *MemoryMonitor) SetCooldownPeriod(d time.Duration) *MemoryMonitor {
	m.config.cooldownPeriod = d
	return m
}

func (m *MemoryMonitor) SetMemoryThreshold(threshold float64) *MemoryMonitor {
	m.config.memoryThreshold = threshold
	return m
}

func (m *MemoryMonitor) Start() error {
	// 创建profile目录
	if err := os.MkdirAll(m.config.profileDir, 0755); err != nil {
		return fmt.Errorf("create profile directory: %w", err)
	}

	// 获取内存限制
	m.detectMemoryLimit()

	// 启动监控
	m.state.isMonitoring = true
	go m.monitorRoutine()
	go m.handleSignals()

	return nil
}

func (m *MemoryMonitor) Stop() {
	m.state.mu.Lock()
	m.state.isMonitoring = false
	m.state.mu.Unlock()
}

func (m *MemoryMonitor) detectMemoryLimit() {
	// 尝试从cgroup获取内存限制
	paths := []string{
		"/sys/fs/cgroup/memory.max",                   // cgroup v2
		"/sys/fs/cgroup/memory/memory.limit_in_bytes", // cgroup v1
	}

	for _, path := range paths {
		if limit, err := readMemoryLimit(path); err == nil && limit > 0 {
			m.state.memoryLimit = limit
			return
		}
	}

	// 如果无法获取限制，使用系统内存作为限制
	var memInfo runtime.MemStats
	runtime.ReadMemStats(&memInfo)
	m.state.memoryLimit = memInfo.Sys
}

func (m *MemoryMonitor) monitorRoutine() {
	ticker := time.NewTicker(m.config.checkInterval)
	defer ticker.Stop()

	for {
		if !m.state.isMonitoring {
			return
		}

		var memStats runtime.MemStats
		runtime.ReadMemStats(&memStats)

		if m.shouldDumpProfile(memStats) {
			m.dumpProfiles()
		}

		<-ticker.C
	}
}

func (m *MemoryMonitor) shouldDumpProfile(stats runtime.MemStats) bool {
	m.state.mu.Lock()
	defer m.state.mu.Unlock()

	// 检查冷却时间
	if time.Since(m.state.lastDumpTime) < m.config.cooldownPeriod {
		return false
	}

	// 检查内存使用率
	memoryUsage := float64(stats.Alloc) / float64(m.state.memoryLimit)
	return memoryUsage > m.config.memoryThreshold
}

func (m *MemoryMonitor) dumpProfiles() {
	m.state.mu.Lock()
	m.state.lastDumpTime = time.Now()
	m.state.dumpCount++
	dumpCount := m.state.dumpCount
	m.state.mu.Unlock()

	timestamp := time.Now().Format("20060102_150405")
	baseFileName := fmt.Sprintf("%s/profile_%d_%s", m.config.profileDir, dumpCount, timestamp)

	// 创建概要文件
	summaryFile, err := os.Create(baseFileName + "_summary.txt")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to create summary file: %v\n", err)
		return
	}
	defer summaryFile.Close()

	// 记录内存统计
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	writeMemoryStats(summaryFile, memStats)

	// 导出profiles
	m.writeProfiles(baseFileName)

	// 清理旧文件
	m.cleanOldProfiles()
}

func (m *MemoryMonitor) writeProfiles(baseFileName string) {
	profiles := map[string]func(f *os.File) error{
		"heap": func(f *os.File) error {
			return pprof.WriteHeapProfile(f)
		},
		"goroutine": func(f *os.File) error {
			return pprof.Lookup("goroutine").WriteTo(f, 0)
		},
		"allocs": func(f *os.File) error {
			return pprof.Lookup("allocs").WriteTo(f, 0)
		},
		"threadcreate": func(f *os.File) error {
			return pprof.Lookup("threadcreate").WriteTo(f, 0)
		},
		"block": func(f *os.File) error {
			return pprof.Lookup("block").WriteTo(f, 0)
		},
	}

	for name, dumpFunc := range profiles {
		fileName := fmt.Sprintf("%s_%s.pprof", baseFileName, name)
		if f, err := os.Create(fileName); err == nil {
			if err := dumpFunc(f); err != nil {
				fmt.Fprintf(os.Stderr, "Failed to write %s profile: %v\n", name, err)
			}
			f.Close()
		} else {
			fmt.Fprintf(os.Stderr, "Failed to create %s profile file: %v\n", name, err)
		}
	}
}

func (m *MemoryMonitor) cleanOldProfiles() {
	files, err := os.ReadDir(m.config.profileDir)
	if err != nil {
		return
	}

	// 获取所有profile文件信息
	type fileInfo struct {
		name    string
		modTime time.Time
	}

	var fileInfos []fileInfo
	for _, file := range files {
		info, err := file.Info()
		if err != nil {
			continue
		}
		fileInfos = append(fileInfos, fileInfo{
			name:    file.Name(),
			modTime: info.ModTime(),
		})
	}

	// 按时间排序
	sort.Slice(fileInfos, func(i, j int) bool {
		return fileInfos[i].modTime.Before(fileInfos[j].modTime)
	})

	// 删除旧文件
	if len(fileInfos) > m.config.maxProfiles*5 { // 每次dump产生5个文件
		for _, fi := range fileInfos[:(len(fileInfos) - m.config.maxProfiles*5)] {
			os.Remove(fmt.Sprintf("%s/%s", m.config.profileDir, fi.name))
		}
	}
}

func (m *MemoryMonitor) handleSignals() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGTERM, syscall.SIGQUIT, syscall.SIGINT)

	for sig := range sigChan {
		fmt.Printf("Received signal: %v, dumping profiles\n", sig)
		m.dumpProfiles()
		os.Exit(1)
	}
}

// 辅助函数
func readMemoryLimit(path string) (uint64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	var limit uint64
	_, err = fmt.Sscanf(string(data), "%d", &limit)
	return limit, err
}

func writeMemoryStats(f *os.File, stats runtime.MemStats) {
	fmt.Fprintf(f, "=== Memory Stats ===\n")
	fmt.Fprintf(f, "Alloc: %v MB\n", stats.Alloc/1024/1024)
	fmt.Fprintf(f, "TotalAlloc: %v MB\n", stats.TotalAlloc/1024/1024)
	fmt.Fprintf(f, "Sys: %v MB\n", stats.Sys/1024/1024)
	fmt.Fprintf(f, "NumGC: %v\n", stats.NumGC)
	fmt.Fprintf(f, "HeapObjects: %v\n", stats.HeapObjects)
	fmt.Fprintf(f, "HeapAlloc: %v MB\n", stats.HeapAlloc/1024/1024)
	fmt.Fprintf(f, "HeapSys: %v MB\n", stats.HeapSys/1024/1024)
	fmt.Fprintf(f, "HeapIdle: %v MB\n", stats.HeapIdle/1024/1024)
	fmt.Fprintf(f, "HeapInuse: %v MB\n", stats.HeapInuse/1024/1024)
	fmt.Fprintf(f, "StackInuse: %v MB\n", stats.StackInuse/1024/1024)
	fmt.Fprintf(f, "GCCPUFraction: %v\n", stats.GCCPUFraction)
}
