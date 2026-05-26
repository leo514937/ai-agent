package util

import (
	"math/rand"
	"time"

	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

// RandomPick 随机抽取指定数量的元素
func RandomPick[V any](slice []V, n int) []V {
	rand.Seed(time.Now().UnixNano()) // 初始化随机种子
	rand.Shuffle(len(slice), func(i, j int) {
		slice[i], slice[j] = slice[j], slice[i]
	})
	return slice[:util.Min(n, len(slice))]
}
