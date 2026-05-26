package mysql

import (
	"context"
	"fmt"
	"net/url"

	"git.in.zhihu.com/go/base/mysql"
	"git.in.zhihu.com/go/borm/connection"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"github.com/samber/lo"
)

var configClient = config.GetClient()

var pools = map[string]mysql.Pool{
	"aisp_core": lo.Must(mysql.Discovery("aisp")),
	"aisp_internal": util.SafeNew(func() (mysql.Pool, error) {
		return mysql.Discovery("aisp_internal")
	}),
	"luca_backend": util.SafeNew(func() (mysql.Pool, error) {
		return mysql.Discovery("luca-backend__luca_backend")
	}),
	"aisp_doris_internal": util.SafeNew(func() (mysql.Pool, error) {
		addr := lo.Must(url.Parse(configClient.GetString("mysql.aisp_internal.url")))
		return mysql.DiscoveryWithOptions("aisp_doris_interal", &mysql.Options{
			Name:       "aisp_doris_internal",
			MasterAddr: addr,
			SlaveAddrs: util.List(addr),
			DSNBuilder: func(opt *mysql.Options, u *url.URL) string {
				password, _ := u.User.Password()
				return fmt.Sprintf("%s:%s@tcp(%s)%s?%s", u.User.Username(), password, u.Host, u.Path, opt.RawQuery)
			},
			DriverName: "zhihu-mysql",
		})
	}),
}

type ZhihuConnection struct {
	connection.Connection
}

func (c *ZhihuConnection) WithTxn(ctx context.Context, f func() error) error {
	txnMgr := connection.NewTransactionManager(c.Connection)
	return txnMgr.Execute(ctx, func(_ context.Context) error {
		return f()
	})
}

func (c *ZhihuConnection) Begin(ctx context.Context) Transaction {
	return c.Connection.Begin(ctx)
}

func NewZhihuConnection(name string) *ZhihuConnection {
	pool, ok := pools[name]
	if !ok {
		panic(ErrNameNotFound)
	}
	return &ZhihuConnection{
		Connection: connection.NewMySQLConnection(pool),
	}
}

func init() {
	NewConnection = func(name string) Connection {
		return NewZhihuConnection(name)
	}
}
