package service

import (
	"context"
	"sort"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
)

const (
	defBatchSize = 1
	batchSize    = 16
)

func NewSimilarService(modelName string) SimilarService {
	return &SimilarServiceImpl{
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient(modelName),
	}
}

type SimilarService interface {
	// BatchGetSimilarScore 批量获取Similar 分数
	BatchGetSimilarScore(ctx context.Context, query string, chunks []string) []float64

	// BatchGetSimilarScoreBySize 批量获取Similar 分数
	BatchGetSimilarScoreBySize(ctx context.Context, query string, chunks []string, innerBatchSize int) []float64
}

type SimilarServiceImpl struct {
	klaraEmbeddingClient rpc.KlaraRpcClient
}

type similarScore struct {
	index int
	score float64
}

func (s *SimilarServiceImpl) BatchGetSimilarScore(ctx context.Context, query string, chunks []string) []float64 {
	return s.BatchGetSimilarScoreBySize(ctx, query, chunks, batchSize)
}

func (s *SimilarServiceImpl) BatchGetSimilarScoreBySize(ctx context.Context, query string, chunks []string, innerBatchSize int) []float64 {
	if innerBatchSize <= 0 {
		innerBatchSize = defBatchSize
	}

	logger := log.WithFields(ctx, map[string]any{
		"func": "BatchGetSimilarScore",
	})
	// 组合 query 和 chunks 一块发起 klara 请求embedding 结果
	batchArr := make([]string, 0)
	batchArr = append(batchArr, query)
	batchArr = append(batchArr, chunks...)

	// 取embedding
	embeddingRes := s.klaraEmbeddingClient.BatchInferEmbeddingBySize(ctx, batchArr, innerBatchSize)
	if len(embeddingRes) != len(batchArr) {
		logger.Errorf(ctx, "embeddingRes len not equal to batchArr len")
		return []float64{}
	}

	// 获取Query Embedding结果
	queryEmbeddingRes := embeddingRes[0]
	// 获取chunks embedding 结果
	chunksEmbeddingRes := embeddingRes[1:]

	doneCh := make(chan int)
	scoresChan := make(chan *similarScore, len(chunks))
	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroupWithTimeout("BatchGetSimilarScore", 1000).SetLimit(8)
	for i, chunkEmbeddingRes := range chunksEmbeddingRes {
		iTmp, chunkEmbeddingResTmp := i, chunkEmbeddingRes
		wg.Go(func() error {
			// 求余弦相似度
			score, err := util2.CosineByDefIgnoreNormalize(queryEmbeddingRes, chunkEmbeddingResTmp, 0)
			if err != nil {
				logger.Warnf(ctx, "CosineByDefIgnoreNormalize error: %v", err)
				return err
			}

			item := &similarScore{index: iTmp, score: score}
			// 使用select来判断channel是否关闭
			select {
			case <-doneCh:
				logger.Warnf(ctx, "Stop sending, channel is closed => %+v", item)
				return nil
			default:
				scoresChan <- item
			}
			return nil
		})
	}
	// 等待所有 goroutine 完成
	go func() {
		wgErr := wg.Wait()
		if wgErr != nil {
			logger.Warnf(ctx, "Cosine Chan Wait Err => %v", wgErr)
		}
		close(doneCh)
		close(scoresChan)
	}()

	similarScoreArr := make([]*similarScore, 0)
	for tmp := range scoresChan {
		similarScoreArr = append(similarScoreArr, tmp)
	}

	// index 正序排序
	sort.Slice(similarScoreArr, func(i, j int) bool {
		return similarScoreArr[i].index < similarScoreArr[j].index
	})

	return lo.Map(similarScoreArr, func(item *similarScore, _ int) float64 {
		return item.score
	})
}
