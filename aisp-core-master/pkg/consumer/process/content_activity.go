package process

import (
	"context"
	"encoding/json"

	"git.in.zhihu.com/go/cafe/stream"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word/word_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// ContentActivityProcessor 内容平台 内容更新时通知事件
type ContentActivityProcessor struct {
	allowContentType []string
	cacheDao         dao.RelatedWordCacheDao
}

func NewContentActivityProcessor() *ContentActivityProcessor {
	return &ContentActivityProcessor{
		allowContentType: []string{content_core_thrift.ContentTypeAnswer},
		cacheDao:         impl.NewRelatedWordCacheDao(),
	}
}

func (d *ContentActivityProcessor) TopicName() macro.TopicName {
	return macro.ContentActivity
}

func (d *ContentActivityProcessor) Process(ctx context.Context, message *stream.Message) error {
	return d.DoHandleProcess(ctx, message.Value, false, false)
}

// DoHandleProcess 执行(独立出来方便单测)
func (d *ContentActivityProcessor) DoHandleProcess(ctx context.Context, messageValue []byte, isTask bool, isStock bool) error {
	logger := log.WithFields(ctx, map[string]any{
		"class": "ContentActivityProcessor",
		"func":  "Process",
	})
	event := &module.ContentActivityEvent{}
	err := json.Unmarshal(messageValue, event)
	if err != nil {
		logger.Warnf(ctx, "json unmarshal error: %s", err.Error())
		return err
	}

	if !lo.Contains(d.allowContentType, event.ContentType) {
		// 主要是为了确认 消费者可以真正的在生产环境运行起来 而输出的日志（现实场景输出量巨大 故而关掉）
		logger.Warnf(ctx, "content type not allowed: %s", event.ContentType)
		return nil
	}

	cacheKey := d.cacheDao.CreateAskCacheKey(model.NewContentWithDocType(cast.ToInt64(event.OutId), word_util.WordDocType2DocType(d.convertDocType(event.ContentType))))
	if !isTask {
		// 如果已有缓存存在 才会去触发更新缓存动作
		items, _ := d.cacheDao.GetCache(ctx, proto.SuggestQueriesType_ASK_AGAIN_RELATED.String(), cacheKey)
		if len(items) == 0 {
			return nil
		}
	} else {
		// 判断是否是存量数据
		if isStock {
			// 如果已有缓存存在 则直接退出更新缓存动作
			items, _ := d.cacheDao.GetCache(ctx, proto.SuggestQueriesType_ASK_AGAIN_RELATED.String(), cacheKey)
			if len(items) != 0 {
				logger.Infof(ctx, "cache exists, so return")
				return nil
			}
		}
	}

	// 更新缓存 (按照算法老师要求，需要更新缓存期间首个用户延迟，需要在得到触发时间后 直接覆盖更新缓存)
	logger.Infof(ctx, "update cache for content activity: %s:%s", event.OutId, event.ContentType)
	// 获取当前图配置
	req := &proto.SuggestQueriesRequest{
		Type: proto.SuggestQueriesType_ASK_AGAIN_RELATED,
		Header: &proto.RequestHeader{
			ClientSource:  proto.ClientSource_UNDEFINED_SOURCE,
			TrafficSource: proto.TrafficSource_undefined_traffic,
		},
		Info: &proto.RequestInfo{
			SessionId: "",
			Message: &proto.ChatMessage{
				MessageId:   "",
				TimestampMs: 0,
				Type:        proto.ChatMessageType_TEXT,
				Text:        "",
			},
			MemberId: 0,
		},
		DocAboutQueriesRequest: &proto.DocAboutQueriesRequest{
			DocId:   cast.ToInt64(event.OutId),
			DocType: d.convertDocType(event.ContentType),
		},
	}
	graphLogicConfig, _ := conf.GetGraphConfig(conf.LogicConfigNameByQueriesAnswerAsk)
	bizRequestContext := entities.NewRequestContextFromSuggestQueriesRequest(req, graphLogicConfig.GetBizConfigMap(), true)
	defer bizRequestContext.ABCommit() // 手动提交数据给布谷实验平台
	_, _, _, err = graph.RunGraph(ctx, bizRequestContext, nil)
	if err != nil {
		util.Increment(ctx, macro.CommonStatsPrefix+".word_cache_modify_fail.count")
		logger.WithError(ctx, err).Error(ctx, "run graph failed => SuggestQueries")
		return err
	} else {
		util.Increment(ctx, macro.CommonStatsPrefix+".word_cache_modify_succ.count")
	}
	return nil
}

func (d *ContentActivityProcessor) convertDocType(contentType string) proto.DocType {
	docType := proto.DocType_UNKNOWN_DOCTYPE
	switch contentType {
	case content_core_thrift.ContentTypeAnswer:
		docType = proto.DocType_ANSWER
	case content_core_thrift.ContentTypeArticle:
		docType = proto.DocType_ARTICLE
	default:
	}
	return docType
}
