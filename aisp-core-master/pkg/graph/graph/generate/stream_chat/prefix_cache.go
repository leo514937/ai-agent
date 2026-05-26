package stream_chat

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const (
	// PrefixCacheKeyPrefix Redis 缓存 key 前缀
	PrefixCacheKeyPrefix = "prefix_cache_response_id"
)

// PrefixCacheManager 管理 System Prompt 的 Prefix Cache
type PrefixCacheManager struct {
	modelGatewayRPC modelapi.ModelTarget
}

// NewPrefixCacheManager 创建 PrefixCacheManager 实例
func NewPrefixCacheManager(modelGatewayRPC modelapi.ModelTarget) *PrefixCacheManager {
	return &PrefixCacheManager{
		modelGatewayRPC: modelGatewayRPC,
	}
}

// BuildRequestWithPrefixCache 为请求添加 Prefix Cache 支持
func (m *PrefixCacheManager) BuildRequestWithPrefixCache(ctx context.Context, chatRequest *dto.ChatRequest) *dto.ChatRequest {
	var responseId string
	if config.GetBool(macro.OpenPrefixCache, false) {
		responseId = m.GetPrefixCacheResponseId(ctx, chatRequest.AIProfile, chatRequest.ModelName)
	}

	if responseId != "" {
		chatRequest.PreviousResponseId = responseId
	} else {
		chatRequest.ExtraBody["store"] = false
	}

	return chatRequest
}

// GetPrefixCacheResponseId 获取缓存的 Prefix Cache Response ID
func (m *PrefixCacheManager) GetPrefixCacheResponseId(ctx context.Context, systemPrompt string, modelName string) string {
	res := make(map[string]string, 1)

	cacheKey := m.buildCacheKey(modelName, systemPrompt)

	resource.RedisLocalCache.BatchGet(ctx, []string{cacheKey}, util.StringKeyGeneratorFunc,
		func(params interface{}) interface{} {
			paramStr := params.([]string)[0]
			responseId := m.SetPrefixCache(ctx, systemPrompt, modelName)
			if responseId == "" {
				return map[string]string{}
			}
			return map[string]string{
				paramStr: responseId,
			}
		}, &res, util.SystemPromptPrefixCacheOption)

	return res[cacheKey]
}

// SetPrefixCache 设置 Prefix Cache，返回 Response ID
func (m *PrefixCacheManager) SetPrefixCache(ctx context.Context, systemPrompt string, modelName string) string {
	messages := []*dto.ChatRequestMessage{
		{
			Role:    dto.ChatRequestMessageRoleSystem,
			Content: systemPrompt,
		},
	}

	// 构建 ChatRequest
	chatRequest := &dto.ChatRequest{
		ModelName: modelName,
		Messages:  messages,
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
			"caching":  map[string]interface{}{"type": "enabled", "prefix": true},
		},
	}

	// 调用 Responses 接口
	response, err := m.modelGatewayRPC.Responses(ctx, chatRequest)
	if err != nil || response == nil || !strings.HasPrefix(response.ResponseId, "resp_") {
		log.Errorf(ctx, "ModelGatewayRPC.Responses failed: %v", err)
		util.Increment(ctx, macro.CommonStatsPrefix+".set_prefix_cache.failed.count")
		return ""
	}

	util.Increment(ctx, macro.CommonStatsPrefix+".set_prefix_cache.success.count")

	return response.ResponseId
}

// DeletePrefixCache 删除 Prefix Cache
func (m *PrefixCacheManager) DeletePrefixCache(ctx context.Context, modelName string, aiProfile string) {
	cacheKey := m.buildCacheKey(modelName, aiProfile)
	resource.RedisLocalCache.BatchDelete(ctx, []string{cacheKey}, util.StringKeyGeneratorFunc, util.SystemPromptPrefixCacheOption)
}

// buildCacheKey 构建缓存 key
func (m *PrefixCacheManager) buildCacheKey(modelName string, systemPrompt string) string {
	return fmt.Sprintf("%s:%s:%s", PrefixCacheKeyPrefix, modelName, util.MD5(systemPrompt))
}
