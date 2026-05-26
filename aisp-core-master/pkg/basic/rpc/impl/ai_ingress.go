package impl

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	ingress "git.in.zhihu.com/one-rpc-go/thrift-ai_ingress/ai_ingress_thrift"
	knowledge "git.in.zhihu.com/one-rpc-go/thrift-ai_ingress/knowledge_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
)

type AiIngressRPCImpl struct {
	knowledgeClient *knowledge.KnowledgeServiceClient
	ingressClient   *ingress.AIIngressServiceClient
}

var DefaultAiIngressRPCImpl rpc.AiIngressRPC

func init() {
	DefaultAiIngressRPCImpl = NewAiIngressRPCImpl()
}
func NewAiIngressRPCImpl() *AiIngressRPCImpl {
	return &AiIngressRPCImpl{
		ingressClient: ingress.NewAIIngressServiceClient(tzone.NewClient(
			"AIIngressService",
			tzone.TargetName("ai-ingress-rpc"),
			tzone.Timeout(200*time.Millisecond),
		)),
		knowledgeClient: knowledge.NewKnowledgeServiceClient(tzone.NewClient(
			"KnowledgeService",
			tzone.TargetName("ai-ingress-rpc"),
			tzone.Timeout(200*time.Millisecond),
		)),
	}
}

func (a *AiIngressRPCImpl) GetOperationConfig(ctx context.Context, operationId int64) string {
	if operationId == 0 {
		return ""
	}

	var jsonConfig = ""
	runFunc := func(ctx context.Context) (err error) {
		resp, err := a.ingressClient.GetConfDetail(ctx, &ingress.GetConfDetailReq{
			ID: operationId,
		})
		if err == nil {
			jsonConfig = resp.GetConfigJSON()
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return jsonConfig
}

func (a *AiIngressRPCImpl) GetKnowledgeBaseDetail(ctx context.Context, memberId int64, knowledgeBaseId int64, limit int64) *knowledge.GetKnowledgeResponse {
	var res *knowledge.GetKnowledgeResponse
	runFunc := func(ctx context.Context) (err error) {
		param := &knowledge.GetKnowledgeRequest{
			MemberId:    memberId,
			KnowledgeId: knowledgeBaseId,
			Limit:       &limit,
		}

		resp, err := a.knowledgeClient.FetchKnowledgeDetails(ctx, param)
		if err == nil {
			res = resp
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (a *AiIngressRPCImpl) ConcurrentGetKnowledgeBaseDetail(ctx context.Context, memberId int64, knowledgeBaseIds []int64, limit int64, concurrency int) map[int64]*knowledge.GetKnowledgeResponse {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetKnowledgeBaseDetail", 800).SetLimit(concurrency)
	for _, knowledgeBaseId := range knowledgeBaseIds {
		knowledgeBaseId := knowledgeBaseId
		group.Go(func() error {
			resultMap.Store(knowledgeBaseId, a.GetKnowledgeBaseDetail(ctx, memberId, knowledgeBaseId, limit))
			return nil
		})
	}
	_ = group.Wait()

	result := map[int64]*knowledge.GetKnowledgeResponse{}
	for _, knowledgeBaseId := range knowledgeBaseIds {
		if detail, ok := resultMap.Load(knowledgeBaseId); ok {
			result[knowledgeBaseId] = detail.(*knowledge.GetKnowledgeResponse)
		} else {
			result[knowledgeBaseId] = nil
		}
	}

	return result
}

func (a *AiIngressRPCImpl) BatchGetKnowledgeBaseVisibility(ctx context.Context, knowledgeBaseIds []int64) map[int64]proto.KnowledgeBaseVisibility {
	var res map[int64]proto.KnowledgeBaseVisibility
	runFunc := func(ctx context.Context) (err error) {
		knowledgeBaseIds = lo.Uniq(knowledgeBaseIds)
		res = make(map[int64]proto.KnowledgeBaseVisibility, len(knowledgeBaseIds))
		param := &knowledge.BatchGetKnowledgeVisibilityRequest{
			KnowledgeIds: knowledgeBaseIds,
		}

		resp, err := a.knowledgeClient.BatchGetKnowledgeVisibility(ctx, param)
		if err == nil {
			for id, visibility := range resp.GetKnowledgeVisibility() {
				res[id] = visibilityPbMap[visibility]
			}
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return res
}

var visibilityPbMap = map[knowledge.KnowledgeBaseVisibility]proto.KnowledgeBaseVisibility{
	knowledge.KnowledgeBaseVisibility_PRIVATE:        proto.KnowledgeBaseVisibility_PRIVATE,
	knowledge.KnowledgeBaseVisibility_PUBLIC_FEATURE: proto.KnowledgeBaseVisibility_PUBLIC_FEATURE,
	knowledge.KnowledgeBaseVisibility_PUBLIC_ONLY:    proto.KnowledgeBaseVisibility_PUBLIC_ONLY,
}

var _ rpc.AiIngressRPC = (*AiIngressRPCImpl)(nil)
