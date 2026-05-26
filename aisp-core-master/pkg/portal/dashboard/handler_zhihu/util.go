package handler_zhihu

import (
	"bytes"
	"context"
	"encoding/json"
	"io"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
)

func ResponseSuccess(data any) (rest.Response, error) {
	response := BaseResponse{
		Success: true,
		Msg:     "操作成功",
		Data:    data,
	}
	return response, nil
}

func ResponsePagingSuccess(data any, pageToken string, total int64) (rest.Response, error) {
	response := BaseResponse{
		Success: true,
		Msg:     "操作成功",
		Data:    data,
		Paging: &Paging{
			PageToken: pageToken,
			Total:     total,
		},
	}
	return response, nil
}

type BaseResponse struct {
	Success bool        `json:"success"`
	Msg     string      `json:"msg"`
	Data    interface{} `json:"data"`
	Paging  *Paging     `json:"paging,omitempty"`
}

type Paging struct {
	PageToken string `json:"page_token"`
	Total     int64  `json:"total,omitempty"`
}

type BufferedReadCloser struct {
	readCloser io.ReadCloser
	buffer     *bytes.Buffer
}

var _ io.ReadCloser = (*BufferedReadCloser)(nil)

func (r *BufferedReadCloser) Read(p []byte) (n int, err error) {
	n, err = r.readCloser.Read(p)
	r.buffer.Write(p[:n])
	return
}

func (r *BufferedReadCloser) Close() error {
	return r.readCloser.Close()
}

func (r *BufferedReadCloser) Bytes() []byte {
	return r.buffer.Bytes()
}

func (r *BufferedReadCloser) String() string {
	return r.buffer.String()
}

func NewBufferedReadCloser(readCloser io.ReadCloser) *BufferedReadCloser {
	return &BufferedReadCloser{
		readCloser: readCloser,
		buffer:     bytes.NewBuffer(nil),
	}
}

func GetSkuDisplayNameByName(ctx context.Context, name string) string {
	skus, err := dao.DefaultModelDAO.ListSkus(ctx)
	if err != nil {
		return ""
	}
	for _, sku := range skus {
		if sku.Name == name {
			if len(sku.Model.Skus) == 1 {
				return sku.Model.DisplayName
			}
			return sku.Model.DisplayName + "_" + sku.DisplayName
		}
	}
	return name
}

type emptyResult struct{}

var EmptyResult = emptyResult{}

func (e emptyResult) MarshalJSON() ([]byte, error) {
	return []byte(`""`), nil
}

var _ json.Marshaler = (*emptyResult)(nil)
