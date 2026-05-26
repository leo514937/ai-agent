package handler_zhihu

import (
	"encoding/json"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
)

type CurrentUserHandler struct {
	rest.BaseHandler

	configClient config.Client
}

func NewCurrentUserHandler() rest.Handler {
	return &CurrentUserHandler{
		configClient: config.GetClient(),
	}
}

const avatarURLTemplate = "https://ui-avatars.com/api/?name=%s&size=128&background=fff&color=007bff&rounded=true&bold=true&font-size=0.5"

func getAvatarURL(email string) string {
	return fmt.Sprintf(avatarURLTemplate, email[:2])
}

func getNameFromEmailAddr(email string) string {
	return email[:strings.Index(email, "@")]
}

func (h *CurrentUserHandler) Get(ctx *rest.Context) (rest.Response, error) {
	user := middleware.AuthingUserFromContext(ctx)

	if user == nil {
		return nil, rest.NewMalformRequestException("用户未登录", nil, nil)
	}

	var permissionsRawMap map[string][]string
	permissionsMapStr := h.configClient.GetString("permissions")
	if err := json.Unmarshal([]byte(permissionsMapStr), &permissionsRawMap); err != nil {
		return nil, rest.NewMalformRequestException("解析权限配置失败", nil, nil)
	}

	permissionsMap := util.NewDefaultMap[string, []string](func() []string {
		return []string{}
	}).FromMap(permissionsRawMap)

	return ResponseSuccess(map[string]any{
		"user": &UserDTO{
			Email:       user.Email,
			Name:        getNameFromEmailAddr(user.Email),
			Avatar:      getAvatarURL(user.Email),
			ThumbAvatar: getAvatarURL(user.Email),
		},
		"permissions": permissionsMap.Get(user.Email),
	})
}

type UserDTO struct {
	Email       string `json:"email"`
	Name        string `json:"name"`
	Avatar      string `json:"avatar"`
	ThumbAvatar string `json:"thumb_avatar"`
}
