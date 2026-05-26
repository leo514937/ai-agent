package stage_config

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

type GraphStageLogicConfig[R, U, T any] interface {
	// GetGraphBizType 获取Graph 当前图名称
	GetGraphBizType() string

	GetRecallGraphBizType() string

	GetDeepSearchGraphBizType() string

	// GetDefaultBizConfigMap 获取默认业务配置
	GetDefaultBizConfigMap() map[string]map[string]string

	// GetAbParamMap 获取AB参数Map
	GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue

	// GetDynamicBizLogicConfig 获取动态阶段配置（阶段配置可覆盖默认业务配置）
	GetDynamicBizLogicConfig(
		ctx context.Context,
		stageType conf.StageType,
		requestCtx *data_frame.RequestContext[R, U, T],
		user *data_frame.UserData[U]) map[string]map[string]string
}

type StageLogicConfig[R, U, T any] interface {
	// GetConfigMap 获取阶段配置
	GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[R, U, T], user *data_frame.UserData[U]) map[string]map[string]string
}
