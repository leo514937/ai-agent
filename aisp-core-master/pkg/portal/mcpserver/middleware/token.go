package middleware

import (
	"context"
	"net/http"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

// accessTokenContextKey 是用于在context中存储API密钥的键
type accessTokenContextKey struct{}

// AccessTokenFromRequest 中间件从请求的查询参数中提取Access-Token并将其存储在context中
func AccessTokenFromRequest(ctx context.Context, r *http.Request) context.Context {
	log.Infof(ctx, "RequestURI: %s", r.RequestURI)
	log.Infof(ctx, "Header: %+v", r.Header)

	bearerToken := ""
	bearer := r.Header.Get("Authorization")
	if strings.HasPrefix(bearer, "Bearer ") {
		bearerToken = strings.TrimPrefix(bearer, "Bearer ")
	}

	if bearerToken == "" {
		bearerToken = r.Header.Get("Access-Token")
		if bearerToken != "" {
			bearerToken = "Access-Token--" + strings.TrimSpace(bearerToken)
		}
	}

	// 将Access-Token存储在请求的context中
	ctx = context.WithValue(ctx, accessTokenContextKey{}, bearerToken)

	log.Infof(ctx, "bearerToken: %s", bearerToken)

	ctx = context.WithoutCancel(ctx)

	return ctx
}

// GetAccessTokenromContext 从context中获取API密钥
func GetAccessTokenFromContext(ctx context.Context) string {
	accessToken, _ := ctx.Value(accessTokenContextKey{}).(string)
	return accessToken
}
