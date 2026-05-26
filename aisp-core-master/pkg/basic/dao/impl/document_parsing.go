package impl

import (
	"context"
	"fmt"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type DocumentParsingDaoImpl struct {
	db *borm.ORM
}

var _ dao.DocumentParsingDao = (*DocumentParsingDaoImpl)(nil)

var DefaultDocumentParsingDaoImpl *DocumentParsingDaoImpl

func init() {
	DefaultDocumentParsingDaoImpl = NewDocumentParsingDaoImpl()
}

func NewDocumentParsingDaoImpl() *DocumentParsingDaoImpl {
	return &DocumentParsingDaoImpl{
		db: mysql.AispInternalBorm,
	}
}

func (d *DocumentParsingDaoImpl) GetDocumentParsing(ctx context.Context, docId int64, docType content.DocType_Type, processorName string) (*model.DocumentParsingBase, error) {
	logger := log.WithField(ctx, "GetDocumentParsing", fmt.Sprintf("docId:%d,docType:%s,processorName:%s", docId, docType, processorName))

	documentParsing := &model.DocumentParsingBase{}
	err := d.db.Where(borm.Eq{"doc_id": docId, "doc_type": docType.String(), "processor_name": processorName}).One(ctx, documentParsing)
	if err != nil {
		logger.Errorf(ctx, "GetDocumentParsing err. err=%v", err)
		return nil, err
	}

	return documentParsing, nil
}

func (d *DocumentParsingDaoImpl) InsertDocumentParsing(ctx context.Context, documentParsing *model.DocumentParsingBase) error {
	logger := log.WithField(ctx, "InsertDocumentParsing", util.GetJSONIgnoreError(documentParsing))

	insertResult := d.db.Create(ctx, documentParsing)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "InsertDocumentParsing err. err=%v", insertResult.Error)
		return insertResult.Error
	}

	return nil
}

func (d *DocumentParsingDaoImpl) UpdateDocumentParsing(ctx context.Context, documentParsing *model.DocumentParsingBase) error {
	logger := log.WithField(ctx, "InsertDocumentParsing", util.GetJSONIgnoreError(documentParsing))

	params := map[string]interface{}{
		"id":                documentParsing.ID,
		"processor_version": documentParsing.ProcessorVersion,
		"content":           documentParsing.Content,
		"content_url":       documentParsing.ContentUrl,
	}

	updateQueryResult := d.db.Model(&documentParsing).Updates(ctx, params)
	err := updateQueryResult.Error
	if err != nil {
		logger.Errorf(ctx, "UpdateDocumentParsing err. err=%v", err)
	}
	return err
}
