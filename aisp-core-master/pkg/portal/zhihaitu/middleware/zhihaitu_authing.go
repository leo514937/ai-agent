package middleware

import (
	"context"
	"errors"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/dgrijalva/jwt-go"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"golang.org/x/exp/slices"
)

const tokenSignConfigKey = "zhihaitu.tokenSign"
const zhtHeader = "ZHT"
const tokenExpiration = 19 * 24 * 60 * 60 * 1000

var tokenSignKey = config.GetString(tokenSignConfigKey, "")

type UserClaims struct {
	jwt.StandardClaims
	AccountId int64
	UserName  string
}

func (u UserClaims) Valid() error {
	return nil
}

func CheckIfZhihaituSource(r *http.Request, mobile string) bool {
	sourceDomain := r.Header.Get("Source-Domain")
	if sourceDomain == zhtHeader {
		if !slices.Contains(constant.WxbUser, mobile) {
			return false
		}
	}

	return true
}

var authingWhiteList = []string{
	"/api/account/v1/login",
	"/api/account/v1/isExist",
	"/api/chat/v1/simChat",
	"/api/chat/v1/simChat2",
}

func Authing() func(http.Handler) http.Handler {

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if slices.Contains(authingWhiteList, r.RequestURI) {
				next.ServeHTTP(w, r.WithContext(r.Context()))
				return
			}

			token := r.Header.Get("token")
			account, err := getAccount(r.Context(), token)
			if err != nil {
				log.Error(r.Context(), err)
				w.WriteHeader(http.StatusUnauthorized)
				return
			}

			sourceDomain := r.Header.Get("Source-Domain")
			if sourceDomain == zhtHeader {
				if !CheckIfZhihaituSource(r, account.Mobile) {
					w.WriteHeader(http.StatusUnauthorized)
					return
				}
			}
			nctx := context.WithValue(r.Context(), constant.ZhihaituMemberIdKey, account) // nolint:golint,revive,staticcheck
			nctx = context.WithValue(nctx, constant.TraceId, generateTraceId())
			next.ServeHTTP(w, r.WithContext(nctx))
		})
	}
}

func generateTraceId() string {
	return uuid.New().String()
}

func CreateToken(accountId int64, userName string) (string, error) {
	var user = UserClaims{
		jwt.StandardClaims{Subject: "SRB-USER", ExpiresAt: time.Now().UnixMilli() + tokenExpiration},
		accountId,
		userName}
	jwtToken := jwt.NewWithClaims(jwt.SigningMethodHS512, &user)
	return jwtToken.SignedString([]byte(tokenSignKey))
}

func CheckToken(token string) bool {
	var user UserClaims
	_, err := jwt.ParseWithClaims(token, &user, func(token *jwt.Token) (interface{}, error) {
		return []byte(tokenSignKey), nil
	})

	if err != nil {
		return false
	} else {
		return true
	}
}

func GetUserFromContext(ctx context.Context) *model.TableOpenapiAccount {
	account, ok := ctx.Value(constant.ZhihaituMemberIdKey).(*model.TableOpenapiAccount) // nolint:golint,revive,staticcheck
	if ok {
		return account
	} else {
		return nil
	}
}

func getAccount(ctx context.Context, token string) (*model.TableOpenapiAccount, error) {
	if token == "" {
		return nil, errors.New("没有token")
	}

	var user UserClaims
	parsedToken, err := jwt.ParseWithClaims(token, &user, func(token *jwt.Token) (interface{}, error) {
		return []byte(tokenSignKey), nil
	})

	log.Info(ctx, "parsed token=", lo.Must(utils.MarshalToString(parsedToken)))
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "parse token error. token=%s", token)
		return nil, err
	}
	account, err := dao.DefaultOpenapiAccountDAO.GetByStatus(ctx, user.AccountId, model.NotDeleted, model.AccountStatusAuth)
	if err != nil {
		return nil, err
	}

	if account == nil {
		log.Errorf(ctx, "account is nil. accountId=%s", user.AccountId)
		return nil, nil
	}

	mobile, err := impl.DefaultCryptRpc.Decrypt(ctx, account.EncryptMobile)
	if err != nil {
		return nil, nil
	}
	account.Mobile = mobile

	return account, nil
}
