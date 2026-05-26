package main

import (
	"context"
	"flag"
	"fmt"
	"sync"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

var operationBaseManagementService = operation_base.DefaultOperationBaseManagementService

var bgeEmbeddingClient = impl.GetBgeEmbeddingClient("ensemble")

var rumClient = impl.DefaultFloat32RumClientImpl

// 把faq表中的的存量数据刷到rum中
func main() {
	var rumTableName string
	flag.StringVar(&rumTableName, "rum_table_name", "faq_bge_1024d", "rum_table_name")
	flag.Parse()

	pageSize := 10000
	ctx := context.Background()
	params := &model.FilterParams{
		Page:      0,
		PageSize:  pageSize,
		Status:    model.OperationBaseStatusOnline,
		MatchType: []conf.FaqMatchType{conf.FaqMatchTypeEmbeddingSimilarity},
	}

	allFaqBases, _, err := operationBaseManagementService.ListFaqBase(ctx, params)
	if err != nil {
		panic(err)
	}

	faqBaseMap := map[int64]*model.FaqBase{}
	for _, faqBase := range allFaqBases {
		faqBaseMap[faqBase.Id] = faqBase
	}

	allIds := lo.Map(allFaqBases, func(faqBase *model.FaqBase, _ int) int64 {
		return faqBase.Id
	})

	resMap := map[int64]bool{}

	mapMutex := sync.RWMutex{}
	safe_group.BatchGet(zrecUtil.Min(100, pageSize), allIds, func(idsInter interface{}) interface{} {

		ids := idsInter.([]int64)
		faqBases := []*model.FaqBase{}
		for _, id := range ids {
			faqBases = append(faqBases, faqBaseMap[id])
		}

		res := map[int64]bool{}

		queries := lo.Map(faqBases, func(item *model.FaqBase, _ int) string {
			return item.Question
		})

		embeddings := bgeEmbeddingClient.BatchInferEmbedding(ctx, queries)
		wg := safe_group.NewGroup("group")

		for i, faqBase := range faqBases {
			wg.Go(func(tmpEmbedding []float32, tmpFaqBase *model.FaqBase) safe_group.FutureFunc {
				return func() error {
					fmt.Printf("id=%d, emb=%v\n", tmpFaqBase.Id, tmpEmbedding[0:5])
					result := rumClient.RumUpsert(ctx, rumTableName, tmpFaqBase.Id, tmpEmbedding, "", nil)
					mapMutex.Lock()
					res[tmpFaqBase.Id] = result
					mapMutex.Unlock()
					return nil
				}
			}(embeddings[i], faqBase))
		}

		err := wg.Wait()
		if err != nil {
			panic(err)
		}
		return res

	}, &resMap)

	result := lo.Filter(lo.Entries(resMap), func(item lo.Entry[int64, bool], index int) bool {
		return item.Value == false
	})

	fmt.Printf("result: %v\n", lo.Map(result, func(item lo.Entry[int64, bool], _ int) int64 {
		return item.Key
	}))
}
