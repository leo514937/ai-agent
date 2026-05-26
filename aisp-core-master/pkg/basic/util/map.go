package util

func OverrideMap[K comparable, V any](sourceMap map[K]V, newMap map[K]V) map[K]V {
	resMap := make(map[K]V)
	if sourceMap != nil {
		for key, value := range sourceMap {
			resMap[key] = value
		}
	}
	if newMap != nil {
		for key, value := range newMap {
			resMap[key] = value
		}
	}
	return resMap
}
