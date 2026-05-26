package conf_stage

import (
	"context"
	"encoding/json"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/apollo"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

type StageRerankConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

func (c *StageRerankConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 1. 没有召回就没有重排
	// 2. 有召回
	// 2.1 有召回 - 有挂载纯Doc 则 判断预制，如果超过则进行切chunk，未超过则跳过切chunk
	// 2.2 有召回 - 有挂载其他Doc 决定保量是否开启
	// 2.3 有召回 - 其他正常走 切chunk
	isPureDoc, totalSize := c.GetOverLengthAndTotalSize(ctx, requestCtx, user)
	// 如果在上下文范围内 且是纯文档 则跳过rerank
	if isPureDoc {
		// 设置为纯挂载 且 满足条件状态
		requestCtx.GetBizContext().SetMountPureDoc(isPureDoc)
		return map[string]map[string]string{
			stream_chat_default_tab_conf.UploadRecallChanLogic: {},
			stream_chat_default_tab_conf.RecallChunkAndScoreLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
					KeySize:                    512,
					KeyStep:                    256,
					KeyOffset:                  0.5,
					ValueSize:                  1024,
					TotalSize:                  int(totalSize),
					ScoreThreshold:             0.0,
					BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
					IsAllowItemSkipChunk:       true,
					ActualChunkSizeLimitPerDoc: 2048,
					ModelName:                  string(rpc.KlaraServiceUrlZhiRerankMix),
				}),
			},
		}
	} else {
		// 默认切chunk & 兜底处理
		var scoreScaleByTag string
		if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_ai_search_general {
			scoreScaleByTag = apollo.GetString(macro.ScoreScaleByTag, "answer_property:亲自答:1.2")
		}
		return map[string]map[string]string{
			stream_chat_default_tab_conf.UploadRecallChanLogic: {},
			stream_chat_default_tab_conf.RecallChunkAndScoreLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
					KeySize:                    512,
					KeyStep:                    256,
					KeyOffset:                  0.5,
					ValueSize:                  1024,
					TotalSize:                  int(totalSize),
					ScoreThreshold:             0.0,
					BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
					EachDocHasChunk:            true,
					ActualChunkSizeLimitPerDoc: 2048,
					ModelName:                  string(rpc.KlaraServiceUrlZhiRerankMix),
					ScoreScaleByTag:            scoreScaleByTag,
				}),
			},
		}
	}
}

// GetOverLengthAndTotalSize 获得剩余长度和切chunk的totalsize
func (c *StageRerankConfig) GetOverLengthAndTotalSize(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) (bool, int64) {
	chatBaseConfig, chatMsgConfig, isChatConfigOK := c.getChatConfig(ctx, requestCtx, user)
	// 构造一个message handler 计算出去recall 内容的其他长度
	modelContextLength := int64(zrecUtil.Max(4096, chatBaseConfig.ContextLength-zrecUtil.Max(0, chatBaseConfig.ExtraContextLength)))
	maxTokensLength := int64(zrecUtil.Max(1024, int(*chatBaseConfig.MaxTokens)))
	var messageLength int64
	if isChatConfigOK {
		recallRes := c.getRecallStageRes(requestCtx)
		tmpRecallItems := c.copyRecallItem(requestCtx, recallRes)
		// 提前预计算 systemPrompt history kbMeta authorMeta mountMeta query 等ContextLength
		handlerConfigs := make([]conf.ChatMsgConfig, 0)
		handlerConfigs = append(handlerConfigs, conf.NewChatMsgConfigBySystem(chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag))
		handlerConfigs = append(handlerConfigs, chatMsgConfig.MsgConfigArr...)
		messageHandler := generate.NewMessageHandler(handlerConfigs, requestCtx, tmpRecallItems, int64(chatBaseConfig.ContextLength), chatBaseConfig.ExtraContextLength, *chatBaseConfig.MaxTokens, false)
		messageLength = messageHandler.GetContextLengthIgnoreRecall()
	}

	// 纯文档 小于等于阈值 则全部喂给模型
	totalSize := modelContextLength - (messageLength + maxTokensLength)

	isPureDoc := false
	if requestCtx.GetBizContext().GetCurrReferenceMount().IsMountPureDoc() && len(requestCtx.GetBizContext().GetKnowledgeBases()) == 0 {
		contentLength := c.getRecallStageContextLength(requestCtx)
		isPureDoc = (totalSize - contentLength) > 0
	}
	return isPureDoc, totalSize
}

// CopyRecallItem Copy
func (c *StageRerankConfig) copyRecallItem(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], sourceItems []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	copyItems := make([]*data_frame.ItemData[entities.Item], 0)
	for _, sourceItem := range sourceItems {
		copyRecall := entities.ItemFromSummaryOtherRecall(
			sourceItem.GetBizItem().GetItemMeta().GetTitle(),
			sourceItem.GetBizItem().GetItemMeta().Abstract,
			sourceItem.GetBizItem().GetItemMeta().Url,
			sourceItem.GetBizItem().GetItemMeta().Content,
			sourceItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource(),
			0,
		)
		copyRecall.Text = sourceItem.GetBizItem().GetItemMeta().Content
		copyRecall.GetItemMeta().IndexDocUniqueId = sourceItem.GetBizItem().GetItemMeta().IndexDocUniqueId
		copyRecall.GetItemMeta().DocType = sourceItem.GetBizItem().GetItemMeta().DocType
		copyRecall.GetItemMeta().DocId = sourceItem.GetBizItem().GetItemMeta().DocId
		copyRecall.GetItemMeta().AuthorId = sourceItem.GetBizItem().GetItemMeta().AuthorId
		copyRecall.GetItemMeta().RecallSourceInfo.KbSources = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.KbSources
		copyRecall.GetItemMeta().RecallSourceInfo.KnowledgeBaseId = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.KnowledgeBaseId
		copyRecall.GetItemMeta().RecallSourceInfo.KnowledgeBaseName = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.KnowledgeBaseName
		copyRecall.GetItemMeta().RecallSourceInfo.PersonalKnowledgeBaseType = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.PersonalKnowledgeBaseType
		copyRecall.GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseType = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseType
		copyRecall.GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseName = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseName
		copyRecall.GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseDesc = sourceItem.GetBizItem().GetItemMeta().RecallSourceInfo.UniversalKnowledgeBaseDesc
		copyItems = append(copyItems, copyRecall.IntoFrameItem(requestCtx))
	}
	return copyItems
}

// GetChatConfig 获得Chat配置
func (c *StageRerankConfig) getChatConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) (conf.ChatConfig, conf.MsgConfig, bool) {
	dynamicStageConfig, isExist := requestCtx.GetBizContext().GetDynamicStageConfig()
	if isExist && dynamicStageConfig != nil {
		generateConfig := dynamicStageConfig.GetDynamicBizLogicConfig(ctx, conf.StageTypeGenerate, requestCtx, user)
		// 可以获取 maxToken def 1024
		chatBaseConfigJson := generateConfig[stream_chat_default_tab_conf.StreamChatLogic][conf.JsonConfigLogicKey.ToConvert()]
		chatMessageConfigJson := generateConfig[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig]

		chatConfig := conf.ChatConfig{}
		err1 := json.Unmarshal([]byte(chatBaseConfigJson), &chatConfig)
		if err1 != nil {
			log.Errorf(ctx, "StageRerankConfig Convert ChatConfig error => config is json unmarshal err")
		}

		chatMsgConfig := conf.MsgConfig{}
		err2 := json.Unmarshal([]byte(chatMessageConfigJson), &chatMsgConfig)
		if err2 != nil {
			log.Errorf(ctx, "StageRerankConfig Convert ChatMsgConfig error => config is json unmarshal err")
		}

		if err1 == nil && err2 == nil {
			return chatConfig, chatMsgConfig, true
		}
	}
	return conf.ChatConfig{}, conf.MsgConfig{}, false
}

// GetRecallStageRes 获得召回阶段内容长度
func (c *StageRerankConfig) getRecallStageRes(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []*data_frame.ItemData[entities.Item] {
	// 召回结果
	recallItems, isExist := requestCtx.GetCommonContext().GetLogicData(conf.RecallCardLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isExist {
		return recallItems
	}
	return []*data_frame.ItemData[entities.Item]{}
}

// GetRecallStageContextLength 获得召回阶段内容长度
func (c *StageRerankConfig) getRecallStageContextLength(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) int64 {
	var recallContentLength int64
	for _, item := range c.getRecallStageRes(requestCtx) {
		docPublishedTimeFormatStr := ""
		if item.GetBizItem().GetItemMeta().PublishedTime > 0 {
			docPublishedTimeFormatStr = time.Unix(item.GetBizItem().GetItemMeta().PublishedTime, 0).Format("2006-01-02")
		}
		// 内容 + 标题 + 时间 + 100(额外buffer 含prompt标签等等)
		recallContentLength +=
			int64(util.UnicodeLen(item.GetBizItem().GetItemMeta().Content) +
				util.UnicodeLen(item.GetBizItem().GetItemMeta().Title) +
				util.UnicodeLen(docPublishedTimeFormatStr) + 100)

	}
	return recallContentLength
}
