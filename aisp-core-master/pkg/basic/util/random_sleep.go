package util

import (
	"math/rand"
	"time"
)

// RandomSleep 随机睡眠指定范围的毫秒数
func RandomSleep(minMs, maxMs int) {
	if minMs >= maxMs {
		time.Sleep(time.Duration(minMs) * time.Millisecond)
		return
	}

	sleepTime := rand.Intn(maxMs-minMs+1) + minMs
	time.Sleep(time.Duration(sleepTime) * time.Millisecond)
}

// RandomSleepBetween 在指定范围内随机睡眠
func RandomSleepBetween(min, max time.Duration) {
	if min >= max {
		time.Sleep(min)
		return
	}

	diff := max - min
	randomDiff := time.Duration(rand.Int63n(int64(diff)))
	time.Sleep(min + randomDiff)
}
