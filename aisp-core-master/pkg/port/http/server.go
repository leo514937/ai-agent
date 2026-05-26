package http

type Server interface {
	Run() error
}

var (
	NewServer func(name string, port int) Server
)
