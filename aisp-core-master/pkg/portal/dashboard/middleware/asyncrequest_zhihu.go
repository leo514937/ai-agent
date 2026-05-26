package middleware

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"regexp"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
	"github.com/samber/lo"
)

// AsyncConnection is a middleware that keeps the connection alive by convert long time request to async request.
// It is used to avoid the connection closed by the load balancer.
// If any request is longer than firstRequestTimeout, it will be converted to async request.
// If any async request is longer than asyncTimeout, it will be terminated.
// All async request will be recycled after recycleTimeout.
func AsyncConnection(
	firstRequestTimeout, asyncTimeout, recycleTimeout time.Duration,
	connDetailEndpoint string,
	connStorage AsyncConnStorage,
	skipList []string) func(next http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			for _, skip := range skipList {
				if matched, _ := regexp.MatchString(skip, r.URL.Path); matched {
					next.ServeHTTP(w, r)
					return
				}
			}

			if r.URL.Path == connDetailEndpoint {
				connID := r.URL.Query().Get("conn_id")
				if connID == "" {
					w.WriteHeader(http.StatusBadRequest)
					w.Write(lo.Must(json.Marshal(map[string]any{
						"success": false,
					})))
					return
				}
				conn, err := connStorage.Get(r.Context(), connID)
				if err != nil {
					w.WriteHeader(http.StatusInternalServerError)
					w.Write(lo.Must(json.Marshal(map[string]any{
						"success": false,
					})))
					return
				}
				if conn == nil {
					w.WriteHeader(http.StatusNotFound)
					w.Write(lo.Must(json.Marshal(map[string]any{
						"success": false,
					})))
					return
				}
				if conn.Resp == nil {
					w.WriteHeader(http.StatusAccepted)
					w.Write(lo.Must(json.Marshal(map[string]any{
						"success": true,
					})))
					return
				}
				for k, v := range conn.Resp.Header {
					w.Header()[k] = v
				}
				w.WriteHeader(conn.Resp.StatusCode)
				w.Write(conn.Resp.Body)
			} else {
				ww := NewBufferedResponseWriter()
				done := make(chan struct{})
				taskCtx, cancel := context.WithTimeout(NoCancelCtx(r.Context()), recycleTimeout)
				connID := lo.Must(uuid.NewRandom()).String()

				go func() {
					lo.Must0(connStorage.Set(taskCtx, connID, &AsyncConn{
						ID:  connID,
						TTL: asyncTimeout + firstRequestTimeout + recycleTimeout,
					}))
					defer cancel()
					defer close(done)
					defer func() {
						log.Info(taskCtx, "async request finished")
						lo.Must0(connStorage.Set(taskCtx, connID, &AsyncConn{
							ID:   connID,
							TTL:  recycleTimeout,
							Resp: &AsyncConnResp{StatusCode: ww.statusCode, Header: ww.header, Body: ww.body.Bytes()},
						}))
					}()
					next.ServeHTTP(ww, r.WithContext(taskCtx))
				}()

				select {
				case <-done:
					for k, v := range ww.Header() {
						w.Header()[k] = v
					}
					w.WriteHeader(ww.statusCode)
					w.Write(ww.body.Bytes())
				case <-time.After(firstRequestTimeout):
					w.WriteHeader(http.StatusAccepted)
					w.Write(lo.Must(json.Marshal(map[string]any{
						"success": true,
						"data": map[string]any{
							"conn_id": connID,
						},
					})))
				}
			}
		})
	}
}

type AsyncConnStorage interface {
	// Get returns the connection detail by connID.
	Get(ctx context.Context, connID string) (*AsyncConn, error)
	// Set sets the connection detail by connID.
	Set(ctx context.Context, connID string, conn *AsyncConn) error
}

type AsyncConn struct {
	ID string
	// The time when the connection is created.
	Resp *AsyncConnResp
	TTL  time.Duration
}

type AsyncConnResp struct {
	StatusCode int
	Header     http.Header
	Body       []byte
}

type BufferedResponseWriter struct {
	header     http.Header
	body       bytes.Buffer
	statusCode int
}

func (w *BufferedResponseWriter) Header() http.Header {
	return w.header
}

func (w *BufferedResponseWriter) Write(bytes []byte) (int, error) {
	return w.body.Write(bytes)
}

func (w *BufferedResponseWriter) WriteHeader(statusCode int) {
	w.statusCode = statusCode
}

var _ http.ResponseWriter = (*BufferedResponseWriter)(nil)

func NewBufferedResponseWriter() *BufferedResponseWriter {
	return &BufferedResponseWriter{
		header:     make(http.Header),
		statusCode: http.StatusOK,
	}
}

func NoCancelCtx(ctx context.Context) context.Context {
	return &noCancelCtx{ctx}
}

type noCancelCtx struct {
	context.Context
}

func (c *noCancelCtx) Deadline() (deadline time.Time, ok bool) {
	return
}

func (c *noCancelCtx) Done() <-chan struct{} {
	return nil
}
