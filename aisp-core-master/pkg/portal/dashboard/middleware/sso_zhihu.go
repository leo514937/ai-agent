package middleware

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/dgrijalva/jwt-go"
	"github.com/imroc/req"
)

const (
	waterMarkKey          = "w_m0"
	authingKeyProviderURI = "https://staff.zhihu.com/oidc"
	authingCookieKey      = "content-brain-authing"
	AuthingCtxKey         = "cafe-authing"
)

func Authing(appID, secretKey, callbackPath string) func(http.Handler) http.Handler {
	ctx := context.TODO()
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "portal.dashboard.middleware.Authing",
	})

	getUserByToken := func(token, callbackURL string) (*middleware.AuthingUser, string, error) {
		param := req.Param{
			"code":          token,
			"client_id":     appID,
			"client_secret": secretKey,
			"grant_type":    "authorization_code",
			"redirect_uri":  callbackURL,
			"scope":         "openid username email",
		}
		header := req.Header{
			"User-Agent":   "Mozilla/5.0 (compatible; ABrowse 0.4; Syllable)",
			"Content-Type": "application/x-www-form-urlencoded",
		}
		resp, err := req.Post(authingKeyProviderURI+"/token", param, header)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "request oidc/token failed")
			return nil, "", fmt.Errorf("request oidc/token error: %w", err)
		}

		var respJSON map[string]interface{}
		err = resp.ToJSON(&respJSON)
		if err != nil {
			logger.WithFields(ctx, map[string]interface{}{
				"token": token,
				"resp":  respJSON,
			}).WithError(ctx, err).Error(ctx, "bad oidc/token")
			return nil, "", fmt.Errorf("bad oidc/token %+v request: %+v response: %w", token, param, err)
		}

		if respJSON["access_token"] == nil {
			logger.WithFields(ctx, map[string]interface{}{
				"token": token,
				"resp":  respJSON,
			}).WithError(ctx, err).Error(ctx, "bad oidc/token")
			return nil, "", fmt.Errorf("bad oidc/token %+v request: %+v response: %+v", token, param, respJSON)
		}
		var atoken string
		var ok bool
		if atoken, ok = respJSON["access_token"].(string); !ok {
			logger.WithField(ctx, "token", token).WithError(ctx, err).Error(ctx, "bad sso user response")
			return nil, "", fmt.Errorf("bad sso user response: %w", err)
		}
		infoURL := authingKeyProviderURI + "/me"
		header = req.Header{
			"User-Agent":    "Mozilla/5.0 (compatible; ABrowse 0.4; Syllable)",
			"Content-Type":  "application/x-www-form-urlencoded",
			"Authorization": "Bearer " + atoken,
		}
		resp, err = req.Get(infoURL, param, header)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "request oidc/me error")
			return nil, "", fmt.Errorf("request oidc/me error: %w", err)
		}
		var respMap map[string]interface{}
		_ = resp.ToJSON(&respMap)
		var user middleware.AuthingUser
		err = resp.ToJSON(&user)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "bad sso user response")
			return nil, "", fmt.Errorf("bad sso user response: %w", err)
		}
		user.UpdatedAt = time.Now()
		return &user, atoken, nil
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// 获取当前的真实 Host，兼容本地开发（当前只能通过 Referer 来判断是否是本地开发的 Host）
			var realHost, realScheme string
			refererURL, urlErr := url.Parse(r.Referer())
			if urlErr != nil {
				realHost = r.Host
				realScheme = "https"
			} else if strings.HasPrefix(refererURL.Host, "localhost") || strings.HasPrefix(refererURL.Host, "127.0.0.1") {
				realHost = refererURL.Host
				realScheme = "http"
			} else {
				realHost = r.Host
				realScheme = "https"
			}
			callbackURL := fmt.Sprintf("%s://%s%s", realScheme, realHost, callbackPath)
			if r.URL.Path == callbackPath {
				code := r.URL.Query().Get("code")
				user, aToken, err := getUserByToken(code, callbackURL)
				if user == nil {
					w.WriteHeader(http.StatusBadRequest)
					_, _ = w.Write([]byte("bad sso user response: " + err.Error()))

					return
				}
				jwtToken := jwt.NewWithClaims(jwt.SigningMethodHS256, user)
				cookieValue, _ := jwtToken.SignedString([]byte(secretKey))
				http.SetCookie(w, &http.Cookie{
					Name:    authingCookieKey,
					Value:   cookieValue,
					Path:    "/",
					Domain:  ".in.zhihu.com",
					Expires: time.Now().AddDate(0, 0, 5),
				})
				http.SetCookie(w, &http.Cookie{
					Name:    waterMarkKey,
					Value:   aToken,
					Path:    "/",
					Expires: time.Now().AddDate(0, 0, 5),
				})
				http.Redirect(w, r, r.URL.Query().Get("state"), http.StatusFound)

				return
			}

			userCookie, err := r.Cookie(authingCookieKey)
			if err != nil {
				args := url.Values{}
				args.Add("response_type", "code")
				args.Add("client_id", appID)
				args.Add("redirect_uri", callbackURL)
				args.Add("scope", "openid username email picture")
				args.Add("state", r.URL.String())
				authURL := authingKeyProviderURI + "/auth?" + args.Encode()
				http.Redirect(w, r, authURL, http.StatusFound)

				return
			}

			user := &middleware.AuthingUser{}
			if jwtToken, err := jwt.ParseWithClaims(userCookie.Value, user, func(token *jwt.Token) (interface{}, error) {
				return []byte(secretKey), nil
			}); err != nil || !jwtToken.Valid {
				logger.WithError(ctx, err).Error(ctx, "bad sso user response")
				w.WriteHeader(http.StatusUnauthorized)
				return
			}

			nctx := context.WithValue(r.Context(), AuthingCtxKey, user) // nolint:golint,revive,staticcheck
			next.ServeHTTP(w, r.WithContext(nctx))
		})
	}
}

func GetUserId(ctx *rest.Context) string {
	var user, ok = ctx.Value(AuthingCtxKey).(*middleware.AuthingUser)
	if ok {
		return user.Username
	} else {
		log.Error(ctx, "getUserId error")
		return ""
	}
}
