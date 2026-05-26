package util

import (
	"context"
	"fmt"
	"math"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

// Cosine 计算两个向量的余弦
func Cosine(a []float32, b []float32) float64 {
	var (
		aLen  = len(a)
		bLen  = len(b)
		s     = float32(0.0)
		sa    = 0.0
		sb    = 0.0
		count = 0
	)
	if aLen > bLen {
		count = aLen
	} else {
		count = bLen
	}
	for i := 0; i < count; i++ {
		if i >= bLen {
			sa += math.Pow(cast.ToFloat64(a[i]), 2)
			continue
		}
		if i >= aLen {
			sb += math.Pow(cast.ToFloat64(b[i]), 2)
			continue
		}
		s += a[i] * b[i]
		sa += math.Pow(cast.ToFloat64(a[i]), 2)
		sb += math.Pow(cast.ToFloat64(b[i]), 2)
	}
	return cast.ToFloat64(s) / (math.Sqrt(sa) * math.Sqrt(sb))
}

// CosineByDefIgnoreNormalize 余弦计算两个向量之间的余弦相似度，使用默认值的边缘情况。
// 检查向量是否归一化或零向量，以避免冗余计算或错误
// 与上述 Cosine 计算有一定的差异，默认算法本次embedding返回的内容是做了归一处理的
func CosineByDefIgnoreNormalize(v1, v2 []float32, defaultValue float64) (float64, error) {
	return CosineByDef(v1, v2, defaultValue, true)
}

// CosineByDefIgnoreNormalize01 余弦计算两个向量之间的余弦相似度，使用默认值的边缘情况。
// 检查向量是否归一化或零向量，以避免冗余计算或错误
// 与上述 Cosine 计算有一定的差异，默认算法本次embedding返回的内容是做了归一处理的
func CosineByDefIgnoreNormalize01(v1, v2 []float32, defaultValue float64) (float64, error) {
	s, err := CosineByDef(v1, v2, defaultValue, true)
	if err != nil {
		log.Errorf(context.TODO(), "CosineByDefIgnoreNormalize01 error: %+v", err)

		return 0, err
	}

	return s*0.5 + 0.5, nil
}

// CosineByDef 余弦计算两个向量之间的余弦相似度，使用默认值的边缘情况。
// 检查向量是否归一化或零向量，以避免冗余计算或错误
// 与上述 Cosine 计算有一定的差异，默认算法本次embedding返回的内容是做了归一处理的
func CosineByDef(v1, v2 []float32, defaultValue float64, isIgnoreNormalize bool) (float64, error) {
	if len(v1) != len(v2) {
		msg := fmt.Sprintf("vector dimensions are not equal, vec1: %d, vec2: %d", len(v1), len(v2))
		return 0, fmt.Errorf(msg)
	}

	if isZeroVector(v1) || isZeroVector(v2) {
		return defaultValue, nil
	}

	// 如果向量还没有归一化，就归一化
	if !isIgnoreNormalize && !isNormalized(v1) {
		v1 = normalize(v1)
	}
	if !isIgnoreNormalize && !isNormalized(v2) {
		v2 = normalize(v2)
	}

	// 计算点积并返回float64
	var sum float32
	for i := range v1 {
		sum += v1[i] * v2[i]
	}
	return float64(sum), nil
}

// normalize 将一个向量归一化为它的L2 norm，但前提是它还没有归一化。
func normalize(vec []float32) []float32 {
	if isNormalized(vec) {
		return vec
	}

	normL2 := norm(vec)
	for i, v := range vec {
		vec[i] = v / normL2
	}
	return vec
}

// 判断是否是零向量
func isZeroVector(vec []float32) bool {
	for _, v := range vec {
		if v != 0 {
			return false
		}
	}
	return true
}

func norm(vec []float32) float32 {
	var sum float32
	for _, v := range vec {
		sum += v * v
	}
	return float32(math.Sqrt(float64(sum)))
}

// isNormalized 判断是否已经完成归一化
func isNormalized(vec []float32) bool {
	const tolerance = 1e-6
	return math.Abs(float64(norm(vec)-1)) < tolerance
}
