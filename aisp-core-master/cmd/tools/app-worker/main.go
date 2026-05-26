package main

import (
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

func main() {
	txn, ctx := log.StartTransaction("app_worker")
	defer txn.End(ctx)

	apps := lo.Must(dao.DefaultAppDAO.ListApp(ctx, "", ""))
	for _, app := range apps {
		appDetail := lo.Must(rpc.DefaultOneRPC.GetAppByName(ctx, app.Name))
		lo.Must0(dao.DefaultAppDAO.SetAppBizLineName(ctx, app.Name, appDetail.OwnerBizLineName))
		time.Sleep(time.Millisecond * 100)
	}
}
