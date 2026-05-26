package rpc

import (
	"context"

	user1 "git.in.zhihu.com/pb-go/feature-schema-proto/feature/user"
	"git.in.zhihu.com/pb-go/feature-schema-proto/serving"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type ZFeatureGRPC interface {
	// BatchGetFeatureInfo 批量获取最新版本特征 版本生成频率（用户 1s，其他类型 1min ）
	BatchGetFeatureInfo(ctx context.Context, sceneCode string, abRequestUserInfo *serving.RequestUser, docIds []model.Content) map[model.Content]*serving.FeatureInfo

	// BatchGetLastBehaviors 批量获取LastN
	BatchGetLastBehaviors(ctx context.Context, sceneCode string, abRequestUserInfo *serving.RequestUser, docIds []model.Content) map[model.Content]*user1.LastBehaviors

	// BatchGetFeatureInfoWithWindow BatchGetFeatureInfoWithWindow
	BatchGetFeatureInfoWithWindow(ctx context.Context, sceneCode string, windowSize int, abRequestUserInfo *serving.RequestUser, docIds []model.Content) map[model.Content]*serving.FeatureInfo
}
