package resource

import (
	"os"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
	"github.com/colinmarc/hdfs"
)

func NewTcAiHdfsClient() *hdfs.Client {
	if !env.RunOnline() {
		return nil
	}
	hdfsUser := os.Getenv("HADOOP_USER_NAME_TC_AI")
	client, err := hdfs.NewClient(hdfs.ClientOptions{
		Addresses: []string{"hdfs01:8020"},
		User:      hdfsUser,
	})
	utils.PanicIfWithStack(err)
	return client
}

func NewTcAgiHdfsClient() *hdfs.Client {
	if !env.RunOnline() {
		return nil
	}
	hdfsUser := os.Getenv("HADOOP_USER_NAME_TC_AGI")
	client, err := hdfs.NewClient(hdfs.ClientOptions{
		Addresses: []string{"hdfs01:8020"},
		User:      hdfsUser,
	})
	utils.PanicIfWithStack(err)
	return client
}
