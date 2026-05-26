package util

// CheckEmbedding 全 0 不行
func CheckEmbedding(embeddingA []float32) bool {
	embeddingValid := false
	if len(embeddingA) == 0 {
		return false
	}
	for _, v := range embeddingA {
		if v != 0 {
			embeddingValid = true
			break
		}
	}
	return embeddingValid
}

// CheckTwoDimEmbedding 检查二维嵌入是否有效
func CheckTwoDimEmbedding(embeddingA [][]float32) bool {
	embeddingValid := false
	if len(embeddingA) == 0 {
		return false
	}
	for _, x := range embeddingA {
		for _, y := range x {
			if y != 0 {
				embeddingValid = true
				break
			}
		}
	}
	return embeddingValid
}
