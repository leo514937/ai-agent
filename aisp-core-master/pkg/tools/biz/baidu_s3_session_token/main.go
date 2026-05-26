package main

import (
	"fmt"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/handler_zhihu"
	"github.com/baidubce/bce-sdk-go/services/sts"
)

func main() {
	conf := &handler_zhihu.S3AccessConfig{}
	confString := config.GetString("baidu_s3_ak_sk", "{}")
	err := util.JSONUnmarshal([]byte(confString), conf)
	if err != nil || conf.AK == "" || conf.SK == "" || conf.Endpoint == "" {
		fmt.Println("配置获取失败")
	}

	// 初始化一个BosClient
	stsClient, err := sts.NewClient(conf.AK, conf.SK)
	if err != nil || stsClient == nil {
		fmt.Println("生成AccessToken失败")
	}

	// 获取临时认证token，有效期为60秒，ACL为空
	baiduS3SessionTokenResult, err := stsClient.GetSessionToken(60, "")
	if err != nil || baiduS3SessionTokenResult == nil {
		fmt.Println("生成AccessToken失败-2")
	}

	fmt.Println("输出结果 => ", util.GetJSONIgnoreError(baiduS3SessionTokenResult))
}
