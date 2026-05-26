package impl

import (
	"context"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/colinmarc/hdfs"
	"github.com/samber/lo"
)

type HdfsDaoImpl struct {
	hdfsClient *hdfs.Client
}

var _ dao.HdfsDao = (*HdfsDaoImpl)(nil)
var TcAiHdfsDaoImpl *HdfsDaoImpl
var TcAgiHdfsDaoImpl *HdfsDaoImpl

func init() {
	TcAiHdfsDaoImpl = NewHdfsDaoImpl("tc_ai")
	TcAgiHdfsDaoImpl = NewHdfsDaoImpl("tc_agi")
}
func NewHdfsDaoImpl(userName string) *HdfsDaoImpl {
	var client *hdfs.Client
	if userName == "tc_ai" {
		client = resource.NewTcAiHdfsClient()
	} else if userName == "tc_agi" {
		client = resource.NewTcAgiHdfsClient()
	}
	return &HdfsDaoImpl{
		hdfsClient: client,
	}
}
func (h *HdfsDaoImpl) ListDirFileNames(ctx context.Context, dirName string) ([]string, error) {
	fileInfos, err := h.hdfsClient.ReadDir(dirName)
	if err != nil {
		return []string{}, err
	}
	return lo.Map(fileInfos, func(item os.FileInfo, index int) string {
		return item.Name()
	}), nil
}
func (h *HdfsDaoImpl) ReadeFile(ctx context.Context, fileName string) (string, error) {
	res, err := h.hdfsClient.ReadFile(fileName)
	return string(res), err
}

func (h *HdfsDaoImpl) DownloadFile(ctx context.Context, sourceFilePath string, savePath string) error {
	err := h.hdfsClient.CopyToLocal(sourceFilePath, savePath)
	if err != nil {
		log.Errorf(ctx, "copy file error:%v", err)
	}
	return err
}

func (h *HdfsDaoImpl) UploadFile(ctx context.Context, sourceFilePath string, savePath string) error {
	log.Infof(ctx, "source:%s,save:%s", sourceFilePath, savePath)
	err := h.hdfsClient.CopyToRemote(sourceFilePath, savePath)
	if err != nil {
		log.Errorf(ctx, "upload file error:%v", err)
	}
	return err
}
