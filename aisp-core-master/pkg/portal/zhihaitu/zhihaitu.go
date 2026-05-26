package zhihaitu

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	zhihaitu_resource "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/handler_zhihu"
	aispMiddleware "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/handler"
	zhtMiddleware "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
	chiMiddleware "github.com/go-chi/chi/middleware"
	"github.com/samber/lo"
)

var (
	RegisterZhihaituHTTPServer func(httpport.Server)
)

func getHandlers() map[string]rest.Handler {
	return map[string]rest.Handler{
		"/api/account/v1/login":      handler.NewLoginHandler(),
		"/api/account/v1/isExist":    handler.NewIsExistHandler(),
		"/api/account/v1/logout":     handler.NewLogoutHandler(),
		"/api/account/v1/checkToken": handler.NewCheckTokenHandler(),

		"/api/chat/v1/submitMsg":          handler.NewSubmitMsgHandler(),
		"/api/chat/v1/getMsgsByConvID":    handler.NewGetMsgsByConvIdHandler(),
		"/api/chat/v1/queryMsg":           handler.NewQueryMsgHandler(),
		"/api/chat/v1/msg/feedback":       handler.NewFeedBackHandler(),
		"/api/chat/v1/deleteConvMsg":      handler.NewDeleteConvMsgHandler(),
		"/api/chat/v1/msg/suggestion":     handler.NewSuggestionHandler(),
		"/api/chat/v1/msg/userSuggestion": handler.NewSuggestionHandler(),
		"/api/chat/v1/reportMsg":          handler.NewReportHandler(),
		"/api/chat/v1/getReportMsgs":      handler.NewGetReportMsgHandler(),

		"/api/chat/v1/simChat":  handler.NewSimChatHandler(false), //给网信办提供的评测api
		"/api/chat/v1/simChat2": handler.NewSimChatHandler(true),  //网安接口
	}
}

var apiLogProducer = lo.Must(kafka.GetProducer(context.Background(), macro.DashboardAPILogTopic))

func init() {
	router.Use(middleware.Base)
	router.Use(middleware.RealIP)
	router.Use(rest.DefaultRequestContext)
	router.Use(middleware.CheckHealth)
	router.Use(middleware.PanicAsError)
	router.Use(middleware.PanicAsError)
	router.Use(middleware.ZhihuCORS(strings.Split(config.GetString("origins", ""), ",")))
	chiMiddleware.DefaultLogger = func(next http.Handler) http.Handler {
		fn := func(w http.ResponseWriter, r *http.Request) {
			ww := chiMiddleware.NewWrapResponseWriter(w, r.ProtoMajor)
			respBuff := bytes.NewBuffer(nil)
			ww.Tee(respBuff)
			reqBuff := handler_zhihu.NewBufferedReadCloser(r.Body)
			r.Body = reqBuff

			t1 := time.Now()
			defer func() {
				ctx := r.Context()
				userName := ""
				account := zhtMiddleware.GetUserFromContext(ctx)
				if account != nil {
					userName = account.Name
				}
				record := map[string]interface{}{
					"func":        "chiMiddleware.DefaultLogger",
					"req_uri":     r.RequestURI,
					"resp_status": ww.Status(),
					"resp_body":   respBuff.String(),
					"req_body":    reqBuff.String(),
					"elapsed":     time.Since(t1).Milliseconds(),
					"req_referer": r.Referer(),
					"req_ua":      r.UserAgent(),
					"req_ip":      r.RemoteAddr,
					"req_method":  r.Method,
					"user":        userName,
					"ts":          time.Now().Unix(),
				}
				log.WithFields(ctx, record).Infof(ctx, "request")
				_ = apiLogProducer.AsyncSend(ctx, &kafka.ProducerMessage{
					Value: lo.Must(json.Marshal(record)),
				})
			}()

			next.ServeHTTP(ww, r)
		}
		return http.HandlerFunc(fn)
	}

	if !macro.Debug {
		router.Use(zhtMiddleware.Authing())
	}
	router.Use(chiMiddleware.Logger)

	router.MountHandlers(getHandlers())

	RegisterZhihaituHTTPServer = func(server httpport.Server) {
		server.(interface{ SetHandler(handler http.Handler) }).SetHandler(router)

		zhihaitu_resource.Init(graph_constant.ApiZhihaituChat)
	}
}

var (
	router       = rest.NewRouter()
	configClient = config.GetClient()
)

type asyncConnStorageAdapter struct {
	storage dao.AsyncHTTPConnDAO
}

func (a *asyncConnStorageAdapter) Get(ctx context.Context, connID string) (*aispMiddleware.AsyncConn, error) {
	conn, err := a.storage.GetAsyncHTTPConn(ctx, connID)
	if err != nil {
		return nil, err
	}
	ret := &aispMiddleware.AsyncConn{
		ID: conn.ID,
	}
	if conn.Resp != nil {
		ret.Resp = &aispMiddleware.AsyncConnResp{StatusCode: conn.Resp.StatusCode, Header: conn.Resp.Header, Body: conn.Resp.Body}
	}
	return ret, nil
}

func (a *asyncConnStorageAdapter) Set(ctx context.Context, connID string, conn *aispMiddleware.AsyncConn) error {
	if conn.Resp == nil {
		return a.storage.SetAsyncHTTPConn(ctx, &model.AsyncHTTPConn{ID: conn.ID})
	}
	return a.storage.SetAsyncHTTPConn(ctx, &model.AsyncHTTPConn{
		ID:   conn.ID,
		Resp: &model.AsyncConnResp{StatusCode: conn.Resp.StatusCode, Header: conn.Resp.Header, Body: conn.Resp.Body},
	})
}

var _ aispMiddleware.AsyncConnStorage = (*asyncConnStorageAdapter)(nil)

func newAsyncConnStorageAdapter() *asyncConnStorageAdapter {
	return &asyncConnStorageAdapter{storage: dao.DefaultAsyncHTTPConnDAO}
}
