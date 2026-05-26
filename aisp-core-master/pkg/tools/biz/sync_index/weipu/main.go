package main

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/tools/biz/sync_index"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/cespare/xxhash/v2"
)

// go run pkg/tools/rpc/qu/main.go
// 从 hdfs 中读取龙源数据，实时流同步到 rum 和 rucene 索引中
func main() {
	ctx := context.Background()
	syncIndex(ctx, "/user/tc_ai/spider/weipu_pdf_0/")
	syncIndex(ctx, "/user/tc_ai/spider/weipu_pdf_1/")
	log.Infof(ctx, "done")
}

func syncIndex(ctx context.Context, dirName string) {
	dirPathSuffs := strings.Split(dirName, "/")
	dirPathSuff := dirPathSuffs[len(dirPathSuffs)-2]

	fileNames, _ := impl.TcAiHdfsDaoImpl.ListDirFileNames(ctx, dirName)

	count := 0

	// 限制并发数
	semaphore := make(chan struct{}, 5)

	sg := safe_group.NewGroup("BatchSyncIndex")
	for _, fileName := range fileNames {
		fileName := fileName
		sg.Go(func() error {
			// 通过channel控制并发数
			semaphore <- struct{}{}
			defer func() { <-semaphore }()

			count++
			if count%100 == 0 {
				percentage := float64(count) / float64(len(fileNames))
				statsd.Gauge(fmt.Sprintf(env.GetAPPName()+".index_sync.%s.%s", "weipu", dirPathSuff), percentage)
				log.Infof(ctx, "%s done sync : %d", dirPathSuff, count)
			}

			impl.TcAiHdfsDaoImpl.DownloadFile(ctx, fmt.Sprintf("%s%s", dirName, fileName), fileName)

			url := "http://localhost:8787/pdf"
			requestBody := map[string]interface{}{
				"file_name": fileName,
			}
			responseBody := sync_index.DoPost(ctx, url, requestBody)
			content, ok := responseBody.(string)
			if !ok {
				log.Errorf(ctx, "response is not string")
				return nil
			}

			pdfRegex := regexp.MustCompile(`\.pdf$`)
			title := pdfRegex.ReplaceAllString(fileName, "")

			if content == "" {
				log.Errorf(ctx, "content is empty")
			}

			// 正则表达式匹配第一行是否符合“第x卷第x期”的模式
			re := regexp.MustCompile(`^第(\d+)卷第(\d+)期`)
			// 使用re.FindString检查第一行是否匹配
			magazineIssue := re.FindString(strings.TrimSpace(content))

			if magazineIssue == "" {
				// 正则表达式匹配第一行是否符合“第x卷第x期”的模式
				re = regexp.MustCompile(`^(\d+)年第(\d+)期`)
				// 使用re.FindString检查第一行是否匹配
				magazineIssue = re.FindString(strings.TrimSpace(content))
			}

			doc := sync_index.DocSchema{
				Id:            int64(xxhash.Sum64String(title)),
				DocId:         int64(xxhash.Sum64String(title)),
				Title:         title,
				Content:       content,
				MagazineName:  "",
				MagazineIssue: magazineIssue,
				LinkUrl:       "",
			}

			sync_index.RemoveFile(fileName)

			// 同步 rucene 和 rum 索引
			sync_index.SyncRucene(ctx, doc, model.WeiPuPath, model.WeiPuIndex)
			sync_index.SyncRum(ctx, doc, macro.WeiPuTitleRumTable, macro.WeiPuContentRumTable, macro.WeiPuTitleAndContentRumTable)

			return nil
		})
	}

	_ = sg.Wait()
}
