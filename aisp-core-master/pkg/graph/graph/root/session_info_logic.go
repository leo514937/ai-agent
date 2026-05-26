package root

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_session"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 获取 session 具体信息
type SessionInfoLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, *model.DialogSession]
	sessionService service.DialogSessionService
}

func NewSessionInfoLogic(name string, config map[string]string) *SessionInfoLogic {
	res := &SessionInfoLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, *model.DialogSession](name, config),
	}
	res.sessionService = service.NewDialogSessionService()
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

func (s *SessionInfoLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) (*model.DialogSession, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.SessionInfoLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.SessionInfoSkip.ToConvert()))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", s.GetName())
		return nil, nil
	}

	// 根据 sessionId 获取 sessionInfo
	sessionId := requestCtx.GetBizContext().GetSessionId()
	sessionInfo, err := s.sessionService.GetSessionInfo(ctx, sessionId)
	constant.DataInputNodeLog.Infof(logCtx, "sessionId:%d", sessionId)

	if err != nil {
		constant.DataOutputNodeLog.Infof(logCtx, "err:%v", err)
		return nil, err
	}

	s.saveTracing(sessionId, sessionInfo, startTime, requestCtx)

	return sessionInfo, err
}

func (s *SessionInfoLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], sessionInfo *model.DialogSession) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.ChatHistoryLogic.realMergeUser")
	defer span.Finish()

	if sessionInfo == nil {
		return nil
	}
	var extraInfo *proto.ExtraInfo
	if err := json.Unmarshal([]byte(sessionInfo.ExtraInfo), &extraInfo); err != nil {
		return nil
	}

	requestCtx.GetBizContext().SetExtraInfo(extraInfo)
	return nil
}

func (s *SessionInfoLogic) saveTracing(sessionId int64, sessionInfo *model.DialogSession, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{fmt.Sprintf("sessionId:%d", sessionId)},
		LogicOutput: []string{util.GetJSONIgnoreError(sessionInfo)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)
}
