package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/pb-go/feature-schema-proto/serving"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

func main() {

	ctx := context.Background()
	rpcImpl := impl.NewZFeatureGRPCImpl()

	docId := model.Content{ContentType: content.DocType_Member, ContentID: 246302179}
	docIds := []model.Content{docId}

	lastN := rpcImpl.BatchGetLastBehaviors(ctx,
		"preset-words-user", &serving.RequestUser{}, docIds)
	fmt.Printf("输出 BatchGetLastBehaviors 结果: %v\n\n", util.GetJSONIgnoreError(lastN[docId]))

}
