package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/samber/lo"
)

// go run pkg/tools/rpc/member_statistic/main.go
func main() {
	ctx := context.Background()
	memberIdStr := flag.String("mids", "655", "member id")
	flag.Parse()

	memberIds := lo.Map(strings.Split(*memberIdStr, ","), func(s string, idx int) int64 {
		return util.SafeString2Int64(s, 0)
	})

	answerMap := impl.DefaultQaGoRPCImpl.BatchGetMemberCreateAnswerCount(ctx, memberIds)
	articleMap := impl.DefaultArticleRPCImpl.BatchGetMemberCreateArticleCount(ctx, memberIds)
	voteupMap := impl.DefaultMemberProfileRPCImpl.BatchGetMemberRecievedVoteup(ctx, memberIds)
	collectionMap := impl.DefaultZFavRPCImpl.ConcurrentGetMemberRecievedCollection(ctx, memberIds, 5)
	followingMap := impl.DefaultMemberRPCImpl.BatchGetMemberFollowingCount(ctx, memberIds)
	followerMap := impl.DefaultMemberRPCImpl.BatchGetMemberFollowerCount(ctx, memberIds)

	for _, memberId := range memberIds {
		fmt.Println(fmt.Sprintf("member:%d 回答数:%d, 文章数:%d, 被赞同数:%d, 被收藏数:%d, 关注数:%d, 被关注数:%d",
			memberId, answerMap[memberId], articleMap[memberId], voteupMap[memberId], collectionMap[memberId], followingMap[memberId], followerMap[memberId]))
	}

	answerIdTimeOrder := impl.DefaultQaGoRPCImpl.GetMemberCreateAnswerIds(ctx, memberIds[0], rpc.OrderTypeTime, 10)
	answerIdHotOrder := impl.DefaultQaGoRPCImpl.GetMemberCreateAnswerIds(ctx, memberIds[0], rpc.OrderTypeHot, 10)
	articleIdTimeOrder := impl.DefaultArticleRPCImpl.GetMemberCreateArticleIds(ctx, memberIds[0], rpc.OrderTypeTime, 10)
	articleIdHotOrder := impl.DefaultArticleRPCImpl.GetMemberCreateArticleIds(ctx, memberIds[0], rpc.OrderTypeHot, 10)
	fmt.Println("answerIdTimeOrder:", answerIdTimeOrder)
	fmt.Println("answerIdHotOrder:", answerIdHotOrder)
	fmt.Println("articleIdTimeOrder:", articleIdTimeOrder)
	fmt.Println("articleIdHotOrder:", articleIdHotOrder)

}
