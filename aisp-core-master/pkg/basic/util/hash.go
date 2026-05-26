package util

import (
	"crypto/sha256"
	"encoding/binary"
)

func Hash64(text string) int64 {
	if text == "" {
		return 0
	}

	// 使用 SHA-256 计算哈希值
	hash := sha256.New()
	hash.Write([]byte(text))
	hashBytes := hash.Sum(nil)

	// 取前8个字节转换为uint64，再转换为int64
	// 通过位运算确保结果为正数
	result := int64(binary.BigEndian.Uint64(hashBytes)) & 0x7FFFFFFFFFFFFFFF

	return result
}
