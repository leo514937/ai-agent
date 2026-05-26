package util

import "math"

func CompareFloat(x, y float32) bool {
	return math.Abs(float64(x-y)) < 1e-6
}
