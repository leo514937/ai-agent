package util

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"math"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

const byteCountOfFloat32 = 4

func ConvertByteArrayToFloat32Array(originBytes []byte) ([]float32, error) {
	floatCount := len(originBytes) / byteCountOfFloat32
	retvals := make([]float32, floatCount)
	for i := 0; i < floatCount; i++ {
		floatBytes := originBytes[i*byteCountOfFloat32 : i*byteCountOfFloat32+byteCountOfFloat32]
		buf := bytes.NewBuffer(floatBytes)
		var retval float32
		err := binary.Read(buf, binary.LittleEndian, &retval)
		if err != nil {
			ctx := context.Background()
			log.WithError(ctx, err).Error(ctx, "parse []byte to []float32 error")
			return nil, err
		}
		retvals[i] = retval
	}

	return retvals, nil
}

func ConvertByteArrayToInt64Array(originBytes []byte) ([]int64, error) {
	const byteCountOfInt64 = 8
	int64Count := len(originBytes) / byteCountOfInt64
	retvals := make([]int64, int64Count)
	for i := 0; i < int64Count; i++ {
		int64Bytes := originBytes[i*byteCountOfInt64 : i*byteCountOfInt64+byteCountOfInt64]
		buf := bytes.NewBuffer(int64Bytes)
		var retval int64
		err := binary.Read(buf, binary.LittleEndian, &retval)
		if err != nil {
			ctx := context.Background()
			log.WithError(ctx, err).Error(ctx, "parse []byte to []int64 error")
			return nil, err
		}
		retvals[i] = retval
	}
	return retvals, nil
}

func ConvertByteArrayToStringArray(originBytes []byte) ([]string, error) {
	var retvals []string
	buf := bytes.NewBuffer(originBytes)
	for buf.Len() > 0 {
		var length uint32
		err := binary.Read(buf, binary.LittleEndian, &length)
		if err != nil {
			ctx := context.Background()
			log.WithError(ctx, err).Error(ctx, "parse length from []byte to string error")
			return nil, err
		}

		strBytes := make([]byte, length)
		_, err = buf.Read(strBytes)
		if err != nil {
			ctx := context.Background()
			log.WithError(ctx, err).Error(ctx, "parse string from []byte error")
			return nil, err
		}

		retvals = append(retvals, string(strBytes))
	}

	return retvals, nil
}

// Split1DArrayToMultiDArray 把一维数组，切分为多维数组，每个数组的维度是secondShape
func Split1DArrayToMultiDArray[T any](array1d []T, firstShape int, secondShape int) [][]T {
	if len(array1d) != secondShape*firstShape {
		ctx := context.Background()
		log.Errorf(ctx, "维度不一致")
	}
	return lo.Chunk(array1d, secondShape)
}

// ConvertFp16ByteToFloat32 把 fp16 的 byte 数组转成 float32。半精度 float 两位表达一个数字
func ConvertFp16ByteToFloat32(data []byte) ([]float32, error) {
	if len(data)%2 != 0 {
		return nil, fmt.Errorf("invalid data length")
	}

	float32Array := make([]float32, len(data)/2)
	for i := 0; i < len(data); i += 2 {
		fp16 := binary.LittleEndian.Uint16(data[i : i+2])
		float32Array[i/2] = fp16ToFloat32(fp16)
	}

	return float32Array, nil
}

// fp16ToFloat32 converts a 16-bit floating point number (fp16) to a 32-bit floating point number (float32)
func fp16ToFloat32(fp16 uint16) float32 {
	sign := (fp16 >> 15) & 0x0001
	exp := (fp16 >> 10) & 0x001F
	frac := fp16 & 0x03FF

	var fp32 uint32
	if exp == 0 {
		// Subnormal number
		if frac == 0 {
			fp32 = uint32(sign) << 31
		} else {
			exp = 1
			for (frac & 0x0400) == 0 {
				frac <<= 1
				exp--
			}
			frac &= 0x03FF
			fp32 = (uint32(sign)<<31 | uint32((exp+127-15))<<23 | uint32(frac)<<13)
		}
	} else if exp == 0x1F {
		// Infinity or NaN
		fp32 = uint32(sign)<<31 | 0x7F800000 | uint32(frac)<<13
	} else {
		// Normalized number
		fp32 = uint32(sign)<<31 | uint32((exp+127-15))<<23 | uint32(frac)<<13
	}

	return math.Float32frombits(fp32)
}
