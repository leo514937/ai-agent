package impl

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/thrift-go/zfav_go_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

type ZFavRPCImpl struct {
	zFavClient *zfav_go_thrift.ZfavServiceClient
}

var DefaultZFavRPCImpl rpc.ZFavRPC

func init() {
	DefaultZFavRPCImpl = NewZFavRPCImpl()
}

func NewZFavRPCImpl() *ZFavRPCImpl {
	return &ZFavRPCImpl{
		zFavClient: zfav_go_thrift.NewZfavServiceClient(tzone.NewClient(
			"ZfavService",
			tzone.TargetName("zfav-go-service"),
			tzone.Timeout(300*time.Millisecond),
		)),
	}
}

func (r *ZFavRPCImpl) GetMemberRecievedCollection(ctx context.Context, memberId int64) int64 {
	var res int64
	runFunc := func(ctx context.Context) (err error) {
		requestParam := &zfav_go_thrift.CountMemberFavoritedParam{
			MemberID: memberId,
		}

		resp, err := r.zFavClient.CountMemberFavorited(ctx, requestParam)
		if err == nil {
			res = resp
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ZFavRPCImpl) ListMemberFavlist(ctx context.Context, memberId int64) []*zfav_go_thrift.Favlist {
	var res []*zfav_go_thrift.Favlist
	runFunc := func(ctx context.Context) (err error) {
		requestParam := &zfav_go_thrift.ListMemberFavlistParam{
			RequestMemberID: memberId,
			MemberID:        memberId,
		}

		resp, err := r.zFavClient.ListMemberFavlist(ctx, requestParam)
		if err == nil && resp != nil {
			res = resp.GetData()
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ZFavRPCImpl) GetFavlist(ctx context.Context, memberId int64, favListId int64) *zfav_go_thrift.Favlist {
	var res *zfav_go_thrift.Favlist
	runFunc := func(ctx context.Context) (err error) {
		requestParam := &zfav_go_thrift.GetFavlistParam{
			RequestMemberID: memberId,
			ID:              &favListId,
		}

		resp, err := r.zFavClient.GetFavlist(ctx, requestParam)
		if err == nil && resp != nil {
			res = resp
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ZFavRPCImpl) ListFavlistItem(ctx context.Context, memberId int64, favListId int64) []*zfav_go_thrift.FavlistItem {
	var res []*zfav_go_thrift.FavlistItem
	runFunc := func(ctx context.Context) (err error) {
		requestParam := &zfav_go_thrift.ListFavlistItemParam{
			RequestMemberID: memberId,
			FavlistID:       &favListId,
		}

		resp, err := r.zFavClient.ListFavlistItem(ctx, requestParam)
		if err == nil && resp != nil {
			res = resp.GetData()
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ZFavRPCImpl) ConcurrentGetMemberRecievedCollection(ctx context.Context, memberIds []int64, concurrency int) map[int64]int64 {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetMemberRecievedCollection", 500).SetLimit(concurrency)
	for _, memberId := range memberIds {
		memberId := memberId
		group.Go(func() error {
			resultMap.Store(memberId, r.GetMemberRecievedCollection(ctx, memberId))
			return nil
		})
	}
	_ = group.Wait()

	result := map[int64]int64{}
	for _, memberId := range memberIds {
		if collectionCnt, ok := resultMap.Load(memberId); ok {
			result[memberId] = collectionCnt.(int64)
		} else {
			result[memberId] = 0
		}
	}

	return result
}

var _ rpc.ZFavRPC = (*ZFavRPCImpl)(nil)
