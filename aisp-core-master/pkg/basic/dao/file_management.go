package dao

import (
	"context"
)

type FileManagementDAO interface {
	UploadFile(ctx context.Context, fileContent []byte, path string) error
	DeleteFile(ctx context.Context, path string) error
	GetFileContent(ctx context.Context, path string) ([]byte, error)
	GenerateFileUrl(ctx context.Context, path string, contentType string) (string, error)
}
