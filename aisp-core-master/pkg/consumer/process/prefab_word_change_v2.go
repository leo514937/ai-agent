package process

import (
	"context"
	"encoding/json"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/stream"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/pkg/errors"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

var (
	ContentTypes   = []string{content_core_thrift.ContentTypeAIPredefinedWord}
	ContentPoolIds = []int64{2305843009215972782}
)

type PrefabWordChangeV2Processor struct {
	contentCoreClient    rpc.ContentCoreRPC
	klaraEmbeddingClient rpc.KlaraRpcClient
	rumClient            rpc.RumClient[float32]
	rumCache             rum_cache.RumCache
	redisDao             dao.PrefabWordV2Dao
	wordWrapperService   word.WordMapperService
}

func NewPrefabWordChangeV2Processor() *PrefabWordChangeV2Processor {
	return &PrefabWordChangeV2Processor{
		contentCoreClient:    rpcImpl.NewContentCoreRPCImpl(),
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("ensemble"),
		rumClient:            rpcImpl.DefaultFloat32RumClientImpl,
		rumCache:             rum_cache.NewRumCache(),
		redisDao:             impl.NewPrefabWordV2Dao(),
		wordWrapperService:   word.NewWordMapperService(),
	}
}

func (d *PrefabWordChangeV2Processor) TopicName() macro.TopicName {
	return macro.ContentPool
}

func (d *PrefabWordChangeV2Processor) Process(ctx context.Context, message *stream.Message) error {
	return d.DoHandle(ctx, message.Value)
}

// DoHandle 执行(独立出来方便单测)
func (d *PrefabWordChangeV2Processor) DoHandle(ctx context.Context, messageValue []byte) error {
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeV2Processor",
		"func":  "Process",
	})

	msg := &module.ContentPoolCoreActionMsg{}
	err := json.Unmarshal(messageValue, msg)
	if err != nil {
		return errors.New("unmarshal error")
	}

	if !lo.Contains(ContentPoolIds, msg.ContentPoolID) {
		//logger.Warnf(ctx, "processPrefabWord contentPoolId is not in ContentPoolIds, msg: %v", util.GetJSONIgnoreError(msg))
		return nil
	}

	if !lo.Contains(ContentTypes, msg.ContentType) {
		logger.Warnf(ctx, "processPrefabWord contentType is not in ContentTypes, msg: %v", util.GetJSONIgnoreError(msg))
		return nil
	}

	docId, err := cast.ToInt64E(msg.OutID)
	if err != nil {
		return err
	}

	modelContent := model.NewContentWithContentType(docId, msg.ContentType)
	// 获取内容详情
	contentInfoMap := d.contentCoreClient.BatchGetContent(ctx, []model.Content{modelContent},
		base.ContentInfoFieldContentTitle, base.ContentInfoFieldContentBizExt)
	contentInfo, isOk := contentInfoMap[modelContent]
	if !isOk {
		d.statsdByError(ctx, prefabStatsdTypeSave)
		return errors.New(fmt.Sprintf("Content is not found  sourceMsg:%s, docId: %d, contentType:%s",
			util.GetJSONIgnoreError(msg), docId, msg.ContentType))
	}

	if msg.IsPoolActionInsert() {
		// 计算 embedding
		embeddings := d.klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{contentInfo.GetTitle()})
		// 检查 embedding是否合规
		embeddingIsOk := util.CheckTwoDimEmbedding(embeddings)
		if !embeddingIsOk {
			d.statsdByError(ctx, prefabStatsdTypeSave)
			errorMsg := fmt.Sprintf("embedding is not Ok  sourceMsg:%s, docId: %d, contentType:%s, contentTitle:%s",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, contentInfo.GetTitle())
			logger.Error(ctx, errorMsg)
			return errors.New(errorMsg)
		}

		bizExt, bizExtErr := model.ParseAIPredefinedWordBizExt(contentInfo.GetBizExt())
		if bizExtErr != nil {
			d.statsdByError(ctx, prefabStatsdTypeSave)
			errorMsg := fmt.Sprintf("content info bizExt is not Unmarshal  sourceMsg:%s, docId: %d, contentType:%s, contentTitle:%s, errorMsg:%v",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, contentInfo.GetTitle(), bizExtErr)
			logger.Error(ctx, errorMsg)
			return errors.New(errorMsg)
		}

		prefabWord := &model.PrefabWord{
			DocId:             docId,
			DocType:           model.GetDocType(msg.ContentType),
			ContentType:       msg.ContentType,
			QueryType:         proto.QueryType_PREFAB_WORD_QUESTION,
			SourceChannel:     bizExt.SourceChannel,
			SourceQuestion:    bizExt.SourceQuestion,
			AiRewriteQuestion: contentInfo.GetTitle(),
		}
		jsonString, jsonStringErr := prefabWord.ToJsonString()
		if jsonStringErr != nil {
			d.statsdByError(ctx, prefabStatsdTypeSave)
			errorMsg := fmt.Sprintf("PrefabWord toJson error  sourceMsg:%s, docId: %d, contentType:%s, contentTitle:%s, errorMsg:%v",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, contentInfo.GetTitle(), jsonStringErr)
			logger.Error(ctx, errorMsg)
			return errors.New(errorMsg)
		}

		// 更新 rum
		actionRes := d.rumClient.RumUpsert(ctx, macro.AiPrefabWordV2RumTable, docId, embeddings[0], "", map[string]interface{}{
			macro.QuestionRewriteHashFieldName:   docId,
			macro.QuestionRewriteStatusFieldName: 1,
			macro.QuestionRewriteRawFieldName:    jsonString,
		})
		// 更新词数据到MySQL
		_, saveMySQLErr := d.wordWrapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
			WordType: int32(proto.QueryType_PREFAB_WORD_QUESTION),
			Word:     contentInfo.GetTitle(),
			SourceId: cast.ToString(docId),
		})
		if !actionRes || saveMySQLErr != nil {
			d.statsdByError(ctx, prefabStatsdTypeSave)
			logger.Errorf(ctx, "Save PrefabWordToRum Err sourceMsg:%s, docId: %d, contentType:%s, contentTitle:%s | MySQL:%v",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, contentInfo.GetTitle(), saveMySQLErr)
		} else {
			// 移除redis中的删除错误记录(只有异常情况下才会有记录)
			d.rumCache.RemoveDeleteErrorCache(ctx, docId, macro.AiPrefabWordV2RumTable)
			d.statsdBySuccess(ctx, prefabStatsdTypeSave)
			logger.Infof(ctx, "Save PrefabWordToRum Success sourceMsg:%s, docId: %d, contentType:%s, contentTitle:%s",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, contentInfo.GetTitle())
		}
		return nil
	} else if msg.IsPoolActionDelete() {
		// 删除 rum
		actionRes := d.rumClient.RumDelete(ctx, macro.AiPrefabWordV2RumTable, docId, "")
		// 删除 MySQL
		_, deleteMySQLErr := d.wordWrapperService.RemoveWord(ctx, contentInfo.GetTitle(), int32(proto.QueryType_PREFAB_WORD_QUESTION))
		// 清除词缓存（判断是否是预制词）
		resource.RedisLocalCache.BatchDelete(ctx, []string{contentInfo.GetTitle()}, util.StringKeyGeneratorFunc, util.SuggestQueriesKeyOption)
		if !actionRes || deleteMySQLErr != nil {
			// 保存删除错误记录到 redis中 便于后期进行后过滤(只有异常情况下才会有记录)
			d.rumCache.SaveDeleteErrorCache(ctx, docId, macro.AiPrefabWordV2RumTable)
			d.statsdByError(ctx, prefabStatsdTypeDeleted)
			logger.Errorf(ctx, "Delted PrefabWordToRum Err sourceMsg:%s, docId: %d, contentType:%s | MySQL:%v",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType, deleteMySQLErr)
		} else {
			d.statsdBySuccess(ctx, prefabStatsdTypeDeleted)
			logger.Infof(ctx, "Delted PrefabWordToRum Success sourceMsg:%s, docId: %d, contentType:%s",
				util.GetJSONIgnoreError(msg), docId, msg.ContentType)
		}
		return nil
	}
	logger.Warnf(ctx, "not found action sourceMsg:%s, docId: %d, contentType:%s", util.GetJSONIgnoreError(msg), docId, msg.ContentType)
	return nil
}

type prefabStatsdType string

func (p prefabStatsdType) String() string {
	return string(p)
}

const (
	prefabStatsdTypeSave    prefabStatsdType = "upsert"
	prefabStatsdTypeDeleted prefabStatsdType = "delete"
)

func (d *PrefabWordChangeV2Processor) statsdBySuccess(ctx context.Context, op prefabStatsdType) {
	statsdTmp := fmt.Sprintf("aisp-core.scene.%s.span.prefab_word.%s.success.count",
		log.GetSceneFromContext(ctx), op.String())
	statsd.Increment(statsdTmp)
}

func (d *PrefabWordChangeV2Processor) statsdByError(ctx context.Context, op prefabStatsdType) {
	statsdTmp := fmt.Sprintf("aisp-core.scene.%s.span.prefab_word.%s.error.count",
		log.GetSceneFromContext(ctx), op.String())
	statsd.Increment(statsdTmp)
}
