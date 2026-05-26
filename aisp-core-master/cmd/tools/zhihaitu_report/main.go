package main

import (
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

func main() {
	txn, ctx := log.StartTransaction("tools_zhihaitu_report")
	defer txn.End(ctx)

	model.SendData(ctx, &model.UserQuestion{
		QuestionID:  "1",
		Content:     "test",
		UserID:      "1",
		State:       1,
		SessionID:   "1",
		PublishTime: time.Now().Format("20060102150405"),
	})
	model.SendData(ctx, &model.AIAnswer{
		QuestionID:     "1",
		AnswerID:       "1",
		AnswerType:     1,
		RegenerateType: 1,
		SessionID:      "1",
		PublishTime:    time.Now().Format("20060102150405"),
	})
	model.SendData(ctx, &model.UserFeedback{
		AnswerID:     "1",
		QuestionID:   "1",
		FeedbackType: 1,
		UserID:       "1",
		SessionID:    "1",
	})
	model.SendData(ctx, &model.SessionCreated{
		UserID:     "1",
		SessionID:  "1",
		UpdateTime: time.Now().Format("20060102150405"),
	})

	sessionSet := make(map[string]bool)

	lucaDao := NewLucaDaoImpl()
	itemList, err := lucaDao.QueryALlConvMessage(ctx)
	if err != nil {
		panic(err)
	}
	for i, item := range itemList {
		if !sessionSet[item.ConvID] {
			sessionSet[item.ConvID] = true
			model.SendData(ctx, &model.SessionCreated{
				UserID:     cast.ToString(item.AccountID),
				SessionID:  item.ConvID,
				UpdateTime: item.CreateTime.Format("20060102150405"),
			})
		}
		if item.Role == 1 {
			// AI
			model.SendData(ctx, &model.AIAnswer{
				QuestionID:     item.ParentMsgID,
				AnswerID:       item.MsgID,
				AnswerType:     1,
				RegenerateType: 1,
				SessionID:      item.ConvID,
				PublishTime:    item.CreateTime.Format("20060102150405"),
			})

			if item.FeedbackMsg != nil && *item.FeedbackMsg != "" {
				model.SendData(ctx, &model.UserFeedback{
					AnswerID:     item.MsgID,
					QuestionID:   item.ParentMsgID,
					FeedbackType: 3,
					UserID:       cast.ToString(item.AccountID),
					SessionID:    item.ConvID,
				})
			}
		} else if item.Role == 2 {
			// 用户
			state := int64(1)
			if item.StopEnum != nil && *item.StopEnum != "PASS" {
				state = 2
			}
			model.SendData(ctx, &model.UserQuestion{
				QuestionID:  item.MsgID,
				Content:     item.Content,
				UserID:      cast.ToString(item.AccountID),
				State:       state,
				SessionID:   item.ConvID,
				PublishTime: item.CreateTime.Format("20060102150405"),
			})
		} else {
			log.Infof(ctx, "i=%d role=%d", i, item.Role)
		}

		time.Sleep(100 * time.Millisecond)
	}

}
