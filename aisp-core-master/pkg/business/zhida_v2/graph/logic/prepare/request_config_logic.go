package prepare

import (
	"context"

	apollo "git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 处理request配置
type RequestConfigLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig]
}

type requestConfig struct {
	abParams       map[zlab.SceneId]map[string]string
	logicConfigMap map[string]map[string]string
}

func NewRequestConfigLogic(name string, config map[string]string) *RequestConfigLogic {
	res := &RequestConfigLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig](name, config),
	}

	res.FillUserFunc = res.getRequestConfig
	res.MergeUserFunc = res.setRequestConfig
	return res
}

func (r *RequestConfigLogic) getRequestConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) (requestConfig, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "prepare.RequestConfigLogic.getRequestConfig")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	logger := log.WithField(ctx, "getRecallOption", "")

	config := requestConfig{
		abParams:       map[zlab.SceneId]map[string]string{},
		logicConfigMap: requestCtx.GetBizContext().GetLogicConfigMap(),
	}

	// 等于v2 强制关闭重答缓存
	if requestCtx.GetBizContext().RequestHeader().GetVersion() == graph_constant.ZhiDaV2Version {
		caseConfig := requestCtx.GetBizContext().GetRunCaseConfig()
		caseConfig.IsUseSessionCache = false
		caseConfig.IsSaveSessionCache = false
		requestCtx.GetBizContext().SetRunCaseConfig(caseConfig)
	}

	// 判断流量来源是否开启缓存
	if r.isEnableCacheTrafficSource(requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) {
		requestCtx.GetBizContext().SetEnableCache(true)
	}

	// 填充 ab 实验参数
	for sceneId, zlabParams := range requestCtx.GetBizContext().GetAbParamMap() {
		for _, zlabParam := range zlabParams {
			abContext := requestCtx.GetBizContext().GetABContext(sceneId)
			abValue := abContext.GetZlabABValue(zlabParam)
			if _, exist := config.abParams[sceneId]; !exist {
				config.abParams[sceneId] = map[string]string{}
			}
			config.abParams[sceneId][zlabParam.Key] = abValue
		}
	}

	// 如果是跑 case 模式，覆盖相关配置
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen {
		for logicName, configMap := range requestCtx.GetBizContext().GetRunCaseConfig().LogicConfig {
			for configKey, configValue := range configMap {
				if config.logicConfigMap[logicName] == nil {
					config.logicConfigMap[logicName] = make(map[string]string)
				}
				config.logicConfigMap[logicName][configKey] = configValue
			}
		}
	}

	logger.Infof(ctx, "logicConfig:%s, abParam:%s", util.GetJSONIgnoreError(config.logicConfigMap), util.GetJSONIgnoreError(config.abParams))
	constant.DataOutputNodeLog.Infof(logCtx, "logicConfig:%s, abParam:%s", util.GetJSONIgnoreError(config.logicConfigMap), util.GetJSONIgnoreError(config.abParams))

	return config, nil
}

func (r *RequestConfigLogic) setRequestConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], config requestConfig) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.RequestConfigLogic.setRequestConfig")
	defer span.Finish()

	for scene, abParamValue := range config.abParams {
		for key, value := range abParamValue {
			requestCtx.GetBizContext().AddAbParamValue(scene, key, value)
		}
	}
	if len(config.logicConfigMap) > 0 {
		requestCtx.GetBizContext().SetLogicConfigMap(config.logicConfigMap)
	}

	return nil
}

func (r *RequestConfigLogic) isEnableCacheTrafficSource(source proto.TrafficSource) bool {
	ZhidaDisableCacheTrafficSource := apollo.GetStringArray(macro.ZhidaDisableCacheTrafficSource, ",", []string{})
	return !lo.Contains(ZhidaDisableCacheTrafficSource, source.String())
}
