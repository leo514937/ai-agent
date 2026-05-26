package macro

import (
	"fmt"

	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/common/log"
)

// 定义日志类型, 业务过程日志
const ProcessLogType log.LogType = "aispProcess"

// 定义日志实体，业务过程日志
var ProcessNodeLog = log.NewDriverLog(fmt.Sprintf("[%s]|[%s]|[%s]|[%s:%s] %s",
	log.ZagLogType, log.RequestId, log.GraphName, log.NodeId, log.NodeName, log.MessageInfo),
	log.InfoLevel, ProcessLogType)
