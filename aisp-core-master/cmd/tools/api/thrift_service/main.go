package main

import (
	"flag"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/thrift_service/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	txn, ctx := log.StartTransaction("tools_api_thrift_service")
	defer txn.End(ctx)

	var (
		questions string
	)

	flag.StringVar(&questions, "questions", "你吃饭了吗？", "词短语集合 逗号分割")
	flag.Parse()

	clientImpl := request.NewQuestionPhraseThriftClientImpl()
	clientImpl.DoSaveQuestionPhrase(ctx, strings.Split(questions, ","))
}
