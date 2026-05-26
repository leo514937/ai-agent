package logic

import (
	"context"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetAnswerAuthorLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetAnswerAuthorLogic(name string, config map[string]string) *GetAnswerAuthorLogic {
	g := &GetAnswerAuthorLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetAnswerAuthorLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.get_answer_author", time.Since(start).Milliseconds())
	}()
	answerAuthorHashIDs := make([]string, 0)
	for _, v := range playListData.FinalQuestionDetails {
		for _, answer := range v.Answers {
			answerAuthorHashIDs = append(answerAuthorHashIDs, answer.AnswerAuthorHashID)
		}
	}
	users, err := impl.DefaultUserCoreServiceImpl.BatchGetUserByHashIds(ctx, answerAuthorHashIDs, []string{user_core_thrift.ProfileField})
	if err != nil {
		log.Errorf(ctx, "[GetQuestionDetailLogic] BatchGetUserByHashIds error: %v", err)
		return err
	}
	for _, v := range playListData.FinalQuestionDetails {
		for _, answer := range v.Answers {
			if userInfo, ok := users[answer.AnswerAuthorHashID]; ok && userInfo.GetProfile() != nil {
				answer.AnswerAuthorName = userInfo.GetProfile().GetFullname()
			} else {
				answer.AnswerAuthorName = "知乎用户"
			}
		}
	}
	return nil
}
