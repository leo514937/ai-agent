package arena_worker

import (
	"os"
	"os/signal"
	"syscall"
	"time"

	"git.in.zhihu.com/go/utils"
	dashboard "git.in.zhihu.com/zhihu/aisp-core/pkg/business/dashboard_zhihu"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func Main() {
	closer := make(chan struct{})
	chsig := make(chan os.Signal, 1)
	signal.Notify(chsig, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-chsig
		close(closer)
	}()

	txn, ctx := log.StartTransaction("arena_worker")
	defer txn.End(ctx)

	for i := 0; i != 10; i++ {
		utils.SafelyGo(func() {
			utils.PanicIf(dashboard.DefaultArenaBiz.ProcessShots(ctx, closer))
		}, func(err error) {
			log.WithError(ctx, err).Error(ctx, "process shots failed")
		})
	}
	<-closer
	time.Sleep(time.Second * 60)
}
