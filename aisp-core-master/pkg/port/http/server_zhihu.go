package http

import (
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rest"
)

type ZhihuServer struct {
	handler http.Handler
	port    int
}

func (s *ZhihuServer) Run() error {
	app := cafe.NewApplication(
		cafe.WithProfiler(6060),
	)
	app.AddBundle(rest.New(
		rest.WithRouter(s.handler),
		rest.Port(s.port),
		rest.Timeout(5*time.Minute),
		rest.WriteTimeout(5*time.Minute),
	))
	app.Run()
	return nil
}

func (s *ZhihuServer) SetHandler(handler http.Handler) {
	s.handler = handler
}

var _ Server = (*ZhihuServer)(nil)

func init() {
	NewServer = func(name string, port int) Server {
		return &ZhihuServer{
			port: port,
		}
	}
}
