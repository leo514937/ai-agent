package rpc

import (
	"context"
)

type Oss interface {
	GetFileBytes(ctx context.Context, url string) ([]byte, error)
	GetFileBase64(ctx context.Context, url string) (string, error)
	GetOssFilePath(ctx context.Context, key string, appName string, sceneName string, spaceName string) string
}
