package resource

import "git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"

var (
	MySQLAISPCore mysql.Connection
)

func init() {
	MySQLAISPCore = mysql.NewConnection("aisp_core")
}
