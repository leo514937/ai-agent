package mysql

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/mysql"
	"git.in.zhihu.com/go/borm"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type Result struct {
	LastInsertedID int64
	AffectedRows   int64
}

var (
	AispInternalBorm   *borm.ORM
	AispCoreBorm       *borm.ORM
	LucaBorm           *borm.ORM
	CrawlerWebPageBorm *borm.ORM
)

const dbNameAispInternal = "aisp_internal"
const dbNameAispCore = "aisp"
const dbNameLucaBackend = "luca-backend"
const crawlerWebPage = "ai-ingress__crawler_webpage_ob"

func initLucaBackend() {
	lucaDiscovery, err := mysql.Discovery("luca-backend__luca_backend")
	if err != nil {
		if conf.GetEnvPath() == env.ProductionEnv {
			panic("no db luca_backend")
		} else {
			log.WithError(context.Background(), err)
			return
		}
	}

	// 传入这里的正确格式是：user_name:password@tcp(address:port)/db?
	lucaBackendMysqlConf := borm.NewMySQLConfigWithSqlDB(
		lucaDiscovery.Master(),
		borm.MaxIdle(20),
		borm.MaxLifetime(1*time.Hour),
		borm.MaxOpen(20),
	).WithName(dbNameLucaBackend)

	borm.AddStore(lucaBackendMysqlConf)

	LucaBorm = borm.New().UseStore(dbNameLucaBackend)
}

func initAispInternal() {
	// borm文档：https://git.in.zhihu.com/go/borm/-/blob/master/USERGUIDE.md
	aispInternalDiscovery, err := mysql.Discovery(dbNameAispInternal)
	if err != nil {
		if conf.GetEnvPath() == env.ProductionEnv {
			panic("no db aisp_internal")
		} else {
			log.WithError(context.Background(), err)
			return
		}
	}

	// 传入这里的正确格式是：user_name:password@tcp(address:port)/db?
	aispInternalMysqlConf := borm.NewMySQLConfigWithSqlDB(
		aispInternalDiscovery.Master(),
		borm.MaxIdle(20),
		borm.MaxLifetime(1*time.Hour),
		borm.MaxOpen(20),
	).WithName(dbNameAispInternal)
	borm.AddStore(aispInternalMysqlConf)

	AispInternalBorm = borm.New().UseStore(dbNameAispInternal)
}

func initAispCore() {
	// borm文档：https://git.in.zhihu.com/go/borm/-/blob/master/USERGUIDE.md
	aispInternalDiscovery, err := mysql.Discovery(dbNameAispCore)
	if err != nil {
		if conf.GetEnvPath() == env.ProductionEnv {
			panic("no db aisp_internal")
		} else {
			log.WithError(context.Background(), err)
			return
		}
	}

	// 传入这里的正确格式是：user_name:password@tcp(address:port)/db?
	aispCoreMysqlConf := borm.NewMySQLConfigWithSqlDB(
		aispInternalDiscovery.Master(),
		borm.MaxIdle(20),
		borm.MaxLifetime(1*time.Hour),
		borm.MaxOpen(20),
	).WithName(dbNameAispCore)
	borm.AddStore(aispCoreMysqlConf)

	AispCoreBorm = borm.New().UseStore(dbNameAispCore)
}

func initCrawlerWebPage() {
	// borm文档：https://git.in.zhihu.com/go/borm/-/blob/master/USERGUIDE.md
	crawlerWebPageDiscovery, err := mysql.Discovery(crawlerWebPage)
	if err != nil {
		if conf.GetEnvPath() == env.ProductionEnv {
			panic("no db crawler web page")
		} else {
			log.WithError(context.Background(), err)
			return
		}
	}

	conf := borm.NewMySQLConfigWithSqlDB(
		crawlerWebPageDiscovery.Master(),
		borm.MaxIdle(20),
		borm.MaxLifetime(1*time.Hour),
		borm.MaxOpen(20),
	).WithName(crawlerWebPage)
	borm.AddStore(conf)

	CrawlerWebPageBorm = borm.New().UseStore(crawlerWebPage)
}

func init() {
	initAispInternal()
	initAispCore()
	initLucaBackend()
	initCrawlerWebPage()
}
