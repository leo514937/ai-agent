package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/tools/biz/sync_index"
	"github.com/spf13/cast"
)

// go run pkg/tools/biz/sync_index/wiki/main.go
// 从 hdfs 中读取龙源数据，写文件同步到 rum 和 rucene 索引中
func main() {
	ctx := context.Background()
	embType := flag.Int("emb_type", 1, "RumIdxType类型，1标题，2正文，3标题+正文")
	rumTableName := flag.String("table", "aisp.wiki_zh_title_bge_emb_1024d", "rum表名")
	flag.Parse()

	rumIdxType := sync_index.RumIdxType(*embType)
	dirName := "/user/tc_agi/liuyingshuai/wiki/wiki_en_clean/"

	fileNames, _ := impl.TcAgiHdfsDaoImpl.ListDirFileNames(ctx, dirName)
	for _, fileName := range fileNames {
		syncIndex(ctx, dirName, fileName, false, rumIdxType)
	}

	sync_index.LoadDataInPath(ctx, fmt.Sprintf("/user/tc_ai/wangran/wiki/wiki_en_clean/%s/*", rumIdxType.String()), *rumTableName)

	log.Infof(ctx, "done")
}

type jsonSchema struct {
	Id    string `json:"id"`
	Text  string `json:"text"`
	Title string `json:"title"`
}

func syncIndex(ctx context.Context, inputDirName string, inputFileName string, isChiness bool, rumIdxType sync_index.RumIdxType) {
	oriFileName := inputFileName[0:strings.LastIndex(inputFileName, ".")]

	// 下载文件到本地
	impl.TcAgiHdfsDaoImpl.DownloadFile(ctx, fmt.Sprintf("%s%s", inputDirName, inputFileName), inputFileName)
	inputFile, err := os.Open(inputFileName)
	if err != nil {
		fmt.Println("Error opening file:", err)
		return
	}

	// 语种标记
	var languageTag string
	if isChiness {
		languageTag = "zh"
	} else {
		languageTag = "en"
	}

	// 创建 rum 导出文件
	nowTime := util2.FormatTime2yyyyMMddHHmmss(time.Now())
	rumFileName := fmt.Sprintf("%s_wiki_%s_rum_%s_%s", languageTag, oriFileName, rumIdxType.String(), nowTime)
	rumOutputFile, err := os.OpenFile(rumFileName, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		fmt.Println("Error opening file:", err)
		return
	}
	defer rumOutputFile.Close() // 确保在函数结束时关闭文件
	// rum 导出文件 writer
	writer := bufio.NewWriter(rumOutputFile)

	// 按行读源文件
	scanner := bufio.NewScanner(inputFile)
	// 设置最大 token 大小为 1MB，总文件最大 1GB
	scanner.Buffer(make([]byte, 1<<20), 1<<30)
	// 最大并发数为 5
	semaphore := make(chan struct{}, 5)
	var wg sync.WaitGroup

	count := 0
	for scanner.Scan() {
		count++
		line := scanner.Text() // 获取
		// 检查行的长度是否超过了1MB
		if len(line) > 1<<20 {
			fmt.Println("Skipping line that is too long")
			continue
		}

		if count%1000 == 0 {
			log.Infof(ctx, "%s %s : %d", rumIdxType.String(), inputFileName, count)
		}

		semaphore <- struct{}{}
		// 增加等待组计数
		wg.Add(1)

		go func(line string, count int) {
			defer wg.Done()
			// 处理完成后，从信号通道接收一个空结构体，以允许其他goroutine进入
			defer func() { <-semaphore }()

			var url, prefix string
			if isChiness {
				url = "http://localhost:8989/wiki/chinese"
				prefix = "zh"
			} else {
				url = "http://localhost:8989/wiki/english"
				prefix = "en"
			}

			// 解析 json，结果为 item
			requestBody := map[string]interface{}{
				"content": line,
			}
			responseBody := sync_index.DoPost(ctx, url, requestBody)
			content, ok := responseBody.(map[string]interface{})
			if !ok {
				log.Errorf(ctx, "response is not map")
				return
			}
			item, err := util2.MapToStruct[jsonSchema](content)
			if err != nil {
				log.Errorf(ctx, "Error:%v", err)
				return
			}

			id := item.Id
			title := item.Title
			docUrl := fmt.Sprintf("https://%s.wikipedia.org/w/index.php?curid=%s", prefix, id)
			text := strings.ReplaceAll(strings.ReplaceAll(item.Text, "\t", ""), "\n", "")

			if text == "" {
				return
			}

			doc := sync_index.DocSchema{
				Content:       text,
				DocId:         cast.ToInt64(id),
				Id:            cast.ToInt64(id),
				LinkUrl:       docUrl,
				MagazineIssue: "",
				MagazineName:  "",
				Title:         title,
			}

			sync_index.WriteRumFile(ctx, doc, writer, rumIdxType)

		}(line, count)
	}
	// 等待所有goroutine完成
	wg.Wait()
	inputFile.Close()
	writer.Flush()
	sync_index.RemoveFile(inputFileName)

	impl.TcAiHdfsDaoImpl.UploadFile(ctx, rumFileName, fmt.Sprintf("/user/tc_ai/wangran/wiki/wiki_%s_clean/%s/%s", languageTag, rumIdxType.String(), rumFileName))

	log.Infof(ctx, "count:%d", count)
}
