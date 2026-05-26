package handler

import (
	"regexp"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
	"github.com/spf13/cast"
	"golang.org/x/exp/slices"
)

type LoginHandler struct {
	rest.BaseHandler
	userRegulateService rpc.UserRegulateService
}

func NewLoginHandler() rest.Handler {
	return &LoginHandler{
		userRegulateService: impl.DefaultUserRegulateService,
	}
}

var phonePattern = regexp.MustCompile(`^(1)\d{10}.*$`)

func isValidMobile(mobile string) bool {
	if mobile == "" {
		return false
	}

	return phonePattern.MatchString(mobile)
}

func isValidSmsCode(smsCode string) bool {
	return smsCode != "" && len(smsCode) == 6
}

type LoginRequest struct {
	Mobile  string `json:"mobile"`
	SmsCode string `json:"smsCode"`
}

func (k *LoginHandler) Post(ctx *rest.Context) (rest.Response, error) {
	loginRequest := LoginRequest{}
	err := ctx.JSONArgs(&loginRequest)
	if err != nil {
		return nil, err
	}
	if !slices.Contains(constant.PrivilegedUser, loginRequest.Mobile) {
		if !isValidMobile(loginRequest.Mobile) {
			return model.NewResponseByStatus(ctx, model.ResponseStatusMobilePatternError), nil
		}

		if !isValidSmsCode(loginRequest.SmsCode) {
			return model.NewResponseByStatus(ctx, model.ResponseStatusSmsCodePatternError), nil
		}
	}

	if !middleware.CheckIfZhihaituSource(ctx.Request, loginRequest.Mobile) {
		return model.NewResponseByStatus(ctx, model.ResponseStatusAccountUnauthorizedError), nil
	}

	account, err := service.Login(ctx, loginRequest.Mobile, loginRequest.SmsCode)
	if err != nil {
		return nil, err
	}

	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusUserNotExistsError), nil
	} else if account.Status == model.AccountStatusNotAuth {
		return model.NewResponseByStatus(ctx, model.ResponseStatusNotAuthingError), nil
	}

	canLogin, err := k.userRegulateService.CanLogin(ctx, account.MemberID)
	if !canLogin {
		return model.NewResponseByStatus(ctx, model.ResponseStatusNotAuthingError), nil
	}

	token, err := middleware.CreateToken(account.ID, loginRequest.Mobile)
	if err != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusError), nil
	}
	userIdent, err := util.AesEncrypt(cast.ToString(account.ID), util.AesKey)
	if err != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusError), nil
	}

	accountLogin := model.AccountLoginResp{
		CommonResp: model.CommonResp{Success: true},
		Mobile:     loginRequest.Mobile,
		Token:      token,
		UserIdent:  userIdent,
		Name:       account.Name,
		UserId:     account.ID,
	}

	return &model.Response{
		ResponseStatus: model.ResponseStatusSuccess,
		Data:           accountLogin,
	}, nil
}

type IsExistHandler struct {
	rest.BaseHandler
}

func NewIsExistHandler() rest.Handler {
	return &IsExistHandler{}
}

func (k *IsExistHandler) Post(ctx *rest.Context) (rest.Response, error) {
	request := &model.IsExistRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[IsExistHandler Post] JSONArgs failed.")
		return nil, err
	}
	account, err := service.GetAccount(ctx, request.Mobile)
	if err != nil {
		return nil, err
	}

	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusUserNotExistsError), nil
	} else if account.Status == model.AccountStatusNotAuth {
		return model.NewResponseByStatus(ctx, model.ResponseStatusNotAuthingError), nil
	} else {
		return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
	}
}

type LogoutHandler struct {
	rest.BaseHandler
}

func NewLogoutHandler() rest.Handler {
	return &LogoutHandler{}
}

func (k *LogoutHandler) Get(ctx *rest.Context) (rest.Response, error) {
	return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
}

type CheckTokenHandler struct {
	rest.BaseHandler
}

func NewCheckTokenHandler() rest.Handler {
	return &CheckTokenHandler{}
}

func (k *CheckTokenHandler) Get(ctx *rest.Context) (rest.Response, error) {
	token := ctx.QueryArgument("token")
	var checkResult bool
	if token == "" {
		checkResult = false
	} else {
		checkResult = middleware.CheckToken(token)
	}
	return model.NewSuccessResponseByData(ctx, checkResult), nil
}
