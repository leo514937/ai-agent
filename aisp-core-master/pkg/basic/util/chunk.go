package util

// ChunkArrWithLimitStrLength 根据limit 限制字符串长度，判断切割数组
func ChunkArrWithLimitStrLength[V any](collection []V, limit int, predicate func(item V) string) []V {
	if collection == nil || len(collection) == 0 || limit <= 0 {
		return []V{}
	}
	currLen := 0
	endIndex := 0
	for _, item := range collection {
		tmpLen := currLen + UnicodeLen(predicate(item))
		if tmpLen > limit {
			break
		}
		endIndex++
		currLen = tmpLen
	}
	if endIndex == 0 {
		return []V{}
	}
	return collection[:endIndex]
}
