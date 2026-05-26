package util

import (
	"fmt"
	"testing"
)

func TestCosineByDef(t *testing.T) {
	arr := make([][][]float32, 5)
	// init
	for i := range arr {
		arr[i] = make([][]float32, 3)
		for j := range arr[i] {
			arr[i][j] = make([]float32, 3)
		}
	}

	arr[0][0] = []float32{1.0, 2.0, 3.0}
	arr[0][1] = []float32{4.0, 5.0, 6.0}
	arr[0][2] = []float32{0.97463185}

	arr[1][0] = []float32{1.0, 2.0, 3.0}
	arr[1][1] = []float32{1.0, 2.0, 3.0}
	arr[1][2] = []float32{1.0000001}

	arr[2][0] = []float32{0.26726124, 0.5345225, 0.8017837}
	arr[2][1] = []float32{0.9282791, 0.20628424, 0.30942637}
	arr[2][2] = []float32{0.6064497}

	arr[3][0] = []float32{0.0, 0.0, 0.0}
	arr[3][1] = []float32{0.9282791, 0.20628424, 0.30942637}
	arr[3][2] = []float32{0.0}

	arr[4][0] = []float32{0.0, 0.5547002, 0.8320503}
	arr[4][1] = []float32{9.0, 2.0, 3.0}
	arr[4][2] = []float32{0.37188423}

	defaultValue := float64(0.0)
	for _, v := range arr {
		cosSim, err := CosineByDef(v[0], v[1], defaultValue, false)
		if err != nil {
			t.Error("Error:", err)
		} else {
			fmt.Printf("Cosine Similarity: %v,  Source Cosine Similarity: %v \n", cosSim, v[2][0])
		}
	}
}
