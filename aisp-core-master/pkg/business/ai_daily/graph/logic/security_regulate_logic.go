package logic

import (
	"context"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/one-rpc-go/thrift-tag-core/tag_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type SecurityRegulateLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	stage string
}

func NewSecurityRegulateLogic(name string, config map[string]string) *SecurityRegulateLogic {
	c := &SecurityRegulateLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	c.UserFunc = c.userFunc
	c.stage = config[conf.Stage]
	return c
}

func (c *SecurityRegulateLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.security_regulate_"+c.stage, time.Since(start).Milliseconds())
	}()
	var objects []*tag_core_thrift.ObjParam
	questionData := playListData.QuestionDetails
	if c.stage == conf.StageParsePlaylist {
		questionData = playListData.FinalQuestionDetails
	}
	for _, v := range questionData {
		objType := tag_core_thrift.ObjType_Question
		objects = append(objects, &tag_core_thrift.ObjParam{
			ObjID:   &v.QuestionID,
			ObjType: &objType,
		})
		for _, answer := range v.Answers {
			answerObjType := tag_core_thrift.ObjType_Answer
			objects = append(objects, &tag_core_thrift.ObjParam{
				ObjID:   &answer.AnswerID,
				ObjType: &answerObjType,
			})
		}
	}
	groupGetFunc := func(keys interface{}) interface{} {
		tagInfoMap, err := impl.DefaultTagCoreServiceImpl.MGetTagContents(ctx, rpc.SceneCode_Ai_Daily, rpc.AppGroupCode_Ai_daily, keys.([]*tag_core_thrift.ObjParam))
		if err != nil {
			return nil
		}
		res := make(map[*tag_core_thrift.ObjectInfo]struct{})
		for k, v := range tagInfoMap {
			for _, info := range v {
				if info.GetTagInfo().TagCode == conf.SecurityRegulateTagCode {
					res[k] = struct{}{}
					break
				}
			}
		}
		return res
	}
	result := make(map[*tag_core_thrift.ObjectInfo]struct{})
	safe_group.BatchGet(50, objects, groupGetFunc, &result)
	log.Infof(ctx, "SecurityRegulate Num=%v", len(result))
	for k, _ := range result {
		prefix := ""
		if k.GetObjType() == tag_core_thrift.ObjType_Answer {
			prefix = conf.SecurityRegulateAnswerPrefix
		} else {
			prefix = conf.SecurityRegulateQuestionPrefix
		}
		playListData.SecurityRegulateMap[prefix+k.GetObjId()] = struct{}{}
	}
	return nil
}
