package sync_index

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type DocSchema struct {
	Id            int64
	DocId         int64
	Title         string
	Content       string
	MagazineName  string
	MagazineIssue string
	LinkUrl       string
	Abstract      string
	AuthorName    []string
	Subject       string
}

func SyncRum(ctx context.Context, doc DocSchema, titleTable string, contentTable string, titleAndContentTable string) bool {
	extraField := map[string]interface{}{
		macro.ScienceKBFieldName:        doc.Title,
		macro.ScienceKBRawFieldName:     doc.Content,
		macro.ScienceKBUrlFieldName:     doc.LinkUrl,
		macro.ScienceKBDocIdFieldName:   cast.ToString(doc.DocId),
		macro.ScienceKBSourceFieldName:  doc.MagazineName,
		macro.ScienceKBPublishFieldName: doc.MagazineIssue,
	}

	toEmbTitle := doc.Title
	titleEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbTitle})
	if len(titleEmbeddings) == 1 {
		titleIndexIsOk := rpcImpl.DefaultFloat32RumClientImpl.RumUpsert(ctx, titleTable, doc.Id, titleEmbeddings[0], "", extraField)
		if !titleIndexIsOk {
			log.Errorf(ctx, "rum insert %s id:%d err", titleTable, doc.Id)
		}
	}

	toEmbContent := util.UnicodeSubstr(doc.Content, 0, 512)
	contentEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbContent})
	if len(contentEmbeddings) == 1 {
		contentIndexIsOk := rpcImpl.DefaultFloat32RumClientImpl.RumUpsert(ctx, contentTable, doc.Id, contentEmbeddings[0], "", extraField)
		if !contentIndexIsOk {
			log.Errorf(ctx, "rum insert %s id:%d err", contentTable, doc.Id)
		}
	}

	toEmbTitleAndContent := fmt.Sprintf("%s\n%s", doc.Title, toEmbContent)
	titleAndContentEmbeddings := rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbTitleAndContent})
	if len(titleAndContentEmbeddings) == 1 {
		titleAndContentIndexIsOk := rpcImpl.DefaultFloat32RumClientImpl.RumUpsert(ctx, titleAndContentTable, doc.Id, titleAndContentEmbeddings[0], "", extraField)
		if !titleAndContentIndexIsOk {
			log.Errorf(ctx, "rum insert %s id:%d err", titleAndContentTable, doc.Id)
		}
	}

	return true
}

var mu sync.Mutex // 创建互斥锁

type RumIdxType int

const (
	RumIdxTypeTitle           RumIdxType = 1
	RumIdxTypeContent         RumIdxType = 2
	RumIdxTypeTitleAndContent RumIdxType = 3
)

func (r RumIdxType) String() string {
	switch r {
	case RumIdxTypeTitle:
		return "title"
	case RumIdxTypeContent:
		return "content"
	case RumIdxTypeTitleAndContent:
		return "title_and_content"
	default:
		return ""
	}
}

func WriteRumFile(ctx context.Context, doc DocSchema, writer *bufio.Writer, rumIdxType RumIdxType) bool {
	var embeddings [][]float32
	switch rumIdxType {
	case RumIdxTypeTitle:
		toEmbTitle := doc.Title
		embeddings = rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbTitle})
	case RumIdxTypeContent:
		toEmbContent := util.UnicodeSubstr(doc.Content, 0, 512)
		embeddings = rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbContent})
	case RumIdxTypeTitleAndContent:
		toEmbTitleAndContent := fmt.Sprintf("%s\n%s", doc.Title, util.UnicodeSubstr(doc.Content, 0, 512))
		embeddings = rpcImpl.GetBgeEmbeddingClient("ensemble_offline").BatchInferEmbedding(ctx, []string{toEmbTitleAndContent})
	default:
		log.Errorf(ctx, "illegal rumIdxType:%v", rumIdxType)
		return false
	}

	if len(embeddings) == 1 {
		embedding := strings.Join(lo.Map(embeddings[0], func(item float32, _ int) string {
			return util.Float64String(float64(item))
		}), ",")
		// id, hash, status, created_at, updated_at, raw, embedding, title, url, doc_id, source, publish_time
		line := fmt.Sprintf("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%d\t%s\t%s", doc.Id, doc.Id, 1, time.Now().Unix(), time.Now().Unix(), strings.ReplaceAll(doc.Content, "\n", "\\n"), embedding, doc.Title, doc.LinkUrl, doc.Id, "", "")

		mu.Lock() // 锁定互斥锁
		_, err := writer.WriteString(line + "\n")
		mu.Unlock()
		if err != nil {
			log.Errorf(ctx, "rum write rumIdxType:%s id:%d err:%v", rumIdxType, doc.Id, err)
		}
		return err == nil
	}
	return false
}

func SyncRucene(ctx context.Context, doc DocSchema, rucenePath string, ruceneIndex string) bool {
	// title + content 进行切词
	text := fmt.Sprintf("%s\n%s\n%s", doc.Title, doc.Abstract, doc.Content)

	ruceneDoc := &model.ArxivRucene{
		Id:      cast.ToString(doc.Id),
		Title:   doc.Title,
		Url:     doc.LinkUrl,
		Content: doc.Content,
		ContentSeg: model.SegmentInfo{
			Words: getSegment(ctx, util.UnicodeSubstr(text, 0, 13000)),
			Raw:   doc.Content,
			Store: true,
		},
		PublishTime: doc.MagazineIssue,
		Author:      doc.AuthorName,
		Subject:     doc.Subject,
		Abstract:    doc.Abstract,
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	err := rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, rucenePath, ruceneIndex, ruceneDoc, "")

	if err != nil {
		log.Errorf(ctx, "rucene insert %s id:%d err:%v", ruceneIndex, doc.Id, err)
	}

	return err == nil
}

func getSegment(ctx context.Context, text string) []*model.Word {
	var result []*model.Word

	response := rpcImpl.DefaultSegmentImpl.Segment(ctx, text, "Common", true, true, true)
	if response == nil {
		return result
	}

	for _, item := range response.Words {
		if item.GrainType == 1 {
			result = append(result, &model.Word{
				Value:  item.Word,
				Begin:  item.PositionBegin,
				Length: item.Length,
			})
		}
	}

	return result
}

func DoPost(ctx context.Context, url string, requestBody map[string]interface{}) interface{} {
	// 将数据编码为JSON格式
	jsonData, err := json.Marshal(requestBody)
	if err != nil {
		fmt.Println("Error marshalling data:", err)
		return ""
	}

	// 创建请求
	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		fmt.Println("Error creating request:", err)
		return ""
	}

	// 设置请求头，表明发送的是JSON数据
	req.Header.Set("Content-Type", "application/json")

	// 发送请求
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Println("Error sending request:", err)
		return ""
	}
	defer resp.Body.Close()

	// 检查响应状态码
	if resp.StatusCode != http.StatusOK {
		fmt.Printf("Server returned non-200 status: %d\n", resp.StatusCode)
		return ""
	}

	// 读取响应体
	respBody, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		fmt.Println("Error reading response body:", err)
		return ""
	}

	// 解析响应体为map
	var responseMap map[string]interface{}
	err = json.Unmarshal(respBody, &responseMap)
	if err != nil {
		fmt.Println("Error unmarshalling response body:", err)
		return ""
	}

	return responseMap["response"]
}

// LoadDataInPath HDFS 文件加载数据到 Hive 表
func LoadDataInPath(ctx context.Context, sourcePath string, tableName string) {
	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()
	sql := fmt.Sprintf("LOAD DATA INPATH '%s' OVERWRITE INTO TABLE %s PARTITION(p_date='2024-08-20')", sourcePath, tableName)

	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		log.Errorf(ctx, "Err:%v", cursor.Err)
		return
	}
	cursor.Close()
}

// InsertOverwriteData Rum 原始 Hive 表中插入一条数据
func InsertOverwriteData(ctx context.Context) {
	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()
	sql := "INSERT overwrite TABLE aisp.ai_prefab_word_v3_1024d partition (p_date = '2024-08-08')\nselect\n  `id`,\n  `hash`,\n  `status`,\n  `created_at`,\n  `updated_at`,\n  '' as raw,\n  `embedding`,\n  0 as query_type\nfrom\n  aisp.wiki_zh_title_bge_emb_1024d\nwhere\n  p_date='2024-08-02'\nlimit 1\n"

	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		log.Errorf(ctx, "Err:%v", cursor.Err)
		return
	}
	cursor.Close()
}

func RemoveFile(fileName string) {
	err := os.Remove(fileName)
	if err != nil {
		// 如果文件不存在或删除失败，则打印错误信息
		fmt.Printf("删除文件 %s 失败: %v\n", fileName, err)
	}
}
