package impl

import (
	"context"
	"io"
	"strings"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/baidubce/bce-sdk-go/services/bos"
)

type FileManagementDaoImpl struct {
	bosClient *bos.Client
}

var DefaultFileManagementDAO *FileManagementDaoImpl

func init() {
	DefaultFileManagementDAO = newFileManagementDAO()
}

var (
	s3Key           = config.GetString("baidus3.accessKeyId", "")
	s3Secret        = config.GetString("baidus3.accessKeySecret", "")
	endpoint        = "bj.bcebos.com"
	bucketName      = "ai-data-nbaidu"
	expireInSeconds = 3600 * 24
)

func newFileManagementDAO() *FileManagementDaoImpl {
	bosClient, _ := bos.NewClient(s3Key, s3Secret, endpoint)

	return &FileManagementDaoImpl{
		bosClient: bosClient,
	}
}

func (f *FileManagementDaoImpl) UploadFile(ctx context.Context, fileContent []byte, path string) error {
	resp, err := f.bosClient.PutObjectFromBytes(bucketName, path, fileContent, nil)

	log.Infof(ctx, "save file:%s, result：%v. err=%v", path, resp, err)

	return err
}

func (f *FileManagementDaoImpl) GetFileContent(ctx context.Context, path string) ([]byte, error) {
	resp, err := f.bosClient.GetObject(bucketName, path, nil)
	log.Infof(ctx, "get file:%s, err=%v", path, err)
	if err != nil {
		return []byte{}, err
	}

	content, err := io.ReadAll(resp.Body)
	return content, err
}

func (f *FileManagementDaoImpl) GenerateFileUrl(ctx context.Context, path string, contentType string) (string, error) {
	headers := map[string]string{
		"Content-Type": contentType,
	}

	fileUrl := f.bosClient.GeneratePresignedUrl(bucketName, path, expireInSeconds, "GET", headers, nil)
	log.Infof(ctx, "get file path :%s", fileUrl)
	if strings.HasPrefix(fileUrl, "http://") {
		fileUrl = strings.Trim(fileUrl, "http://")
	}
	return fileUrl, nil
}

func (f *FileManagementDaoImpl) DeleteFile(ctx context.Context, path string) error {
	err := f.bosClient.DeleteObject(bucketName, path)
	log.Infof(ctx, "delete file path :%s. err=%v", path, err)
	return err
}
