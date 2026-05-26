package main

import (
	"context"
	"flag"
	"fmt"
	"strings"
	"time"

	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/spf13/cast"
)

// go run pkg/tools/rpc/rum/main.go --method=search --table=rec_warmup_cb2cf_v1_128d --k=10 --embedding=-0.021053915843367577,0.17791108787059784...
func search(ctx context.Context, rumClient rpc.RumClient[float64], searchTable string, topK int32, embedding []float64) {
	filterParam := "content_type == Pin and extra in (author_exp_0,author_exp_1)"
	fields := []string{"stage", "author_level"}

	result := rumClient.RumSearch(ctx, searchTable, [][]float64{embedding}, topK, filterParam, fields)

	fmt.Println(fmt.Sprintf("search result:%s", util.GetJSONIgnoreError(result)))
}

// go run pkg/tools/rpc/rum/main.go --method=search_bge --table=ai_zhida_author_bge_1024d --k=10
func bgeSearch(ctx context.Context, rumClient rpc.RumClient[float32], searchTable string, topK int32) {
	embeddings := impl.GetBgeEmbeddingClient("bge-m3-common-for-zhida").BatchInferBgeM3DenseEmb(ctx, []string{"知乎最受欢迎的文章是啥？"})
	if len(embeddings) != 1 {
		return
	}

	result := rumClient.RumSearch(ctx, searchTable, embeddings, topK, "", macro.PersonalKnowledgeBaseDocStoreFields)

	fmt.Println(fmt.Sprintf("search result:%s", util.GetJSONIgnoreError(result)))
}

// go run pkg/tools/rpc/rum/main.go --method=upsert --table=rec_warmup_cb2cf_v1_128d --id=1723890993060016129 --embedding=0.082496001571416855,0.2004924118518829... --extra=content_type:Pin,extra:author_exp_0
func upsert(ctx context.Context, rumClient rpc.RumClient[float64], table string, id int64, embedding []float64, version string, extras string) {
	extraMap := map[string]interface{}{}
	for _, extraFields := range strings.Split(extras, ",") {
		fieldValue := strings.Split(extraFields, ":")
		field, value := fieldValue[0], fieldValue[1]
		extraMap[field] = value
	}
	resp := rumClient.RumUpsert(ctx, table, id, embedding, version, extraMap)
	fmt.Println(fmt.Sprintf("upsert status:%v", resp))
}

// go run pkg/tools/rpc/rum/main.go --method=get --table=rec_warmup_cb2cf_v1_128d --ids=1723890993060016129 --fields=embedding
func get(ctx context.Context, rumClient rpc.RumClient[float64], table string, ids string, fields string) {
	idSlice := strings.Split(ids, ",")
	fieldSlice := strings.Split(fields, ",")
	resp := rumClient.RumGet(ctx, table, idSlice, fieldSlice)
	fmt.Println(fmt.Sprintf("rum get result:%v", util.GetJSONIgnoreError(resp)))
}

// go run pkg/tools/rpc/rum/main.go --method=delete --table=rec_warmup_cb2cf_v1_128d --ids=1723890993060016129
func delete(ctx context.Context, rumClient rpc.RumClient[float64], table string, ids string, version string) {
	idSlice := strings.Split(ids, ",")
	for _, idStr := range idSlice {
		id := cast.ToInt64(idStr)
		resp := rumClient.RumDelete(ctx, table, id, version)
		fmt.Println(fmt.Sprintf("delete id:%d status:%v", id, resp))
		time.Sleep(100 * time.Millisecond)
	}
}

func main() {
	ctx := context.Background()

	table := flag.String("table", "rec_warmup_cb2cf_v1_128d", "table name")
	topK := flag.Int("k", 1, "topk num")
	embedding := flag.String("embedding", "", "source embedding")
	method := flag.String("method", "search", "search/upsert/delete/infos")
	extras := flag.String("extra", "content_type:Answer", "filter fields")
	id := flag.Int64("id", 1723692271638331392, "id")
	ids := flag.String("ids", "1723692271638331392,205509924", "ids")
	version := flag.String("version", "", "version")
	fields := flag.String("fields", "id,embedding", "fields")
	flag.Parse()
	embeddingSlice := util.StringSliceToFloat64(strings.Split(*embedding, ","))

	rumClient64 := impl.NewRumClientImpl[float64](conf.GetRumConfig(), conf.GetRumConfig().TimeoutDefault)
	rumClient32 := impl.NewRumClientImpl[float32](conf.GetRumConfig(), conf.GetRumConfig().TimeoutDefault)

	switch *method {
	case "get":
		get(ctx, rumClient64, *table, *ids, *fields)
	case "search":
		search(ctx, rumClient64, *table, int32(*topK), embeddingSlice)
	case "search_bge":
		bgeSearch(ctx, rumClient32, *table, int32(*topK))
	case "upsert":
		upsert(ctx, rumClient64, *table, *id, embeddingSlice, *version, *extras)
	case "delete":
		delete(ctx, rumClient64, *table, *ids, *version)
	}
}
