package resource

import (
	"os"

	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/beltran/gohive"
)

type HiveClient struct {
	conn *gohive.Connection
}

func NewHiveClient() *HiveClient {
	configuration := gohive.NewConnectConfiguration()
	configuration.Username = os.Getenv("HADOOP_USER_NAME")
	configuration.Password = os.Getenv("HADOOP_USER_PASSWORD")
	configuration.HiveConfiguration = map[string]string{
		"mapreduce.job.queuename": os.Getenv("HADOOP_JOB_QUEUE"),
	}

	conn, err := gohive.Connect("hive-adhoc", 10000, "NOSASL", configuration)
	util.PanicIf(err)

	return &HiveClient{
		conn: conn,
	}
}

func (h *HiveClient) GetCursor() *gohive.Cursor {
	return h.conn.Cursor()
}

func (h *HiveClient) Close() error {
	return h.conn.Close()
}
