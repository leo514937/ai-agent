package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// go run pkg/tools/rpc/metis2/main.go
func main() {
	ctx := context.Background()
	questionIdStr := flag.String("questionId", "108044803,19673677,17672503,107462722,107907659,41094063", "input question id")
	flag.Parse()

	questionIds := util.StringSliceToInt64(strings.Split(*questionIdStr, ","))

	response1 := impl.DefaultMetis2RPCImpl.GetQuestionAnswerIds(ctx, questionIds[0], 1)
	response2 := impl.DefaultMetis2RPCImpl.ConcurrentGetQuestionAnswerIds(ctx, questionIds, 1, 3)

	fmt.Println(fmt.Sprintf("metis2 question2answer \n result1:%s \n result2:%s", util.GetJSONIgnoreError(response1), util.GetJSONIgnoreError(response2)))
}
