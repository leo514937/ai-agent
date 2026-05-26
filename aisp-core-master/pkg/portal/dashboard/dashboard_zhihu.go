package dashboard

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
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/ai_daily/handler_ai_daily"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/handler_zhihu"
	aispMiddleware "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	chiMiddleware "github.com/go-chi/chi/middleware"
	"github.com/samber/lo"
)

func getHandlers() map[string]rest.Handler {
	return map[string]rest.Handler{
		"/api/currentuser": handler_zhihu.NewCurrentUserHandler(),

		"/api/biz-lines":     handler_zhihu.NewBizLinesHandler(),
		"/api/apps":          handler_zhihu.NewAppsHandler(),
		"/api/models":        handler_zhihu.NewModelsHandler(),
		"/api/skus":          handler_zhihu.NewSkusHandler(),
		"/api/billing/usage": handler_zhihu.NewModelUsageHandler(),
		"/api/billing/bills": handler_zhihu.NewModelBillsHandler(),
		"/api/billing/cost":  handler_zhihu.NewModelCostHandler(),

		"/api/arenas":                                handler_zhihu.NewArenasHandler(),
		"/api/arenas/play":                           handler_zhihu.NewArenasPlayHandler(),
		"/api/arenas/multi-play":                     handler_zhihu.NewArenasMultiPlayHandler(),
		"/api/arenas/{arenaID}":                      handler_zhihu.NewArenaDetailHandler(),
		"/api/arenas/{arenaID}/play":                 handler_zhihu.NewArenaDetailPlayHandler(),
		"/api/arenas/{arenaID}/match":                handler_zhihu.NewArenasMatchHandler(),
		"/api/arenas/{arenaID}/match/input-template": handler_zhihu.NewArenasMatchInputTemplateHandler(),
		"/api/arenas/parse-prompt":                   handler_zhihu.NewArenasParsePromptHandler(),

		"/api/models/{modelName}/playground/generate-image": handler_zhihu.NewPlaygroundGenerateImageHandler(),
		"/api/models/{modelName}/playground/chat":           handler_zhihu.NewPlaygroundChatHandler(),

		"/api/feedbacks": handler_zhihu.NewFeedbacksHandler(),

		"/api/operation-base/authority":                  handler_zhihu.NewOperationBaseAuthorityHandler(),
		"/api/operation-base/scenes":                     handler_zhihu.NewOperationBaseScenesHandler(),
		"/api/operation-base/knowledge-base/list":        handler_zhihu.NewKnowledgeBaseListHandler(),
		"/api/operation-base/knowledge-base/add":         handler_zhihu.NewKnowledgeBaseAddOrUpdateHandler(),
		"/api/operation-base/knowledge-base/upload":      handler_zhihu.NewKnowledgeBaseUploadHandler(),
		"/api/operation-base/knowledge-base/{id}/update": handler_zhihu.NewKnowledgeBaseAddOrUpdateHandler(),
		"/api/operation-base/static-base/list":           handler_zhihu.NewStaticBaseListHandler(),
		"/api/operation-base/static-base/add":            handler_zhihu.NewStaticBaseAddOrUpdateHandler(),
		"/api/operation-base/static-base/upload":         handler_zhihu.NewStaticBaseUploadHandler(),
		"/api/operation-base/static-base/{id}/update":    handler_zhihu.NewStaticBaseAddOrUpdateHandler(),

		"/api/operation-base/faq-base/list":        handler_zhihu.NewFaqBaseListHandler(),
		"/api/operation-base/faq-base/add":         handler_zhihu.NewFaqBaseAddOrUpdateHandler(),
		"/api/operation-base/faq-base/upload":      handler_zhihu.NewFaqBaseUploadHandler(),
		"/api/operation-base/faq-base/{id}/update": handler_zhihu.NewFaqBaseAddOrUpdateHandler(),

		"/api/operation-base/tracing/list":         handler_zhihu.NewTracingListHandler(),
		"/api/operation-base/tracing/detail":       handler_zhihu.NewTracingDetailHandler(),
		"/api/operation-base/tracing/download":     handler_zhihu.NewTracingDownloadHandler(),
		"/api/operation-base/tracing/agent-detail": handler_zhihu.NewTracingEventHandler(),

		"/api/badcase-tracing/list":     handler_zhihu.NewBadCaseTracingListHandler(),
		"/api/badcase-tracing/process":  handler_zhihu.NewBadCaseTracingProcessHandler(),
		"/api/badcase-tracing/add":      handler_zhihu.NewBadCaseTracingInsertHandler(),
		"/api/badcase-tracing/update":   handler_zhihu.NewBadCaseTracingUpdateHandler(),
		"/api/badcase-tracing/delete":   handler_zhihu.NewBadCaseTracingDeleteHandler(),
		"/api/badcase-tracing/resolved": handler_zhihu.NewBadCaseTracingUpdateToBeResolvedHandler(),
		"/api/badcase-tracing/download": handler_zhihu.NewBadCaseTracingDownloadHandler(),

		"/api/knowledge-base":      handler_zhihu.NewKnowledgeBasesHandler(),
		"/api/knowledge-base/{id}": handler_zhihu.NewSingleKnowledgeBasesHandler(),

		"/api/knowledge-base/document":             handler_zhihu.NewKnowledgeBasesDocHandler(),
		"/api/knowledge-base/document/{id}":        handler_zhihu.NewKnowledgeBasesSingleDocHandler(),
		"/api/knowledge-base/document/detail":      handler_zhihu.NewKnowledgeBasesDocDetailHandler(),
		"/api/knowledge-base/document/parse_state": handler_zhihu.NewKnowledgeBasesDocParseStateHandler(),

		"/api/knowledge-base/find": handler_zhihu.NewKnowledgeBasesDocFindHandler(),

		"/api/hot-content-product":          handler_zhihu.NewHotContentProductHandler(),
		"/api/hot-content-product/trend":    handler_zhihu.NewHotContentProductTrendHandler(),
		"/api/hot-content-product/download": handler_zhihu.NewHotContentProductDownloadHandler(),

		"/api/hot-content/synonym":        handler_zhihu.NewHotContentSynonymHandler(),
		"/api/hot-content/synonym/upload": handler_zhihu.NewHotContentSynonymUploadHandler(),
		"/api/hot-content/synonym/{id}":   handler_zhihu.NewHotContentSingleSynonymHandler(),

		"/api/translate": handler_zhihu.NewTranslateHandler(),

		"/api/ai-daily/query": handler_ai_daily.NewGetPlaylistInternalHandler(),

		// 直答服务 HTTP 接口
		"/api/zhida/recall":         handler_zhihu.NewZhidaRecallHandler(),
		"/api/zhida/content-core":   handler_zhihu.NewContentCoreHandler(),
		"/api/zhida/knowledge-base": handler_zhihu.NewKnowledgeBaseDetailHandler(),
		"/api/zhida/author-detail":  handler_zhihu.NewAuthorDetailHandler(),

		// 百度s3 session token 授权
		"/api/s3/session_token": handler_zhihu.NewS3AccessHandler(),
	}
}

var apiLogProducer = lo.Must(kafka.GetProducer(context.Background(), macro.DashboardAPILogTopic))

func init() {
	router.Use(middleware.Base)
	router.Use(middleware.RealIP)
	router.Use(rest.DefaultRequestContext)
	router.Use(middleware.CheckHealth)
	router.Use(middleware.PanicAsError)
	router.Use(aispMiddleware.AsyncConnection(
		time.Second*10, time.Minute*10, time.Minute*10,
		"/api/async-connection",
		newAsyncConnStorageAdapter(),
		util.List(`^/api/arenas/.*/match$`, `^/api/ai-daily/.*`, `^/api/translate$`, `^/api/hot-content-product/*`),
	))
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
				userEmail := ""
				user := middleware.AuthingUserFromContext(ctx)
				if user != nil {
					userEmail = user.Email
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
					"user":        userEmail,
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

	secret := configClient.GetString("authing_secret")
	if !macro.Debug && secret != "" {
		authingMiddleware := aispMiddleware.Authing(configClient.GetString("authing_app_id"), secret, configClient.GetString("authing_callback_url"))
		router.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				// 直答 http 接口为算法测试使用，路径以 /api/zhida 开头，跳过鉴权
				if strings.HasPrefix(r.URL.Path, "/api/zhida") {
					next.ServeHTTP(w, r)
					return
				}
				authingMiddleware(next).ServeHTTP(w, r)
			})
		})
	}
	router.Use(chiMiddleware.Logger)

	RegisterAispCoreDashboardHTTPServer = func(server httpport.Server) {
		router.MountHandlers(getHandlers())
		server.(interface{ SetHandler(handler http.Handler) }).SetHandler(router)
		resources.InitAIDailyLogic()
		graph.InitZagDriver(graph_constant.ApiAIDailyPlaylist)
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
