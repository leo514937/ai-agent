package handler_zhihu

import (
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/baidubce/bce-sdk-go/services/sts"
)

type S3AccessHandler struct {
	rest.BaseHandler
}

// 请求体结构
type S3AccessConfig struct {
	AK       string `json:"ak"`
	SK       string `json:"sk"`
	Endpoint string `json:"endpoint"`
}

type S3SessionTokenResult struct {
	AccessKeyId     string `json:"AccessKeyId"`
	SecretAccessKey string `json:"SecretAccessKey"`
	SessionToken    string `json:"SessionToken"`
	CreateTime      string `json:"CreateTime"`
	Expiration      string `json:"Expiration"`
}

func NewS3AccessHandler() rest.Handler {
	return &S3AccessHandler{}
}

func (h *S3AccessHandler) Get(ctx *rest.Context) (rest.Response, error) {
	conf := &S3AccessConfig{}
	confString := config.GetString("baidu_s3_ak_sk", "{}")
	err := util.JSONUnmarshal([]byte(confString), conf)
	if err != nil || conf.AK == "" || conf.SK == "" || conf.Endpoint == "" {
		return nil, rest.NewMalformRequestException("配置获取失败", nil, nil)
	}

	// 初始化一个BosClient
	stsClient, err := sts.NewClient(conf.AK, conf.SK)
	if err != nil {
		return nil, rest.NewMalformRequestException("生成AccessToken失败", nil, nil)
	}

	// 获取临时认证token，有效期为60秒，ACL为空
	baiduS3SessionTokenResult, err := stsClient.GetSessionToken(60, "")
	if err != nil || baiduS3SessionTokenResult == nil {
		return nil, rest.NewMalformRequestException("生成AccessToken失败", nil, nil)
	}
	return ResponseSuccess(&S3SessionTokenResult{
		AccessKeyId:     baiduS3SessionTokenResult.AccessKeyId,
		SecretAccessKey: baiduS3SessionTokenResult.SecretAccessKey,
		SessionToken:    baiduS3SessionTokenResult.SessionToken,
		CreateTime:      baiduS3SessionTokenResult.CreateTime,
		Expiration:      baiduS3SessionTokenResult.Expiration,
	})
}
