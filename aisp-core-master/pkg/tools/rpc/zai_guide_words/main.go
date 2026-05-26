package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/user_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func main() {
	grpcImpl := impl.NewZaiRecallGuideWordGRPCImpl()
	words := grpcImpl.RecallGuideWords(context.Background(), &user_grpc.UserGuideWordsRequest{
		MemberId: 246248568,
		Limit:    50,
	})
	fmt.Printf("输出引导词：%v\n", util.GetJSONIgnoreError(words))
}
