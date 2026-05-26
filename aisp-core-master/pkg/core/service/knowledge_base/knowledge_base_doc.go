package knowledge_base

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/cespare/xxhash/v2"
	"github.com/google/uuid"
	"github.com/samber/lo"
)

var chunkConfig = conf.RecallChunkReRankConfig{
	KeySize:        512,
	KeyStep:        256,
	KeyOffset:      0.5,
	ValueSize:      1024,
	TotalSize:      4096,
	ScoreThreshold: 0,
	BoundaryRegex:  rerank_util.BoundaryRegexBySentence,
}

const MaxDocNum = 10000

type KnowledgeBaseDocService interface {
	BatchCreateKnowLedgeBaseDoc(ctx context.Context, docs []*model.KnowledgeBaseDocRaw, knowledgeBase *model.KnowledgeBase, userId string) ([]*model.KnowledgeBaseDocRaw, error)
	FindByDocId(ctx context.Context, docId string, withFileUrl bool) (*model.KnowledgeBaseDoc, error)
	FindByDocNameAndUserId(ctx context.Context, name string, creatorUserId string) ([]*model.KnowledgeBaseDoc, error)
	DeleteByDocId(ctx context.Context, docId string) error
	Update(ctx context.Context, docId string, docName string) error
	GetDocParseTaskState(ctx context.Context, docId string) (model.KnowledgeBaseDocState, error)
	RetrieveKnowledgeBaseDocs(ctx context.Context, query string, topK int, docId string) ([]*model.KnowledgeBaseRetrieveResult, error)
	GetDocDetail(ctx context.Context, docId string) ([]byte, error)
}

type KnowledgebaseServiceDocImpl struct {
	fileManagementDao     dao.FileManagementDAO
	knowledgeBaseDocDAO   dao.KnowledgeBaseDocDAO
	knowledgeBaseChunkDAO dao.KnowledgeBaseChunkDAO
	rumClient             rpc.RumClient[float32]
	klaraEmbeddingClient  rpc.KlaraRpcClient
	aispToolsClient       rpc.AispToolsClient
	docParseTasks         chan *model.KnowledgeBaseDocParseTask

	rumTableName string
}

var (
	DefaultKnowledgebaseDocService = newKnowledgebaseDocService()
)

func newKnowledgebaseDocService() *KnowledgebaseServiceDocImpl {
	service := &KnowledgebaseServiceDocImpl{
		fileManagementDao:     impl.DefaultFileManagementDAO,
		knowledgeBaseDocDAO:   impl.DefaultKnowledgeBaseDocDAO,
		knowledgeBaseChunkDAO: impl.DefaultKnowledgeBaseChunkDAO,
		rumClient:             rpcImpl.DefaultFloat32RumClientImpl,
		klaraEmbeddingClient:  rpcImpl.GetBgeEmbeddingClient("ensemble_offline"),
		aispToolsClient:       rpcImpl.DefaultAispToolsClient,
		docParseTasks:         make(chan *model.KnowledgeBaseDocParseTask),
		rumTableName:          "kb_zhida_demo_private_1024d",
	}

	go service.startProcessDocParseTasks()

	return service
}

func (k *KnowledgebaseServiceDocImpl) BatchCreateKnowLedgeBaseDoc(ctx context.Context, rawDocs []*model.KnowledgeBaseDocRaw, knowledgeBase *model.KnowledgeBase, userId string) ([]*model.KnowledgeBaseDocRaw, error) {
	for _, rawDoc := range rawDocs {
		path := fmt.Sprintf(knowledgeBase.KnowledgeBasePath+"/%s", rawDoc.FileName)
		err := k.fileManagementDao.UploadFile(ctx, rawDoc.FileContent, path)
		if err != nil {
			log.Errorf(ctx, "uploadFile error. path=%s", path, err)
			continue
		}

		docId := uuid.New().String()
		knowledgeBaseDoc := &model.KnowledgeBaseDoc{
			UniqueId:        docId,
			KnowledgeBaseId: knowledgeBase.UniqueId,
			CreatorUserId:   userId,
			DocName:         rawDoc.FileName,
			State:           model.KnowledgeBaseDocStateInit,
			DocPath:         path,
			DocSourceType:   rawDoc.DocType,
			ParsedAt:        time.Now(),
		}

		count, err := k.knowledgeBaseDocDAO.CountDocByCreatorUserId(ctx, userId)
		if err != nil {
			log.Errorf(ctx, "CountDocByCreatorUserId error. userId=%s", userId, err)
			continue
		}

		if count > MaxDocNum {
			log.Errorf(ctx, "doc num exceed limit. userId=%s", userId)
			return rawDocs, errors.New("doc num exceed limit")
		}
		err = k.knowledgeBaseDocDAO.CreateKnowledgeBaseDoc(ctx, knowledgeBaseDoc)
		if err != nil {
			log.Errorf(ctx, "CreateKnowledgeBaseDoc error. uniqueId=%s", knowledgeBaseDoc.KnowledgeBaseId, err)
			continue
		}

		var contentType = lo.Ternary(rawDoc.DocType == model.KnowledgeBaseDocSourcePdf, "application/pdf", "text/html; charset=utf-8")
		url, err := k.fileManagementDao.GenerateFileUrl(ctx, path, contentType)
		if err != nil {
			log.Errorf(ctx, "GenerateFileUrl error. path=%s", path, err)
			continue
		}
		rawDoc.FileUrl = url
		rawDoc.UniqueId = docId

		k.submitDocParseTask(ctx, knowledgeBaseDoc, rawDoc)
	}

	return rawDocs, nil
}

func (k *KnowledgebaseServiceDocImpl) FindByDocId(ctx context.Context, docId string, withFileUrl bool) (*model.KnowledgeBaseDoc, error) {
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docId)
	if err != nil {
		return nil, err
	}

	if withFileUrl {
		var contentType = lo.Ternary(doc.DocSourceType == model.KnowledgeBaseDocSourcePdf, "application/pdf", "text/html; charset=utf-8")
		fileUrl, err := k.fileManagementDao.GenerateFileUrl(ctx, doc.DocPath, contentType)
		if err != nil {
			return nil, err
		}
		doc.Url = fileUrl
	}

	return doc, nil
}

func (k *KnowledgebaseServiceDocImpl) FindByDocNameAndUserId(ctx context.Context, name string, creatorUserId string) ([]*model.KnowledgeBaseDoc, error) {
	docs, err := k.knowledgeBaseDocDAO.FindByDocNameAndUserId(ctx, name, creatorUserId)
	if err != nil {
		return nil, err
	}

	return docs, nil
}

func (k *KnowledgebaseServiceDocImpl) DeleteByDocId(ctx context.Context, docId string) error {
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docId)
	if err != nil {
		return err
	}

	err = k.fileManagementDao.DeleteFile(ctx, doc.DocPath)
	if err != nil {
		return err
	}

	err = k.deleteRumIndex(ctx, docId)
	if err != nil {
		return err
	}

	doc.State = model.KnowledgeBaseDocStateDeleted
	err = k.knowledgeBaseDocDAO.UpdateKnowledgeBaseDoc(ctx, doc)
	if err != nil {
		return err
	}

	return nil
}

func (k *KnowledgebaseServiceDocImpl) Update(ctx context.Context, docId string, docName string) error {
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docId)
	if err != nil {
		return err
	}

	doc.DocName = docName
	err = k.knowledgeBaseDocDAO.UpdateKnowledgeBaseDoc(ctx, doc)
	if err != nil {
		return err
	}

	return nil
}

func (k *KnowledgebaseServiceDocImpl) RetrieveKnowledgeBaseDocs(ctx context.Context, query string, topK int, docIdStr string) ([]*model.KnowledgeBaseRetrieveResult, error) {
	embeddings := k.klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{query})
	if len(embeddings) == 0 {
		return nil, errors.New("get embedding error")
	}
	filterParam := fmt.Sprintf("doc_unique_id == %s", docIdStr)

	searchResult := k.rumClient.RumSearch(ctx, k.rumTableName, [][]float32{embeddings[0]}, int32(topK), filterParam, macro.KnowledgeBaseDocFields)

	if len(searchResult) == 0 || len(searchResult[0]) == 0 {
		return nil, errors.New("embedding search error")
	}
	var retrieveResult []*model.KnowledgeBaseRetrieveResult
	for _, result := range searchResult[0] {
		retrieveResult = append(retrieveResult, &model.KnowledgeBaseRetrieveResult{
			Text:       result.Fields[macro.KnowledgeBaseDocContent].(string),
			Similarity: result.Sim,
		})
	}

	return retrieveResult, nil
}

func (k *KnowledgebaseServiceDocImpl) GetDocDetail(ctx context.Context, docId string) ([]byte, error) {
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docId)
	if err != nil {
		return nil, err
	}

	fileContent, err := k.fileManagementDao.GetFileContent(ctx, k.getParsedFileContentPath(ctx, doc.DocPath))
	if err != nil {
		return nil, err
	}

	return fileContent, nil
}

// 删除rum索引
func (k *KnowledgebaseServiceDocImpl) deleteRumIndex(ctx context.Context, docId string) error {
	chunks, err := k.knowledgeBaseChunkDAO.FindByDocId(ctx, docId)
	if err != nil {
		log.Errorf(ctx, "FindByDocId error. docUniqueId=%s", docId)
		return err
	}

	for _, chunk := range chunks {
		success := k.rumClient.RumDelete(ctx, k.rumTableName, chunk.Id, "")
		if success {
			continue
		}
		err := k.knowledgeBaseChunkDAO.DeleteKnowledgeBaseChunk(ctx, chunk)
		if err != nil {
			log.Errorf(ctx, "DeleteKnowledgeBaseChunk error. chunkId=%s, err=+%v", chunk.Id, err)
			continue
		}
	}

	return nil
}

// 后续在线上使用的话，需要考虑把任务持久化
func (k *KnowledgebaseServiceDocImpl) submitDocParseTask(ctx context.Context, doc *model.KnowledgeBaseDoc, rawDoc *model.KnowledgeBaseDocRaw) {
	safe_group.SafeGo(func() error {

		k.docParseTasks <- &model.KnowledgeBaseDocParseTask{
			KnowledgeBaseDocId: doc.UniqueId,
			DocContent:         rawDoc.FileContent,
		}

		return nil
	}, "parse_doc")
}

func (k *KnowledgebaseServiceDocImpl) GetDocParseTaskState(ctx context.Context, docId string) (model.KnowledgeBaseDocState, error) {
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docId)
	if err != nil {
		return model.KnowledgeBaseDocStateInit, err
	}

	return doc.State, nil
}
func (k *KnowledgebaseServiceDocImpl) getParsedFileContentPath(ctx context.Context, docPath string) string {
	return docPath + "/" + "parsed"
}

func (k *KnowledgebaseServiceDocImpl) processDocParseTask(ctx context.Context, docParseTask *model.KnowledgeBaseDocParseTask) error {
	log.Infof(ctx, "begin processDocParseTask. docUniqueId=%s", docParseTask.KnowledgeBaseDocId)
	doc, err := k.knowledgeBaseDocDAO.FindByDocId(ctx, docParseTask.KnowledgeBaseDocId)
	if err != nil {
		log.Errorf(ctx, "FindByDocId error. docUniqueId=%s", docParseTask.KnowledgeBaseDocId, err)
		return err
	}

	var parseResult []*model.AispToolsItem
	if doc.DocSourceType == model.KnowledgeBaseDocSourcePdf {
		parseResult, err = k.aispToolsClient.ParsePdf(ctx, rpc.ProcessorNameLlamaIndexPdfParser, docParseTask.DocContent)
		lo.Filter(parseResult, func(item *model.AispToolsItem, _ int) bool {
			return item.Name == "pdf_element" && item.Element != nil
		})
	} else if doc.DocSourceType == model.KnowledgeBaseDocSourceUrlZhihu {
		parseResult, err = k.aispToolsClient.ParseHtml(ctx, rpc.ProcessorNameZhihuHtmlParser, docParseTask.DocContent, "", "")
	} else {
		parseResult, err = k.aispToolsClient.ParseHtml(ctx, rpc.ProcessorNameGeneralHtmlParser, docParseTask.DocContent, "", "")
	}

	if err != nil {
		log.Errorf(ctx, "ParsePdf error. docUniqueId=%s", docParseTask.KnowledgeBaseDocId, err)
		return err
	}
	textSlice := lo.Map(parseResult, func(item *model.AispToolsItem, _ int) string {
		return item.GetText()
	})

	for index, text := range textSlice {
		//chunker := rerank_util.NewDocumentChunker(
		//	ctx,
		//	text,
		//	index,
		//	chunkConfig.KeySize,
		//	chunkConfig.KeyStep,
		//	chunkConfig.ValueSize,
		//	chunkConfig.KeyOffset,
		//	chunkConfig.BoundaryRegex,
		//)
		// chunkRes := chunker.Chunks()

		chunkRes := rerank_util.ChunkRes{
			Chunks: util.SplitText([]rune(text), 512, 10000, 0),
		}

		embeddings := k.klaraEmbeddingClient.BatchInferEmbedding(ctx, chunkRes.Chunks)
		for i, chunk := range chunkRes.Chunks {
			chunkId := int64(xxhash.Sum64String(doc.UniqueId + fmt.Sprintf("_%d_%d", index, i)))
			extras := map[string]interface{}{}
			extras[macro.KnowledgeBaseDocContent] = chunk
			extras[macro.KnowledgeBaseDocUniqueId] = doc.UniqueId
			extras[macro.KnowledgeBaseDocCreatorUserId] = doc.CreatorUserId

			success := k.rumClient.RumUpsert(ctx, k.rumTableName, chunkId, embeddings[i], "", extras)
			if !success {
				log.Errorf(ctx, "RumUpsert error. docUniqueId=%s", doc.UniqueId)
				continue
			}

			// 后续需要考虑下支持多版本切chunk策略
			k.knowledgeBaseChunkDAO.CreateKnowledgeBaseChunk(ctx, &model.KnowledgeBaseChunk{
				Id:               chunkId,
				ChunkText:        chunk,
				DocId:            doc.UniqueId,
				ParseRuleVersion: doc.ParseRuleVersion,
			})
		}
	}

	doc.State = model.KnowledgeBaseDocStateParsed
	doc.ParsedAt = time.Now()
	err = k.knowledgeBaseDocDAO.UpdateKnowledgeBaseDoc(ctx, doc)
	if err != nil {
		log.Errorf(ctx, "UpdateKnowledgeBaseDoc error. docUniqueId=%s", docParseTask.KnowledgeBaseDocId, err)
	}

	fileContent := strings.Join(textSlice, "\n")
	k.fileManagementDao.UploadFile(ctx, []byte(fileContent), k.getParsedFileContentPath(ctx, doc.DocPath))
	return err
}

func (k *KnowledgebaseServiceDocImpl) startProcessDocParseTasks() {
	ctx := context.Background()
	mutex := sync.RWMutex{}

	// 接收channel中的任务
	for {
		select {
		case task, ok := <-k.docParseTasks:
			mutex.Lock()
			if ok {
				err := k.processDocParseTask(ctx, task)
				if err != nil {
					k.docParseTasks <- task
				}
			}
			mutex.Unlock()
		}
	}
}
