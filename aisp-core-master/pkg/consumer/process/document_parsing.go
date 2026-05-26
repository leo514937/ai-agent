package process

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const documentParsingScene = "kafka.document_parsing"

type DocumentParsingProcessor struct {
	contentClient    rpc.ContentCoreRPC
	ossClient        rpc.Oss
	aispToolsClient  rpc.AispToolsClient
	knowledgebaseDao dao.DocumentParsingDao
}

func NewDocumentParsingProcessor() *DocumentParsingProcessor {
	return &DocumentParsingProcessor{
		contentClient:    impl.DefaultContentCoreRPCImpl,
		ossClient:        impl.DefaultOssImpl,
		aispToolsClient:  impl.DefaultAispToolsClient,
		knowledgebaseDao: daoImpl.DefaultDocumentParsingDaoImpl,
	}
}

func (d *DocumentParsingProcessor) TopicName() macro.TopicName {
	return macro.DocumentParsing
}

func (d *DocumentParsingProcessor) Process(ctx context.Context, message *stream.Message) error {
	statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".recieved.count", documentParsingScene))

	msg := &module.DocumentParsingKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".unmarshal.count", documentParsingScene))
		return errors.New("unmarshal error")
	}

	docId, typeErr := util.String2Int64(msg.ZhidaRelevantSource.DocId)
	docType := util.ContentType2DocType(msg.ZhidaRelevantSource.DocType)
	if typeErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".type.count", documentParsingScene))
		return errors.New("type error")
	}

	// 读内容平台
	content := model.NewContentWithDocType(docId, docType)
	contentInfoMap := d.contentClient.BatchGetContent(ctx, []model.Content{content}, base.ContentInfoFieldContentBizExtDetail)
	contentInfo := contentInfoMap[content]
	if contentInfo == nil || contentInfo.GetBizExtDetail().GetPaperBizExt().GetPdfPath() == "" {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".empty.count", documentParsingScene))
		return errors.New("empty contentInfo")
	}

	// 从 oss 中读取文件
	ossPath := d.ossClient.GetOssFilePath(ctx, contentInfo.GetBizExtDetail().GetPaperBizExt().GetPdfPath(), "aisp-core", "zhida", "community-assets")
	fileBytes, ossErr := d.ossClient.GetFileBytes(ctx, ossPath)
	if ossErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".oss.count", documentParsingScene))
		return ossErr
	}

	// pdf 解析
	pdfParseResult, parseErr := impl.DefaultAispToolsClient.ParsePdf(ctx, rpc.ProcessorNamePymuPdfParser, fileBytes)
	if parseErr != nil || len(pdfParseResult) != 1 {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".parse.count", documentParsingScene))
		return parseErr
	}
	// 过滤空解析结果
	parseItem := pdfParseResult[0]
	if parseItem.GetText() == "" {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".parse_empty.count", documentParsingScene))
		log.Errorf(ctx, "parse empty, docId:%d, docType:%s", docId, docType.String())
		return errors.New("parse empty")
	}
	// tidb单行数据限制6M，此字段长度限制5M
	if len(parseItem.GetText()) > 5*1024*1024 {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".parse_too_long.count", documentParsingScene))
		log.Errorf(ctx, "parse too long, docId:%d, docType:%s", docId, docType.String())
		return errors.New("parse too long")
	}

	doc := &model.DocumentParsingBase{
		DocId:            docId,
		DocType:          docType.String(),
		ProcessorType:    rpc.ProcessorTypePdfParser.String(),
		ProcessorName:    rpc.ProcessorNamePymuPdfParser.String(),
		ProcessorVersion: parseItem.Version,
		ItemName:         parseItem.Name,
		Content:          util.GetJSONIgnoreError(parseItem.Element),
	}

	// 先判断一下库里是否存在
	existDoc, selectErr := d.knowledgebaseDao.GetDocumentParsing(ctx, docId, docType, rpc.ProcessorNamePymuPdfParser.String())

	if selectErr != nil || existDoc == nil {
		return d.insertRecord(ctx, doc)
	} else {
		return d.updateRecord(ctx, existDoc.ID, doc)
	}
}

func (d *DocumentParsingProcessor) insertRecord(ctx context.Context, doc *model.DocumentParsingBase) error {
	insertErr := daoImpl.DefaultDocumentParsingDaoImpl.InsertDocumentParsing(ctx, doc)
	log.Infof(ctx, "insert document status:%v, item %s:%d, processor version:%s, error:%v", insertErr == nil, doc.DocType, doc.DocId, doc.ProcessorVersion, insertErr)
	if insertErr == nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".insert_succ.count", documentParsingScene))
	}
	return insertErr
}

func (d *DocumentParsingProcessor) updateRecord(ctx context.Context, id int64, doc *model.DocumentParsingBase) error {
	doc.ID = id
	updateErr := daoImpl.DefaultDocumentParsingDaoImpl.UpdateDocumentParsing(ctx, doc)
	log.Infof(ctx, "update document status:%v, id:%d, item %s:%d, processor version:%s, error:%v", updateErr == nil, doc.ID, doc.DocType, doc.DocId, doc.ProcessorVersion, updateErr)
	if updateErr == nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".update_succ.count", documentParsingScene))
	}
	return updateErr
}
