package util

import (
	"math/rand"
)

func Any(b ...bool) bool {
	for _, v := range b {
		if v {
			return true
		}
	}
	return false
}

func StringInSlice(word string, list []string) bool {
	for _, element := range list {
		if word == element {
			return true
		}
	}
	return false
}

func IntInSlice(num int, list []int) bool {
	for _, element := range list {
		if num == element {
			return true
		}
	}
	return false
}

// RandomElement 从给定的数组中随机选择一个元素并返回
func RandomElement[V any](arr []V) V {
	randomIndex := rand.Intn(len(arr))
	return arr[randomIndex]
}

func SplitSlice(slice [][]float32, batchSize int) [][][]float32 {
	var batches [][][]float32
	for i := 0; i < len(slice); i += batchSize {
		end := i + batchSize

		if end > len(slice) {
			end = len(slice)
		}

		batches = append(batches, slice[i:end])
	}
	return batches
}

// MergeSlices 合并多个切片成一个切片
func MergeSlices[T any](slices ...[]T) []T {
	var merged []T
	for _, slice := range slices {
		merged = append(merged, slice...)
	}
	return merged
}

func UniqueElementSlice[T string | int | int32 | int64](arr []T) []T {
	keys := make(map[T]bool)
	result := make([]T, 0)
	for _, ele := range arr {
		if _, ok := keys[ele]; !ok {
			keys[ele] = true
			result = append(result, ele)
		}
	}
	return result
}
