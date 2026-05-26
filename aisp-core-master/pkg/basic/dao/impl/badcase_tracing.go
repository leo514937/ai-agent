package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BadCaseTracingDaoImpl struct {
	db *borm.ORM
}

var _ dao.BadCaseTracingDao = (*BadCaseTracingDaoImpl)(nil)

var DefaultBadCaseTracingDaoImpl *BadCaseTracingDaoImpl

func init() {
	DefaultBadCaseTracingDaoImpl = NewBadCaseTracingDaoImpl()
}

func NewBadCaseTracingDaoImpl() *BadCaseTracingDaoImpl {
	return &BadCaseTracingDaoImpl{
		db: mysql.AispInternalBorm,
	}
}

func (b *BadCaseTracingDaoImpl) GetBadCaseTracingList(ctx context.Context, filterParam *model.BadcaseTracingFilterParams) ([]*model.BadcaseTracingList, int64, error) {
	logger := log.WithField(ctx, "GetBadCaseTracingList", filterParam)
	db := b.db

	var badCaseTracingList []*model.BadcaseTracingList
	var query *borm.ORM
	if filterParam.State == 0 {
		query = db.Where(borm.Ne{"state": 0})
	} else {
		query = db.Where(borm.Eq{"state": filterParam.State})
	}

	if len(filterParam.ChatScene) > 0 {
		query = query.Where(borm.Eq{"chat_scene": filterParam.ChatScene})
	}
	if filterParam.MemberId != 0 {
		query = query.Where(borm.Eq{"member_id": filterParam.MemberId})
	}
	if filterParam.RequestMessageId != "" {
		query = query.Where(borm.Eq{"request_message_id": filterParam.RequestMessageId})
	}
	if filterParam.RequestQuery != "" {
		requestQuery := "%" + filterParam.RequestQuery + "%"
		query = query.Where(borm.Like{"request_query": requestQuery})
	}
	if filterParam.ResponseMessageId != "" {
		query = query.Where(borm.Eq{"response_message_id": filterParam.ResponseMessageId})
	}
	if filterParam.CaseType != "" {
		query = query.Where(borm.Eq{"case_type": filterParam.CaseType})
	}
	if filterParam.HandlingState != "" {
		query = query.Where(borm.Eq{"handling_state": filterParam.HandlingState})
	}
	if filterParam.FeedbackSource != "" {
		query = query.Where(borm.Eq{"feedback_source": filterParam.FeedbackSource})
	}
	if filterParam.TraceId != "" {
		query = query.Where(borm.Eq{"trace_id": filterParam.TraceId})
	}
	if filterParam.FeedbackStartTime != nil && !filterParam.FeedbackStartTime.IsZero() {
		query = query.Where(borm.GTE{"created_at": filterParam.FeedbackStartTime})
	}
	if filterParam.FeedbackEndTime != nil && !filterParam.FeedbackEndTime.IsZero() {
		query = query.Where(borm.LTE{"created_at": filterParam.FeedbackEndTime})
	}
	if filterParam.ToBeResolved == 1 {
		query = query.Where(borm.Eq{"to_be_resolved": filterParam.ToBeResolved})
	}

	// 读取列表数据
	err := query.OrderBy("-created_at").Offset(filterParam.Page*filterParam.PageSize).Limit(filterParam.PageSize).All(ctx, &badCaseTracingList)
	if err != nil {
		logger.Errorf(ctx, "GetBadCaseTracingList err. err=%v", err)
		return nil, 0, err
	}
	// 返回总数
	total, err := query.Model(&model.BadcaseTracingList{}).Count(ctx)
	if err != nil {
		logger.Errorf(ctx, "GetBadCaseTracingList count err. err=%v", err)
		return nil, 0, err
	}

	return badCaseTracingList, total, nil
}

func (b *BadCaseTracingDaoImpl) GetBadCaseTracingProcess(ctx context.Context, tracingId string) (*model.BadcaseTracingProcess, error) {
	logger := log.WithField(ctx, "GetBadCaseTracingProcess", tracingId)
	db := b.db

	var badCaseTracingProcess model.BadcaseTracingProcess
	err := db.Where(borm.Eq{"trace_id": tracingId}).OrderBy("-created_at").One(ctx, &badCaseTracingProcess)
	if err != nil {
		logger.Errorf(ctx, "GetBadCaseTracingProcess err. err=%v", err)
		return nil, err
	}

	return &badCaseTracingProcess, nil
}

func (b *BadCaseTracingDaoImpl) UpsertBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	logger := log.WithField(ctx, "UpsertBadCaseTracingRecord", util.GetJSONIgnoreError(badCaseTracingRecord))
	db := b.db

	exist, id := b.IsBadCaseRecordExist(ctx, badCaseTracingRecord.TraceId)
	if exist {
		params := map[string]interface{}{
			"id":                  id,
			"member_id":           badCaseTracingRecord.MemberId,
			"chat_scene":          badCaseTracingRecord.ChatScene,
			"chat_sub_scene":      badCaseTracingRecord.ChatSubScene,
			"request_message_id":  badCaseTracingRecord.RequestMessageId,
			"request_query":       badCaseTracingRecord.RequestQuery,
			"response_message_id": badCaseTracingRecord.ResponseMessageId,
			"response_answer":     badCaseTracingRecord.ResponseAnswer,
			"feedback_source":     badCaseTracingRecord.FeedbackSource,
			"case_type":           badCaseTracingRecord.CaseType,
			"case_description":    badCaseTracingRecord.CaseDescription,
			"handling_state":      badCaseTracingRecord.HandlingState,
			"handling_member":     badCaseTracingRecord.HandlingMember,
			"handling_result":     badCaseTracingRecord.HandlingResult,
			"handling_module":     badCaseTracingRecord.HandlingModule,
			"state":               badCaseTracingRecord.State,
		}
		updateResult := db.Model(badCaseTracingRecord).Updates(ctx, params)
		if updateResult.Error != nil {
			logger.Errorf(ctx, "UpsertBadCaseTracingRecord err. err=%v", updateResult.Error)
			return updateResult.Error
		}
	} else {
		insertResult := db.Create(ctx, badCaseTracingRecord)
		if insertResult.Error != nil {
			logger.Errorf(ctx, "UpsertBadCaseTracingRecord err. err=%v", insertResult.Error)
			return insertResult.Error
		}
	}

	return nil
}

func (b *BadCaseTracingDaoImpl) IsBadCaseRecordExist(ctx context.Context, traceId string) (bool, int64) {
	logger := log.WithField(ctx, "IsBadCaseRecordExist", traceId)
	db := b.db

	var badCaseTracingList []*model.BadcaseTracingList
	err := db.Where(borm.AND{borm.Eq{"trace_id": traceId}, borm.Ne{"state": 0}}).All(ctx, &badCaseTracingList)
	if err != nil {
		logger.Errorf(ctx, "IsBadCaseRecordExist err. err=%v", err)
		return false, 0
	}
	if len(badCaseTracingList) > 0 {
		return true, badCaseTracingList[0].ID
	} else {
		return false, 0
	}
}

func (b *BadCaseTracingDaoImpl) InsertBadCaseTracingProcess(ctx context.Context, badCaseTracingProcess *model.BadcaseTracingProcess) error {
	logger := log.WithField(ctx, "InsertBadCaseTracingProcess", util.GetJSONIgnoreError(badCaseTracingProcess))
	db := b.db

	insertResult := db.Create(ctx, badCaseTracingProcess)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "InsertBadCaseTracingProcess err. err=%v", insertResult.Error)
		return insertResult.Error
	}

	return nil
}

func (b *BadCaseTracingDaoImpl) UpdateBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	logger := log.WithField(ctx, "UpdateBadCaseTracingRecord", util.GetJSONIgnoreError(badCaseTracingRecord))
	db := b.db

	params := map[string]interface{}{}
	if badCaseTracingRecord.HandlingState != "" {
		params["handling_state"] = badCaseTracingRecord.HandlingState
	}
	if badCaseTracingRecord.HandlingMember != "" {
		params["handling_member"] = badCaseTracingRecord.HandlingMember
	}
	if badCaseTracingRecord.HandlingResult != "" {
		params["handling_result"] = badCaseTracingRecord.HandlingResult
	}
	if badCaseTracingRecord.HandlingModule != "" {
		params["handling_module"] = badCaseTracingRecord.HandlingModule
	}

	updateQueryResult := db.Model(badCaseTracingRecord).Where(borm.Eq{"trace_id": badCaseTracingRecord.TraceId}).UpdateRaw(ctx, params)
	err := updateQueryResult.Error
	if err != nil {
		logger.Errorf(ctx, "UpdateBadCaseTracingRecord err. err=%v", err)
	}
	return err
}

func (b *BadCaseTracingDaoImpl) UpdateBadCaseToBeResolved(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	logger := log.WithField(ctx, "UpdateBadCaseToBeResolved", util.GetJSONIgnoreError(badCaseTracingRecord))
	db := b.db

	params := map[string]interface{}{
		"to_be_resolved": badCaseTracingRecord.ToBeResolved,
	}

	updateQueryResult := db.Model(badCaseTracingRecord).Where(borm.Eq{"trace_id": badCaseTracingRecord.TraceId, "state": 1}).UpdateRaw(ctx, params)
	err := updateQueryResult.Error
	if err != nil {
		logger.Errorf(ctx, "UpdateBadCaseToBeResolved err. err=%v", err)
	}
	return err
}

func (b *BadCaseTracingDaoImpl) DeleteBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	logger := log.WithField(ctx, "DeleteBadCaseTracingRecord", util.GetJSONIgnoreError(badCaseTracingRecord))
	db := b.db

	params := map[string]interface{}{
		"state": 0,
	}

	deleteQueryResult := db.Model(badCaseTracingRecord).Where(borm.Eq{"trace_id": badCaseTracingRecord.TraceId}).UpdateRaw(ctx, params)
	err := deleteQueryResult.Error
	if err != nil {
		logger.Errorf(ctx, "DeleteBadCaseTracingRecord err. err=%v", err)
	}
	return err
}
