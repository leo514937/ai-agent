package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

func main() {
	//saveToRedis()
	// printToRedis()
	dumpWord()
}

func dumpWord() {
	dao := daoImpl.DefaultWordMapperDAO
	words, _ := dao.GetValidWordByType(context.Background(), []proto.QueryType{proto.QueryType_PREFAB_WORD_QUESTION}, 5000)
	questionWords, _ := dao.GetValidWordByType(context.Background(), []proto.QueryType{proto.QueryType_PREFAB_WORD_HOT_QUESTION}, 5000)
	words = append(words, questionWords...)

	file, _ := os.Create("ids.txt")
	for _, mapper := range words {
		file.WriteString(mapper.Word)
		file.WriteString("\n")
	}
}

func printToRedis() {
	ctx := context.Background()
	//klaraEmbeddingClient := rpcImpl.BgeEmbeddingClient
	//rumClient := rpcImpl.DefaultFloat32RumClientImpl
	//rumCache := rum_cache.NewRumCache()
	redisDao := daoImpl.NewPrefabWordV2Dao()
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeV2",
		"func":  "Print",
	})

	res := redisDao.GetRandomPrefabQueryV2ByRedis(ctx, 50, proto.QueryType_PREFAB_WORD_QUESTION)
	for _, v := range res {
		logger.Infof(ctx, util.GetJSONIgnoreError(v))
	}
}

func saveToRedis() {
	ctx := context.Background()
	contentCoreRpc := impl.DefaultContentCoreRPCImpl
	klaraEmbeddingClient := impl.GetBgeEmbeddingClient("ensemble")
	rumClient := impl.DefaultFloat32RumClientImpl
	wordWrapperService := word.NewWordMapperService()
	//rumCache := rum_cache.NewRumCache()
	redisDao := daoImpl.NewPrefabWordV2Dao()
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeV2",
		"func":  "Process",
	})

	filePath := "ids.txt"
	file, err := os.Open(filePath)
	if err != nil {
		fmt.Println("Error opening file:", err)
		return
	}
	defer file.Close()

	ids := make([]int64, 0)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		ids = append(ids, cast.ToInt64(line))
	}

	if err := scanner.Err(); err != nil {
		fmt.Println("Error reading file:", err)
	}

	contents := make([]model.Content, 0)
	for _, id := range ids {
		newContent := model.NewContentWithContentType(id, content_core_thrift.ContentTypeAIPredefinedWord)
		contents = append(contents, newContent)
	}

	// 查询内容 url token
	contentResultMap := contentCoreRpc.BatchGetContent(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentBizExt)

	for k, contentInfo := range contentResultMap {
		docId := k.ContentID

		// 计算 embedding
		embeddings := klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{contentInfo.GetTitle()})
		// 检查 embedding是否合规
		embeddingIsOk := util.CheckTwoDimEmbedding(embeddings)
		if !embeddingIsOk {
			errorMsg := fmt.Sprintf("embedding is not Ok  docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
			logger.Error(ctx, errorMsg)
			continue
		}

		bizExt, bizExtErr := model.ParseAIPredefinedWordBizExt(contentInfo.GetBizExt())
		if bizExtErr != nil {
			errorMsg := fmt.Sprintf("content info bizExt is not Unmarshal docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
			logger.Error(ctx, errorMsg)
			continue
		}

		prefabWord := &model.PrefabWord{
			DocId:             docId,
			DocType:           model.GetDocType(contentInfo.GetContentType()),
			ContentType:       contentInfo.GetContentType(),
			QueryType:         proto.QueryType_PREFAB_WORD_QUESTION,
			SourceChannel:     bizExt.SourceChannel,
			SourceQuestion:    bizExt.SourceQuestion,
			AiRewriteQuestion: contentInfo.GetTitle(),
		}
		jsonString, jsonStringErr := prefabWord.ToJsonString()
		if jsonStringErr != nil {
			errorMsg := fmt.Sprintf("PrefabWord toJson error  docId: %d, contentType:%s, contentTitle:%s, errorMsg:%v",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle(), jsonStringErr)
			logger.Error(ctx, errorMsg)
			continue
		}

		logger.Infof(ctx, "PrefabWord toJson success  docId: %s", jsonString)

		// 更新词数据到MySQL
		_, saveMySQLErr := wordWrapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
			WordType: int32(proto.QueryType_PREFAB_WORD_QUESTION),
			Word:     contentInfo.GetTitle(),
			SourceId: cast.ToString(docId),
		})
		if saveMySQLErr != nil {
			logger.Error(ctx, saveMySQLErr)
		} else {
			logger.Infof(ctx, "Save PrefabWordToRum Success(MySQL) docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
		}

		// 更新到Redis
		bizExtErr = redisDao.SavePrefabWordV2ToRedisSet(ctx, proto.QueryType_PREFAB_WORD_QUESTION, prefabWord)
		if bizExtErr != nil {
			logger.Error(ctx, bizExtErr)
		} else {
			logger.Infof(ctx, "Save PrefabWordToRum Success(Redis) docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
		}
		// 更新 rum
		actionRes := rumClient.RumUpsert(ctx, macro.AiPrefabWordV2RumTable, docId, embeddings[0], "", map[string]interface{}{
			macro.QuestionRewriteHashFieldName:   docId,
			macro.QuestionRewriteStatusFieldName: 1,
			macro.QuestionRewriteRawFieldName:    jsonString,
		})
		if !actionRes {
			logger.Errorf(ctx, "Save PrefabWordToRum Err docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
		} else {
			logger.Infof(ctx, "Save PrefabWordToRum Success(Rum) docId: %d, contentType:%s, contentTitle:%s",
				docId, contentInfo.GetContentType(), contentInfo.GetTitle())
		}
		time.Sleep(50 * time.Millisecond)
	}
}
