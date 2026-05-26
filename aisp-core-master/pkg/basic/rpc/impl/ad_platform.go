package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-bidding_xg_tools/brandai"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type AdPlatformRPCImpl struct {
	brandClient brandai.BrandAiQaService
}

var DefaultAdPlatformImpl rpc.AdPlatFormRPC

func init() {
	DefaultAdPlatformImpl = NewAdPlatform()
}
func NewAdPlatform() *AdPlatformRPCImpl {
	return &AdPlatformRPCImpl{
		brandClient: brandai.NewBrandAiQaServiceClient(tzone.NewClient(
			"BrandAiQaService",
			tzone.Timeout(1*time.Second),
			tzone.TargetName("ad-platform-xg-tools-tzone"))),
	}
}

func (a *AdPlatformRPCImpl) GetRecallList(ctx context.Context, query string, queryMerge string, memberId int64, sessionId string, messageId string, extraInfo *brandai.ExtraInfo) []*model.ItemMeta {
	var res = make([]*model.ItemMeta, 0)
	runFunc := func(ctx context.Context) (err error) {
		request := &brandai.BrandAiQaRequest{
			Query:      query,
			QueryMerge: queryMerge,
			MemberID:   util.Int64String(memberId),
			SessionID:  sessionId,
			MessageID:  messageId,
			ExtraInfo:  extraInfo,
		}
		resp, err := a.brandClient.GetRecallList(ctx, request)
		if err == nil {
			for _, item := range resp {
				if docType, exist := rpc.AdContentTypeMap[item.GetDocType()]; exist {
					res = append(res, &model.ItemMeta{
						DocId:   util.SafeString2Int64(item.GetDocID(), 0),
						DocType: docType,
						Title:   item.GetTitle(),
						Raw:     item.GetText(),
					})
				}
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

var _ rpc.AdPlatFormRPC = (*AdPlatformRPCImpl)(nil)
