package util

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/ioutil"
	"net"
	"net/http"
	netURL "net/url"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type HttpClient struct {
	httpClient *http.Client
	url        string
	method     string
}

func NewHttpClient(method string, url string, timeout time.Duration) *HttpClient {
	return &HttpClient{
		method: method,
		url:    url,
		httpClient: &http.Client{
			Timeout: timeout,
			Transport: telemetry.WrapRoundTripper(
				&http.Transport{
					// copy from go/src/net/http/transport.go
					Proxy: http.ProxyFromEnvironment,
					DialContext: (&net.Dialer{
						Timeout:   30 * time.Second,
						KeepAlive: 30 * time.Second,
					}).DialContext,
					ForceAttemptHTTP2:     true,
					MaxIdleConns:          100,
					IdleConnTimeout:       90 * time.Second,
					TLSHandshakeTimeout:   10 * time.Second,
					ExpectContinueTimeout: 1 * time.Second,
					// self-config
					MaxIdleConnsPerHost: 1000,
				}),
		},
	}
}

func NewHttpClientWithProxy(method string, url string, timeout time.Duration) *HttpClient {
	proxyURL, err := netURL.Parse("http://gfw.in.zhihu.com:18080")
	if err != nil {
		log.Errorf(context.Background(), "parse proxy url error: %v", err)
		return NewHttpClient(method, url, timeout)
	}

	return &HttpClient{
		method: method,
		url:    url,
		httpClient: &http.Client{
			Timeout: timeout,
			Transport: telemetry.WrapRoundTripper(
				&http.Transport{
					// copy from go/src/net/http/transport.go
					Proxy: http.ProxyURL(proxyURL),
					DialContext: (&net.Dialer{
						Timeout:   30 * time.Second,
						KeepAlive: 30 * time.Second,
					}).DialContext,
					ForceAttemptHTTP2:     true,
					MaxIdleConns:          100,
					IdleConnTimeout:       90 * time.Second,
					TLSHandshakeTimeout:   10 * time.Second,
					ExpectContinueTimeout: 1 * time.Second,
					// self-config
					MaxIdleConnsPerHost: 1000,
				}),
		},
	}
}

func (c *HttpClient) GetHttpClient() *http.Client {
	return c.httpClient
}

func (c *HttpClient) DoGet(ctx context.Context, url string, header map[string]string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, url, http.NoBody)
	if err != nil {
		log.Warnf(ctx, "error.request_error")
		return nil, err
	}
	for k, v := range header {
		req.Header.Add(k, v)
	}
	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		log.Warnf(ctx, "DoGet request err: %+v", err)
		return nil, err
	}
	if resp == nil {
		return nil, errors.New("response  is nil")
	}

	if resp.Body != nil {
		defer func() {
			err = resp.Body.Close()
			if err != nil {
				log.Warnf(ctx, "DoGet response body close err: %+v", err)
			}
		}()
	}

	if resp.StatusCode != http.StatusOK {
		data, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("response status code is not OK, response code is %d, body:%s", resp.StatusCode, string(data))
	}

	// 返回数据处理
	bodyData, err := io.ReadAll(resp.Body)

	if err != nil {
		return nil, err
	}

	return bodyData, err
}

func (c *HttpClient) Do(ctx context.Context, header, query map[string]string, body interface{}, resp interface{}) error {
	var bodyB []byte
	var err error

	start := time.Now()
	if body != nil {
		bodyB, err = json.Marshal(body)
		if err != nil {
			log.Errorf(ctx, "build request error, method: %s, url:%s, body:%s", c.method, c.url, string(bodyB))
			return err
		}
	}

	var bodyReader io.Reader
	if len(bodyB) > 0 {
		bodyReader = bytes.NewReader(bodyB)
	}

	req, err := http.NewRequestWithContext(ctx, c.method, c.url, bodyReader)
	if err != nil {
		log.Errorf(ctx, "build request error, method: %s, url:%s, body:%s", c.method, c.url, string(bodyB))
		return err
	}

	param := req.URL.Query()
	for k, v := range query {
		param.Add(k, v)
	}
	req.URL.RawQuery = param.Encode()

	for k, v := range header {
		req.Header.Add(k, v)
	}

	raw, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}

	if err != nil {
		log.Errorf(ctx, "http client do error, method: %s, url:%s, body:%s, header:%v, query:%v", c.method, c.url, string(bodyB), header, query)
		return err
	}

	defer raw.Body.Close()

	rawBody, err := ioutil.ReadAll(raw.Body)
	if err != nil {
		return err
	}

	if raw.StatusCode != 200 {
		log.Warnf(ctx, "http client stats code error, %d: method: %s, url:%s, body:%s, header:%v, query:%v", raw.StatusCode, c.method, c.url, string(bodyB), header, query)
		return errors.New("error http client status code")
	}

	log.Infof(ctx, "http client info, %d: method: %s, url:%s, body:%s, header:%v, query:%v, cost:%s, response header:%v, response:%s",
		raw.StatusCode, c.method, c.url, string(bodyB), header, query, time.Since(start).String(), raw.Header, string(rawBody))

	err = json.Unmarshal(rawBody, resp)
	if err != nil {
		return err
	}
	return nil
}

// DoSse 支持服务器向浏览器推送信息。参考：https://www.ruanyifeng.com/blog/2017/05/server-sent_events.html
func (c *HttpClient) DoSse(ctx context.Context, header, query map[string]string, body interface{}) ([]string, error) {
	var bodyB []byte
	var err error

	if body != nil {
		bodyB, err = json.Marshal(body)
		if err != nil {
			log.Errorf(ctx, "build request error, method: %s, url:%s, body:%s", c.method, c.url, string(bodyB))
			return nil, err
		}
	}

	var bodyReader io.Reader
	if len(bodyB) > 0 {
		bodyReader = bytes.NewReader(bodyB)
	}

	req, err := http.NewRequestWithContext(ctx, c.method, c.url, bodyReader)
	if err != nil {
		log.Errorf(ctx, "build request error, method: %s, url:%s, body:%s", c.method, c.url, string(bodyB))
		return nil, err
	}

	param := req.URL.Query()
	for k, v := range query {
		param.Add(k, v)
	}
	req.URL.RawQuery = param.Encode()

	for k, v := range header {
		req.Header.Add(k, v)
	}

	raw, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}

	if err != nil {
		log.Errorf(ctx, "http client do error, method: %s, url:%s, body:%s, header:%v, query:%v", c.method, c.url, string(bodyB), header, query)
		return nil, err
	}

	defer raw.Body.Close()

	rawBody, err := ioutil.ReadAll(raw.Body)
	if err != nil {
		return nil, err
	}

	if raw.StatusCode != 200 {
		log.Warnf(ctx, "http client stats code error, %d: method: %s, url:%s, body:%s, header:%v, query:%v", raw.StatusCode, c.method, c.url, string(bodyB), header, query)
		return nil, errors.New("error http client status code")
	}

	log.Infof(ctx, "http client info, %d: method: %s, url:%s, body:%s, header:%v, query:%v, response header:%v, response:%s", raw.StatusCode, c.method, c.url, string(bodyB), header, query, raw.Header, string(rawBody))

	// 解析sse协议的结果
	lines := strings.Split(string(rawBody), "\n")
	realLines := make([]string, 0, len(lines))
	for _, line := range lines {
		if strings.HasPrefix(line, "data: ") {
			line = strings.TrimPrefix(line, "data: ")
			realLines = append(realLines, line)
		}
	}
	return realLines, nil
}
