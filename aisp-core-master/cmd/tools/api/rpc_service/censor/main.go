package main

import (
	"context"
	"flag"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/rpc_service/censor/request"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	txn, ctx := log.StartTransaction("tools_api_rpc_service_censor")
	defer txn.End(ctx)

	rpcTest()
}
func rpcTest() {
	ctx := context.Background()
	log.Infof(ctx, "准备处理")

	var (
		wordId     string
		objectType string
	)

	flag.StringVar(&wordId, "word_id", "51", "词Id")
	flag.StringVar(&objectType, "object_type", "ai_tab_interest_expansion_word", "审核词类型")
	flag.Parse()

	rumClient32 := impl.NewRumClientImpl[float32](conf.GetRumConfig(), conf.GetRumConfig().TimeoutDefault)
	rumTable := objectType2RumTable(objectType)

	if rumTable != "" {
		resp := rumClient32.RumGet(ctx, rumTable, []string{wordId}, []string{"id"})
		fmt.Println(fmt.Sprintf("before rum result:%v", util.GetJSONIgnoreError(resp)))
	}

	// 发起审核结果调用
	request.DefCensorThriftRpcClient.DoSetCensorResult(ctx, objectType, wordId)

	// 查询审核结果
	request.DefCensorThriftRpcClient.DoGetCensorInfo(ctx, objectType, wordId)

	if rumTable != "" {
		// 循环检测 20 次是否删除成功
		for i := 0; i < 20; i++ {
			resp := rumClient32.RumGet(ctx, rumTable, []string{wordId}, []string{"id"})
			fmt.Println(fmt.Sprintf("monitor %d times: after rum result:%v", i, util.GetJSONIgnoreError(resp)))
			if len(resp) > 0 {
				time.Sleep(10 * time.Second)
			} else {
				break
			}
		}

	}
}

func objectType2RumTable(objectType string) string {
	workTypeRef := macro.CensorTypeAndWordTypeRef[strings.ToLower(objectType)]

	switch proto.QueryType(workTypeRef) {
	case proto.QueryType_PREFAB_WORD_QUESTION,
		proto.QueryType_PREFAB_WORD_HOT_QUESTION,
		proto.QueryType_RELATE_WORD_HOT_EVENT:
		return macro.AiPrefabWordV3RumTable
	default:
		return ""
	}
}
