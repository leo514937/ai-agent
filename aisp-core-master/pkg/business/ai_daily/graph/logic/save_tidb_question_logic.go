package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type SaveTiDBQuestionLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewSaveTiDBQuestionLogic(name string, config map[string]string) *SaveTiDBQuestionLogic {
	s := &SaveTiDBQuestionLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	s.UserFunc = s.userFunc
	s.AddCondition(condition.NewSavePlaylistControl("SaveTiDB"))
	return s
}

func (s *SaveTiDBQuestionLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	_ = s.SaveTiDB(ctx, requestCtx.GetBizContext().GetPlayListData())
	return nil
}

func (s *SaveTiDBQuestionLogic) SaveTiDB(ctx context.Context, playListData *model.PlayListData) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"token": playListData.HashToken,
	})
	questionIDs := make([]string, 0)
	for _, v := range playListData.FinalQuestionDetails {
		questionIDs = append(questionIDs, v.QuestionID)
	}
	err := resource.MySQLAISPCore.WithTxn(ctx, func() error {
		alreadyExist, queryErr := dao.DefaultQuestionDetailCntDAO.ExistQuestionIDs(ctx, questionIDs)
		if queryErr != nil {
			logger.Errorf(ctx, "ExistQuestionIDs failed.err=%v", queryErr)
			return queryErr
		}
		datas := make([]*model.TableQuestionDetailCnt, 0)
		for _, v := range questionIDs {
			if _, ok := alreadyExist[v]; !ok {
				datas = append(datas, &model.TableQuestionDetailCnt{
					QuestionID: v,
					CreatedAt:  playListData.CardGenerateTime.Unix(),
				})
			}
		}
		if len(datas) == 0 {
			return nil
		}
		insertErr := dao.DefaultQuestionDetailCntDAO.BatchCreateQuestionDetailCnt(ctx, datas)
		if insertErr != nil {
			logger.Errorf(ctx, "BatchCreateDailySnapshot failed.err=%v", insertErr)
			return insertErr
		}
		return nil
	})
	if err != nil {
		return err
	}
	return nil
}
