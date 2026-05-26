package constant

import (
	"context"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/philchia/agollo/v4"
)

const configKeyZhihaituWxbUser = "zhihaitu.wxb_users"
const configKeyZhihaituPrivilegedUser = "zhihaitu.privileged_users"
const configKeyZhihaituWxbEmexptUser = "zhihaitu.wxb_exempt_security_review_users"

func parseJsonToArray(ctx context.Context, userStr string, users *[]string) {
	err := utils.JSONUnmarshal([]byte(userStr), &users)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "parse config error. content=%s", userStr)
	}
}

func init() {
	ctx := context.Background()
	configClient := config.GetClient()

	parseJsonToArray(ctx, configClient.GetString(configKeyZhihaituWxbUser), &WxbUser)
	parseJsonToArray(ctx, configClient.GetString(configKeyZhihaituPrivilegedUser), &PrivilegedUser)
	parseJsonToArray(ctx, configClient.GetString(configKeyZhihaituWxbEmexptUser), &WxbExemptSecurityReviewUser)

	configClient.OnUpdate(func(event *agollo.ChangeEvent) {
		for key, change := range event.Changes {
			if key == configKeyZhihaituPrivilegedUser {
				parseJsonToArray(ctx, change.NewValue, &PrivilegedUser)
			} else if key == configKeyZhihaituWxbUser {
				parseJsonToArray(ctx, change.NewValue, &WxbUser)
			} else if key == configKeyZhihaituWxbEmexptUser {
				parseJsonToArray(ctx, change.NewValue, &WxbExemptSecurityReviewUser)
			}
		}
	})
}

var WxbUser = []string{}

var PrivilegedUser = []string{}

// WxbExemptSecurityReviewUser 网信办的豁免安全审核的账号
var WxbExemptSecurityReviewUser = []string{}
