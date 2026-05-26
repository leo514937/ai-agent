package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/thrift-go/zhuanlan_thrift/article"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type ArticleRPCImpl struct {
	articleClient  *article.ArticleServiceClient
	articleClient2 *article.ArticleServiceClient
}

var DefaultArticleRPCImpl rpc.ArticleRPC

func init() {
	DefaultArticleRPCImpl = NewColumnRpcImpl()
}
func NewColumnRpcImpl() *ArticleRPCImpl {
	articleClient := tzone.NewClient(
		"ArticleService",
		tzone.TargetName("zhuanlan-service-go"),
		tzone.Timeout(200*time.Millisecond),
	)
	articleClient2 := tzone.NewClient(
		"ArticleService",
		tzone.TargetName("zhuanlan-service"),
		tzone.Timeout(200*time.Millisecond),
	)
	return &ArticleRPCImpl{
		articleClient:  article.NewArticleServiceClient(articleClient),
		articleClient2: article.NewArticleServiceClient(articleClient2),
	}
}

func (r *ArticleRPCImpl) BatchGetMemberCreateArticleCount(ctx context.Context, memberIds []int64) map[int64]int64 {
	var res = make(map[int64]int64)
	runFunc := func(ctx context.Context) (err error) {
		param := &article.BatchGetMemberArticlesCountParam{
			MemberIds: &memberIds,
		}

		resp, err := r.articleClient.BatchGetMemberArticlesCount(ctx, param)
		if err == nil {
			res = resp
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ArticleRPCImpl) GetMemberCreateArticleIds(ctx context.Context, memberId int64, orderType rpc.OrderType, limit int64) []int64 {
	var res = make([]int64, 0)
	runFunc := func(ctx context.Context) (err error) {
		var orderBy string
		if orderType == rpc.OrderTypeHot {
			orderBy = ListArticleByPeopleOrderByVote
		} else {
			orderBy = ListArticleByPeopleOrderByCreated
		}
		param := &article.ListArticleByPeopleParam{
			AuthorID: memberId,
			OrderBy:  &orderBy,
			Limit:    limit,
		}

		resp, err := r.articleClient2.ListArticleByPeople(ctx, param)
		if err == nil {
			for _, v := range resp {
				res = append(res, v.GetMeta().GetID())
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

const ListArticleByPeopleOrderByCreated = "CREATED" // 发布时间由近到远
const ListArticleByPeopleOrderByVote = "VOTE_NUM"   // 点赞数由多到少，但是只排序用户最近发布的 500 篇文章

var _ rpc.ArticleRPC = (*ArticleRPCImpl)(nil)
