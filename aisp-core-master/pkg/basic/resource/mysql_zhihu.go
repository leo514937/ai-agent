package resource

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

var (
	DorisAISPInternal mysql.Connection
	MySQLAISPInternal mysql.Connection
)

func init() {
	DorisAISPInternal = mysql.NewConnection("aisp_doris_internal")
	MySQLAISPInternal = mysql.NewConnection("aisp_internal")
}
