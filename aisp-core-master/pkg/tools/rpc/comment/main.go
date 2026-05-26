package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
)

func main() {
	commentId := flag.Int64("id", 10157827371, "comment ID")
	depth := flag.Int("depth", 1, "Depth:  0;1;-1;...")
	flag.Parse()

	ctx := context.TODO()
	service := impl.NewCommentService()
	common, isOk := service.GetComment(ctx, *commentId, *depth)
	printComment("print ", common, isOk)
}

func printComment(name string, res *rpc.CommentResultWrapper, isOk bool) {
	if !isOk {
		fmt.Printf("%s res:%+v, isok:%v\n\n", name, res, isOk)
		return
	}
	marshal, _ := json.Marshal(res)
	fmt.Printf("%s OKK res:%+v, isok:%v\n\n", name, string(marshal), isOk)
}
