package impl

import (
	"context"

	"git.in.zhihu.com/go/base/grpc"
	user1 "git.in.zhihu.com/pb-go/feature-schema-proto/feature/user"
	"git.in.zhihu.com/pb-go/feature-schema-proto/serving"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util/failsafe"
)

type ZFeatureGRPCImpl struct {
	servingClient serving.FeatureServiceClient
	timeout       int // 单位毫秒
	maxBatch      int
}

var _ rpc.ZFeatureGRPC = (*ZFeatureGRPCImpl)(nil)

func NewZFeatureGRPCImpl() *ZFeatureGRPCImpl {
	conn, _ := grpc.DialContext(context.Background(), "zfeature-grpc-service")
	return &ZFeatureGRPCImpl{
		servingClient: serving.NewFeatureServiceClient(conn),
		timeout:       200, // 默认 200ms 的超时
		maxBatch:      100,
	}
}

func (r *ZFeatureGRPCImpl) SetTimeout(timeout int) *ZFeatureGRPCImpl {
	r.timeout = timeout
	return r
}

// BatchGetLastBehaviors 获取 LastN
func (r *ZFeatureGRPCImpl) BatchGetLastBehaviors(
	ctx context.Context,
	sceneCode string,
	abRequestUserInfo *serving.RequestUser,
	docIds []model.Content) map[model.Content]*user1.LastBehaviors {

	featureInfoRes := r.BatchGetFeatureInfoWithWindow(ctx, sceneCode, 100, abRequestUserInfo, docIds)
	if len(featureInfoRes) == 0 {
		return map[model.Content]*user1.LastBehaviors{}
	}

	lastBehaviorsMap := make(map[model.Content]*user1.LastBehaviors)
	for _, v := range featureInfoRes {
		if v.GetUserInfo() == nil || v.GetUserInfo().GetLastBehaviors() == nil {
			continue
		}
		key := model.Content{ContentID: v.Id.Id, ContentType: v.Id.DocType}
		lastBehaviorsMap[key] = v.GetUserInfo().GetLastBehaviors()
	}
	return lastBehaviorsMap
}

func (r *ZFeatureGRPCImpl) BatchGetFeatureInfo(
	ctx context.Context,
	sceneCode string,
	abRequestUserInfo *serving.RequestUser,
	docIds []model.Content) map[model.Content]*serving.FeatureInfo {
	return r.BatchGetFeatureInfoWithWindow(ctx, sceneCode, 100, abRequestUserInfo, docIds)
}

func (r *ZFeatureGRPCImpl) BatchGetFeatureInfoWithWindow(
	ctx context.Context,
	sceneCode string, windowSize int,
	abRequestUserInfo *serving.RequestUser,
	docIds []model.Content) map[model.Content]*serving.FeatureInfo {

	res := make(map[model.Content]*serving.FeatureInfo)
	groupGetFunc := func(ids interface{}) interface{} {
		docIdsTmp := ids.([]model.Content)
		return r.batchFeature(ctx, sceneCode, abRequestUserInfo, docIdsTmp)
	}
	safe_group.BatchGet(windowSize, docIds, groupGetFunc, &res)
	return res
}

func (r *ZFeatureGRPCImpl) batchFeature(ctx context.Context, sceneCode string, requestUser *serving.RequestUser, id []model.Content) map[model.Content]*serving.FeatureInfo {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "pkg.basic.rpc.impl.FeatureSchemaRPCImpl.BatchGetFeatureInfo",
		"sceneCode": sceneCode,
	})

	result := make(map[model.Content]*serving.FeatureInfo, len(id))
	docIds := make([]*content.DocIdentity, 0, len(id))
	for _, dic := range id {
		docIds = append(docIds, &content.DocIdentity{
			Id:      dic.ContentID,
			DocType: dic.ContentType,
		})
	}

	if len(docIds) == 0 {
		return result
	}

	runFunc := func(ctx context.Context) error {
		req := &serving.BatchGetFeatureInfoRequest{
			Ids:         docIds,
			SceneCode:   sceneCode,
			RequestUser: requestUser,
		}
		resp, err := r.servingClient.BatchGetFeatureInfo(ctx, req)
		if err != nil {
			logger.Errorf(ctx, "batch get feature info failed, %v", err)
			return err
		}
		features := resp.GetFeatureInfos()
		for _, f := range features {
			ff := f
			key := model.Content{ContentID: ff.GetId().GetId(), ContentType: ff.GetId().GetDocType()}
			result[key] = ff
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return result
}
