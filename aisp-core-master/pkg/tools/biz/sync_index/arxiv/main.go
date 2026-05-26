package main

import (
	"bufio"
	"compress/zlib"
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/tools/biz/sync_index"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/cespare/xxhash/v2"
	"github.com/samber/lo"
)

// go run pkg/tools/biz/sync_index/arxiv/main.go
// nohup go run pkg/tools/biz/sync_index/arxiv/main.go >arxiv.log 2>&1 &
// 早期的 arxiv pdf 读取和构建脚本
func main() {
	ctx := context.Background()

	recordCount := 0
	fileCount := 30
	var outputFileTitle *os.File
	var deflateWriterTitle *zlib.Writer
	var writerTitle *bufio.Writer

	var outputFileAbstract *os.File
	var deflateWriterAbstract *zlib.Writer
	var writerAbstract *bufio.Writer

	var outputFileTotal *os.File
	var deflateWriterTotal *zlib.Writer
	var writerTotal *bufio.Writer

	// 初始打开第一个文件
	recordCount, outputFileTitle, deflateWriterTitle, writerTitle, err := openNewFile(1, outputFileTitle, deflateWriterTitle, writerTitle, fileCount, recordCount)
	if err != nil {
		fmt.Printf("Error creating output file: %v\n", err)
		return
	}
	// 初始打开第一个文件
	recordCount, outputFileAbstract, deflateWriterAbstract, writerAbstract, err = openNewFile(2, outputFileAbstract, deflateWriterAbstract, writerAbstract, fileCount, recordCount)
	if err != nil {
		fmt.Printf("Error creating output file: %v\n", err)
		return
	}
	// 初始打开第一个文件
	recordCount, outputFileTotal, deflateWriterTotal, writerTotal, err = openNewFile(3, outputFileTotal, deflateWriterTotal, writerTotal, fileCount, recordCount)
	if err != nil {
		fmt.Printf("Error creating output file: %v\n", err)
		return
	}

	// 落本地文件
	syncIndex(ctx,
		outputFileTitle, deflateWriterTitle, writerTitle,
		outputFileAbstract, deflateWriterAbstract, writerAbstract,
		outputFileTotal, deflateWriterTotal, writerTotal,
		fileCount, recordCount)

	writerTitle.Flush()
	deflateWriterTitle.Close()
	outputFileTitle.Close()

	writerAbstract.Flush()
	deflateWriterAbstract.Close()
	outputFileAbstract.Close()

	writerTotal.Flush()
	deflateWriterTotal.Close()
	outputFileTotal.Close()

	//本地 to hdfs
	impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(1, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(1), getOutputFileName(1, fileCount)))
	impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(2, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(2), getOutputFileName(2, fileCount)))
	impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(3, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(3), getOutputFileName(3, fileCount)))

	log.Infof(ctx, "done")

	sync_index.LoadDataInPath(ctx, "/user/tc_ai/wangran/arxiv/pdf/content/*", "aisp.arxiv_abstract_bge_emb_1024d")
	sync_index.LoadDataInPath(ctx, "/user/tc_ai/wangran/arxiv/pdf/title/*", "aisp.arxiv_title_bge_emb_1024d")
	sync_index.LoadDataInPath(ctx, "/user/tc_ai/wangran/arxiv/pdf/titlecontent/*", "aisp.arxiv_bge_emb_1024d")

}

func getTypeDesc(embType int) string {
	switch embType {
	case 1:
		return "title"
	case 2:
		return "content"
	case 3:
		return "titlecontent"
	}
	panic("unknown embType")
}

var openNewFile = func(embType int, outputFile *os.File, deflateWriter *zlib.Writer, writer *bufio.Writer, fileCount int, recordCount int) (int, *os.File, *zlib.Writer, *bufio.Writer, error) {
	if outputFile != nil {
		writer.Flush()
		deflateWriter.Close()
		outputFile.Close()
	}

	outputFile, err := os.Create(getOutputFileName(embType, fileCount))
	if err != nil {
		return recordCount, outputFile, deflateWriter, writer, err
	}
	deflateWriter = zlib.NewWriter(outputFile)
	writer = bufio.NewWriter(deflateWriter)

	recordCount = 0 // 重置计数器
	return recordCount, outputFile, deflateWriter, writer, err
}

var mu sync.Mutex // 创建互斥锁

func getOutputFileName(embType int, fileCount int) string {
	return fmt.Sprintf("%s_output_%d.deflate", getTypeDesc(embType), fileCount)
}
func syncIndex(ctx context.Context,
	outputFileTitle *os.File, deflateWriterTitle *zlib.Writer, writerTitle *bufio.Writer,
	outputFileAbstract *os.File, deflateWriterAbstract *zlib.Writer, writerAbstract *bufio.Writer,
	outputFileTotal *os.File, deflateWriterTotal *zlib.Writer, writerTotal *bufio.Writer,
	fileCount int, recordCount int) (int, int) {

	dirSubNames, _ := impl.TcAgiHdfsDaoImpl.ListDirFileNames(ctx, "/user/tc_agi/njt/datasets/arxiv-pdf-38/arxiv-pdf/arxiv/pdf/")
	for _, dirSubName := range dirSubNames {
		dirName := fmt.Sprintf("/user/tc_agi/njt/datasets/arxiv-pdf-38/arxiv-pdf/arxiv/pdf/%s/", dirSubName)
		fileNames, _ := impl.TcAgiHdfsDaoImpl.ListDirFileNames(ctx, dirName)

		// 过滤一遍 fileName，选出最大版本号的文件
		var avalidFileNames []string
		fileMaxVersion := map[string]int64{}

		for _, fileName := range fileNames {
			subs := strings.Split(fileName, "v")
			if len(subs) != 2 {
				continue
			}
			pdfRegex := regexp.MustCompile(`\.pdf$`)
			version, err := util.String2Int64(pdfRegex.ReplaceAllString(subs[1], ""))
			if err != nil {
				continue
			}
			if maxVersion, exist := fileMaxVersion[subs[0]]; !exist {
				fileMaxVersion[subs[0]] = version
			} else {
				if version > maxVersion {
					fileMaxVersion[subs[0]] = version
				}
			}
		}

		for fileName, version := range fileMaxVersion {
			avalidFileNames = append(avalidFileNames, fmt.Sprintf("%sv%d.pdf", fileName, version))
		}

		count := 0

		// 限制并发数
		semaphore := make(chan struct{}, 5)

		// 开始构建索引
		sg := safe_group.NewGroup("BatchSyncIndex")
		for _, fileName := range avalidFileNames {
			fileName := fileName
			sg.Go(func() error {
				// 通过channel控制并发数
				semaphore <- struct{}{}
				defer func() {
					<-semaphore
					sync_index.RemoveFile(fileName)
				}()

				count++
				if count%100 == 0 {
					log.Infof(ctx, "%s done:%d", strings.Split(dirName, "/")[9], count)
				}

				impl.TcAgiHdfsDaoImpl.DownloadFile(ctx, fmt.Sprintf("%s%s", dirName, fileName), fileName)

				// 正文
				contentUrl := "http://localhost:8787/pdf"
				requestBody := map[string]interface{}{
					"file_name": fileName,
				}
				responseBody := sync_index.DoPost(ctx, contentUrl, requestBody)
				content, ok := responseBody.(string)
				if !ok {
					log.Errorf(ctx, "response is not string")
					return nil
				}

				// meta
				pdfRegex := regexp.MustCompile(`v\d+\.pdf$`)
				docUrl := fmt.Sprintf("https://arxiv.org/abs/%s", pdfRegex.ReplaceAllString(fileName, ""))
				meta := getMetaFromUrl(context.Background(), docUrl)
				if meta == nil || meta.Title == "" || meta.Abstract == "" {
					log.Errorf(ctx, "meta is nil or title abstract is empty")
					return nil
				}

				id := int64(xxhash.Sum64String(docUrl))

				// 标题
				titleEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(context.Background(), []string{meta.Title})
				if len(titleEmbeddings) != 1 {
					return nil
				}
				titleEmbedding := strings.Join(lo.Map(titleEmbeddings[0], func(item float32, _ int) string {
					return util.Float64String(float64(item))
				}), ",")
				// 摘要
				abstractEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(context.Background(), []string{util.UnicodeSubstr(meta.Abstract, 0, 512)})
				if len(abstractEmbeddings) != 1 {
					return nil
				}
				abstractEmbedding := strings.Join(lo.Map(abstractEmbeddings[0], func(item float32, _ int) string {
					return util.Float64String(float64(item))
				}), ",")
				// 全部
				totalEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(context.Background(), []string{fmt.Sprintf("%s\n%s", meta.Title, util.UnicodeSubstr(meta.Abstract, 0, 512))})
				if len(totalEmbeddings) != 1 {
					return nil
				}
				totalEmbedding := strings.Join(lo.Map(totalEmbeddings[0], func(item float32, _ int) string {
					return util.Float64String(float64(item))
				}), ",")

				// 数据清洗
				content = strings.ReplaceAll(content, "\n", " \\n")
				content = strings.ReplaceAll(content, "\r", " ")
				content = strings.ReplaceAll(content, "\t", " ")
				meta.Abstract = strings.ReplaceAll(meta.Abstract, "\n", " \\n")
				meta.Abstract = strings.ReplaceAll(meta.Abstract, "\r", " ")
				meta.Abstract = strings.ReplaceAll(meta.Abstract, "\t", " ")
				meta.Abstract = strings.ReplaceAll(meta.Abstract, ",", "，")
				meta.Title = strings.ReplaceAll(meta.Title, "\t", " ")

				// id, hash, status, created_at, updated_at, raw, embedding, title, url, author, subject, abstract, publish_time
				lineTitle := fmt.Sprintf("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s", id, id, 1, time.Now().Unix(), time.Now().Unix(), content, titleEmbedding, meta.Title, meta.Url, strings.Join(meta.Author, ","), meta.Subject, meta.Abstract, "")
				lineAbstract := fmt.Sprintf("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s", id, id, 1, time.Now().Unix(), time.Now().Unix(), content, abstractEmbedding, meta.Title, meta.Url, strings.Join(meta.Author, ","), meta.Subject, meta.Abstract, "")
				lineTotal := fmt.Sprintf("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s", id, id, 1, time.Now().Unix(), time.Now().Unix(), content, totalEmbedding, meta.Title, meta.Url, strings.Join(meta.Author, ","), meta.Subject, meta.Abstract, "")

				mu.Lock() // 锁定互斥锁
				_, err := writerTitle.WriteString(lineTitle + "\n")
				if err != nil {
					fmt.Printf("Error writing line to output file: %v\n", err)
					return nil
				}
				_, err = writerAbstract.WriteString(lineAbstract + "\n")
				if err != nil {
					fmt.Printf("Error writing line to output file: %v\n", err)
					return nil
				}
				_, err = writerTotal.WriteString(lineTotal + "\n")
				if err != nil {
					fmt.Printf("Error writing line to output file: %v\n", err)
					return nil
				}
				mu.Unlock()

				doc := sync_index.DocSchema{
					Id:            int64(xxhash.Sum64String(meta.Url)),
					Title:         meta.Title,
					Content:       content,
					MagazineIssue: meta.PublishDate,
					LinkUrl:       meta.Url,
					Abstract:      meta.Abstract,
					Subject:       meta.Subject,
					AuthorName:    meta.Author,
				}

				sync_index.SyncRucene(ctx, doc, model.ArxivPath, model.ArxivIndex)

				recordCount++

				// 按1万条记录切一次文件
				mu.Lock() // 锁定互斥锁
				if recordCount >= 10000 {
					impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(1, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(1), getOutputFileName(1, fileCount)))
					impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(2, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(2), getOutputFileName(2, fileCount)))
					impl.TcAiHdfsDaoImpl.UploadFile(ctx, getOutputFileName(3, fileCount), fmt.Sprintf("/user/tc_ai/wangran/arxiv/pdf/%s/%s", getTypeDesc(3), getOutputFileName(3, fileCount)))
					fileCount++

					recordCount, outputFileTitle, deflateWriterTitle, writerTitle, err = openNewFile(1, outputFileTitle, deflateWriterTitle, writerTitle, fileCount, recordCount)
					recordCount, outputFileAbstract, deflateWriterAbstract, writerAbstract, err = openNewFile(2, outputFileAbstract, deflateWriterAbstract, writerAbstract, fileCount, recordCount)
					recordCount, outputFileTotal, deflateWriterTotal, writerTotal, err = openNewFile(3, outputFileTotal, deflateWriterTotal, writerTotal, fileCount, recordCount)

					if err != nil {
						fmt.Printf("Error creating new output file: %v\n", err)
						return nil
					}
				}
				mu.Unlock()
				return nil
			})
		}

		_ = sg.Wait()
	}

	return fileCount, recordCount
}

type docMeta struct {
	Title       string   `json:"title"`
	Abstract    string   `json:"abstract"`
	Author      []string `json:"author"`
	Subject     string   `json:"subject"`
	Url         string   `json:"url"`
	PublishDate string   `json:"publish_date"`
}

func getMetaFromUrl(ctx context.Context, url string) *docMeta {
	// 解析 json，结果为 item
	requestBody := map[string]interface{}{
		"url": url,
	}
	responseBody := sync_index.DoPost(ctx, "http://10.40.138.12:8788/arxiv", requestBody)
	content, ok := responseBody.(map[string]interface{})
	if !ok {
		log.Errorf(ctx, "get meta failed")
		return nil
	}
	item, err := util.MapToStruct[docMeta](content)
	if err != nil {
		log.Errorf(ctx, "Error:%v", err)
		return nil
	}
	item.Url = url
	item.Author = lo.Map(item.Author, func(item string, _ int) string {
		return strings.ReplaceAll(item, ",", "")
	})
	return item
}
