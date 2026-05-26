package util

import (
	"math/rand"
)

func GenerateRandomString(length int) string {
	chars := []rune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
	randomString := make([]rune, length)
	for i := 0; i < length; i++ {
		randomString[i] = chars[rand.Intn(len(chars))]
	}
	return string(randomString)
}
