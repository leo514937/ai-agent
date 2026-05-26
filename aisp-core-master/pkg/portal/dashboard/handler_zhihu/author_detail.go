package handler_zhihu

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
)

type AuthorDetailHandler struct {
	rest.BaseHandler
}

// 请求体结构
type AuthorDetailRequest struct {
	MemberIds []int64 `json:"member_ids"`
}

func NewAuthorDetailHandler() rest.Handler {
	return &AuthorDetailHandler{}
}

func (h *AuthorDetailHandler) Post(ctx *rest.Context) (rest.Response, error) {
	// 从请求体中获取参数
	var req AuthorDetailRequest
	if err := ctx.JSONArgs(&req); err != nil {
		return nil, rest.NewMalformRequestException("请求体格式错误", nil, nil)
	}

	if len(req.MemberIds) == 0 {
		return nil, rest.NewMalformRequestException("member_ids 不能为空", nil, nil)
	}

	// 调用 authorDescService 获取作者详情
	authorService := author.DefaultAuthorDescService
	authorDetails := authorService.BatchGetAuthorDetail(ctx, req.MemberIds)

	return ResponseSuccess(authorDetails)
}
