package grpc_util

import (
	"math/rand"
	"time"
)

// SampleWithProbability 抽样器
func SampleWithProbability(p float64) bool {
	if p < 0.01 || p > 1 {
		return false
	}
	// 使用当前时间作为随机数生成器的种子，但通过New实例化避免直接调用Seed
	r := rand.New(rand.NewSource(time.Now().UnixNano()))
	// 生成一个[0, 1)之间的随机浮点数
	randomValue := r.Float64()
	// 如果随机数小于或等于给定的概率p，则返回true，否则返回false
	return randomValue <= p
}
