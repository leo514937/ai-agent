package dao

import (
	"context"
)

type HdfsDao interface {
	ListDirFileNames(ctx context.Context, dirName string) ([]string, error)
	ReadeFile(ctx context.Context, fileName string) (string, error)
	DownloadFile(ctx context.Context, sourceFilePath string, savePath string) error
	UploadFile(ctx context.Context, sourceFilePath string, savePath string) error
}
