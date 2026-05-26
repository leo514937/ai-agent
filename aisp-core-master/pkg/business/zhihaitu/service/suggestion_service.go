package service

import (
	"context"
	"strconv"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"github.com/google/uuid"
)

var suggestionDao = dao.DefaultBmbSuggestionDAO

func Suggestion(ctx context.Context, req *model.SuggestionRequest, accountID int64) *macro.ServiceError {
	suggestion := &model.TableBmbSuggestion{
		Status:     model.SuggestionState_Processing.Status(),
		Numbered:   uuid.NewString(),
		Content:    req.Content,
		AccountID:  accountID,
		AppID:      constant.ZhiHaiTuAppID,
		CreateTime: time.Now(),
		UpdateTime: time.Now(),
	}
	return suggestionDao.CreateSuggestion(ctx, suggestion)
}

func GetUserSuggestion(ctx context.Context, accountID int64) ([]*model.UserSuggestion, *macro.ServiceError) {
	results := make([]*model.UserSuggestion, 0)
	suggestions, serviceErr := suggestionDao.GetSuggestionByAccountID(ctx, accountID)
	if serviceErr != nil {
		return nil, serviceErr
	}
	if len(suggestions) == 0 {
		return results, nil
	}
	for _, v := range suggestions {
		res := &model.UserSuggestion{
			AccountId:    v.AccountID,
			AppId:        v.AppID,
			AuditContent: v.AuditContent,
			AuditTime:    util.FormatSafeTime2yyyyMMddTHHmmss(v.AuditTime),
			Content:      v.Content,
			CreateTime:   util.FormatTime2yyyyMMddTHHmmss(v.CreateTime),
			ID:           strconv.FormatInt(v.ID, 10),
			Numbered:     v.Numbered,
			Status:       model.SuggestionState(v.Status).String(),
			UpdateTime:   util.FormatTime2yyyyMMddTHHmmss(v.UpdateTime),
		}
		results = append(results, res)
	}
	return results, nil
}
