package model

import (
	"net/http"
	"time"
)

type AsyncHTTPConn struct {
	ID   string
	Resp *AsyncConnResp
	TTL  time.Duration
}

type AsyncConnResp struct {
	StatusCode int
	Header     http.Header
	Body       []byte
}
