package logic

import (
	"context"
	"strconv"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type ContentRegulateLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	stage string
}

func NewContentRegulateLogic(name string, config map[string]string) *ContentRegulateLogic {
	c := &ContentRegulateLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	c.UserFunc = c.userFunc
	c.stage = config[conf.Stage]
	return c
}

func (c *ContentRegulateLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.content_regulate_"+c.stage, time.Since(start).Milliseconds())
	}()
	var contents []model.Content
	questionData := playListData.QuestionDetails
	if c.stage == conf.StageParsePlaylist {
		questionData = playListData.FinalQuestionDetails
	}
	for _, v := range questionData {
		if questionID, err := strconv.ParseInt(v.QuestionID, 10, 64); err == nil {
			contents = append(contents, model.Content{
				ContentID:   questionID,
				ContentType: content.DocType_Question,
			})
		}
		for _, answer := range v.Answers {
			if answerID, err := strconv.ParseInt(answer.AnswerID, 10, 64); err == nil {
				contents = append(contents, model.Content{
					ContentID:   answerID,
					ContentType: content.DocType_Answer,
				})
			}
		}
	}
	playListData.ContentRegulateMap = impl.DefaultContentRegulateRPCImpl.BatchGetValidInstruction(ctx, rpc.SceneCodeSearch, "", contents)
	return nil
}
