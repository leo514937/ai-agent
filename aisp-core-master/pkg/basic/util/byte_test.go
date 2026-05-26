package util

import (
	"fmt"
	"testing"
)

func TestByte(t *testing.T) {
	data := []byte{212, 59} // 1.0 and -2.0 in fp16

	float32Array, err := ConvertFp16ByteToFloat32(data)
	if err != nil {
		fmt.Println("Error:", err)
		return
	}

	for i, f := range float32Array {
		fmt.Printf("float32[%d]: %f\n", i, f)
	}
}
