package request

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-censor/censor_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type CensorThriftRpcClient struct {
	client *censor_thrift.CensorServiceClient
}

var DefCensorThriftRpcClient *CensorThriftRpcClient

func NewClient() *CensorThriftRpcClient {
	return &CensorThriftRpcClient{
		client: censor_thrift.NewCensorServiceClient(tzone.NewClient(
			"CensorService",
			tzone.HostPort("localhost", "9999"),
			//tzone.TargetName("aisp-thrift-rpc"),
			tzone.Timeout(2*time.Second))),
	}
}

// DoGetCensorInfo 反查举报结果接口
func (r *CensorThriftRpcClient) DoGetCensorInfo(ctx context.Context, objectType string, wordId string) {
	param := censor_thrift.GetCensorInfoParam{
		ObjectType: objectType,
		ObjectID:   wordId,
	}
	info, err := r.client.GetCensorInfo(ctx, &param)
	if err != nil {
		fmt.Println("Error DoGetCensorInfo => ", err)
		return
	}
	fmt.Println("输出 DoGetCensorInfoResponse信息 => ", util.GetJSONIgnoreError(info))
}

// DoSetCensorResult 发起审核结果回调接口
func (r *CensorThriftRpcClient) DoSetCensorResult(ctx context.Context, objectType string, wordId string) {
	param := censor_thrift.SetCensorResultParam{
		ObjectType: objectType,
		ObjectID:   wordId,
		Operations: []*censor_thrift.Operation{
			{
				Name: strings.ToLower(macro.CensorOperationRemove),
			},
		},
	}
	info, err := r.client.SetCensorResult_(ctx, &param)
	if err != nil {
		fmt.Println("Error DoSetCensorResult => ", err)
		return
	}
	fmt.Println("输出 DoSetCensorResultResponse信息 => ", util.GetJSONIgnoreError(info))
}

func init() {
	DefCensorThriftRpcClient = NewClient()
}
