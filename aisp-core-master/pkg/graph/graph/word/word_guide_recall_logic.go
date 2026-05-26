package word

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 预制词召回V1

// WordGuideRecallLogic 预制词
type WordGuideRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK                 int32
	klaraEmbeddingClient rpc.KlaraRpcClient
	rumClient            rpc.RumClient[float32]
}

func NewWordGuideRecallLogic(name string, config map[string]string) *WordGuideRecallLogic {
	res := &WordGuideRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认最多召回50个
	res.topK = 50
	res.klaraEmbeddingClient = rpcImpl.GetBgeEmbeddingClient("ensemble")
	res.rumClient = rpcImpl.DefaultFloat32RumClientImpl
	res.RecallFunc = res.guideWordRecall
	return res
}

func (l *WordGuideRecallLogic) guideWordRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordGuideRecallLogic.guideWordRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithField(ctx, "func", "guideWordRecall")
	logger.Debug(ctx, "do running")

	// 根据用户tag 查询 embeddings
	var tags = user.GetBizUser().UserMeta().GetTags()
	logger.Infof(ctx, "print member tag, memberId:%v, tags %v", requestCtx.GetBizContext().MemberId(), tags)

	// 获取 embedding
	embeddingRes := l.klaraEmbeddingClient.BatchInferEmbedding(ctx, tags)
	if embeddingRes == nil || len(embeddingRes) == 0 {
		logger.Errorf(ctx, "embeddingRes length not equal to tags length")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 过滤掉空的embedding
	filterEmbeddingRes := lo.Filter(embeddingRes, func(item []float32, index int) bool {
		return item != nil && len(item) > 0
	})
	if filterEmbeddingRes == nil || len(filterEmbeddingRes) == 0 {
		logger.Warn(ctx, "filterEmbeddingRes length not equal to tags length")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 分别从两个rum 表中获取引导词 与去重动作
	questionRewriteArr := l.doSearchRumWord(
		ctx, int32(len(tags)),
		[]proto.QueryType{proto.QueryType_PREFAB_WORD_QUESTION, proto.QueryType_PREFAB_WORD_HOT_QUESTION},
		filterEmbeddingRes)
	unionByWords := lo.UniqBy(questionRewriteArr, func(item *proto.Query) string { return item.GetQuery() })

	// limit 限制词个数
	finalWords := unionByWords[:zrecUtil.Min(int(l.topK), len(unionByWords))]
	if finalWords == nil || len(finalWords) == 0 {
		log.Error(ctx, "guide word recall empty")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 返回词
	frameItem := make([]*data_frame.ItemData[entities.Item], 0)
	for _, query := range finalWords {
		queryItem := entities.ItemFromQuery(query, -1, macro.CensorTypeMap[query.QueryType])
		frameItem = append(frameItem, queryItem.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}

func (l *WordGuideRecallLogic) doSearchRumWord(ctx context.Context, rumLimit int32, queryTypes []proto.QueryType, embeddingRes [][]float32) []*proto.Query {
	if len(embeddingRes) == 0 {
		return []*proto.Query{}
	}

	logger := log.WithField(ctx, "func", "guideWordRecall-doSearchRumWord")

	// 开启多线程查根据 embedding 查 Rum
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "guideWordRecall-doSearchRumWord"), 500)
	doneCh := make(chan int)
	resChan := make(chan []*proto.Query, len(embeddingRes))
	for _, queryType := range queryTypes {
		for _, embeddings := range embeddingRes {
			tableName, err := macro.PrefabQueryType2RumTableName(queryType)
			if err != nil {
				continue
			}

			queryType := queryType
			embeddings := embeddings
			// 查询 Rum
			wg.Go(func() error {
				words := make([]*proto.Query, 0)
				rumSearchRes := l.rumClient.RumSearch(ctx, tableName,
					[][]float32{embeddings}, rumLimit, "", []string{macro.QuestionRewriteRawFieldName})
				if rumSearchRes == nil || len(rumSearchRes) == 0 {
					return nil
				}
				itemList := lo.Flatten(rumSearchRes)
				for _, item := range itemList {
					word := cast.ToString(item.Fields[macro.QuestionRewriteRawFieldName])
					if word != "" {
						words = append(words, &proto.Query{Query: word, QueryType: queryType})
					}
				}

				// 使用select来判断channel是否关闭
				select {
				case <-doneCh:
					logger.Warnf(ctx, "Stop sending, channel is closed => %+v", words)
					return nil
				default:
					resChan <- words
				}
				return nil
			})
		}
	}

	// 等待所有 goroutine 完成
	go func() {
		wgErr := wg.Wait()
		if wgErr != nil {
			logger.Warnf(ctx, "Wait Err => %v", wgErr)
		}
		close(doneCh)
		close(resChan)
	}()

	finalWords := make([]*proto.Query, 0)
	for words := range resChan {
		finalWords = append(finalWords, words...)
	}
	return finalWords
}
