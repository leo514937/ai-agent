package rpc_censor

import (
	"fmt"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rpc"
	"git.in.zhihu.com/one-rpc-go/thrift-censor/censor_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/offline"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/censor/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/thrift_ai_tab"
)

func Main() {
	// service
	censorSvc := service.NewCensorServiceRpcImpl()
	chatService := service.DefaultChatService
	offlineQuestionWordService := thrift_ai_tab.NewOfflineQuestionWordServiceImpl()

	// services
	servicesMap := map[string]thrift.TProcessor{
		"ChatService":    content.NewChatServiceProcessor(chatService),
		"OfflineService": offline.NewOfflineServiceProcessor(offlineQuestionWordService),
		"CensorService":  censor_thrift.NewCensorServiceProcessor(censorSvc),
	}
	bundle := rpc.NewTZoneBundle(
		"aisp-core-thrift-service",
		rpc.WithTZoneServiceMap(servicesMap),
		rpc.TZoneListen(fmt.Sprintf("0.0.0.0:%d", 9999)),
	)
	app := cafe.NewApplication(cafe.SentryIncludePaths("git.in.zhihu.com/zhihu/aisp-core"))
	app.AddBundle(bundle)
	app.Run()
}
