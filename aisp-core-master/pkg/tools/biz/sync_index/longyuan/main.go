package sync_index

import (
	"context"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/tools/biz/sync_index"
	"github.com/cespare/xxhash/v2"
)

// go run pkg/tools/biz/sync_index/main.go
// 从 hive 中读取龙源数据，实时流同步到 rum 和 rucene 索引中
const longYuanSQL = "select id,title,content,magazine_name,magazine_issue,url from ads_vip.ads_vip_content_ai_search_magazine_contents_app_pt where p_date='2024-07-16'"

func readHiveAndSyncIndex(ctx context.Context, hiveClient *resource.HiveClient) {
	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, longYuanSQL)

	if cursor.Err != nil {
		log.Errorf(ctx, "Err:%v", cursor.Err)
		return
	}
	log.Infof(ctx, "start sync job")

	syncCount := 0
	syncRuceneSuccCount := 0
	syncRumSuccCount := 0
	for cursor.HasMore(ctx) {
		syncCount++
		if syncCount%100 == 0 {
			log.Infof(ctx, "sync index count:%d", syncCount)
		}

		longYuanDoc := sync_index.DocSchema{}
		cursor.FetchOne(ctx, &longYuanDoc.DocId, &longYuanDoc.Title, &longYuanDoc.Content, &longYuanDoc.MagazineName, &longYuanDoc.MagazineIssue, &longYuanDoc.LinkUrl)

		// 过滤不合法 url
		if !strings.HasPrefix(longYuanDoc.LinkUrl, "http") {
			continue
		}

		// 调用 http 服务进行 html 转 markdown
		requestBody := map[string]interface{}{
			"content": longYuanDoc.Content,
		}
		responseBody := sync_index.DoPost(ctx, "http://localhost:8787", requestBody)
		filteredContent, ok := responseBody.(string)
		if !ok || len(filteredContent) == 0 {
			log.Errorf(ctx, "response is not string or empty:%v", responseBody)
			continue
		}

		longYuanDoc.Content = filteredContent
		longYuanDoc.Id = int64(xxhash.Sum64String(longYuanDoc.LinkUrl))

		// 同步 rucene 和 rum 索引
		ruceneSucc := sync_index.SyncRucene(ctx, longYuanDoc, model.LongYuanPath, model.LongYuanIndex)
		rumSucc := sync_index.SyncRum(ctx, longYuanDoc, macro.LongYuanTitleRumTable, macro.LongYuanContentRumTable, macro.LongYuanTitleAndContentRumTable)

		if ruceneSucc {
			syncRuceneSuccCount++
		}
		if rumSucc {
			syncRumSuccCount++
		}
	}

	log.Infof(ctx, "sync index done:%d, rucene succ:%d, rum succ:%d", syncCount, syncRuceneSuccCount, syncRumSuccCount)
}

func main() {
	ctx := context.Background()

	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()

	readHiveAndSyncIndex(ctx, hiveClient)
}
