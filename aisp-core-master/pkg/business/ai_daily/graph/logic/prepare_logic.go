package logic

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type PrepareLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewPrepareLogic(name string, config map[string]string) *PrepareLogic {
	p := &PrepareLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	p.UserFunc = p.userFunc
	p.SetChooseKeyFunc(p.chooseKey)
	return p
}

func (p *PrepareLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	if request.Date == "" {
		request.Date = time.Now().Format("2006-01-02")
	}
	return nil
}

func (p *PrepareLogic) checkParam(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	log.WithFields(ctx, map[string]interface{}{
		"token":  request.Token,
		"date":   request.Date,
		"userID": request.UserID,
		"source": request.Source,
	}).Info(ctx, "request param")
	if request.Token != "" {
		// 客态，跳过校验
		return true
	}
	if request.Date != "" {
		// 日期格式不合法
		_, err := time.Parse("2006-01-02", request.Date)
		if err != nil {
			return false
		}
	}

	if request.UserID <= 0 && request.Token == "" { // 未登录用户无客态token
		return false
	}
	return true
}

func (p *PrepareLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	if p.checkParam(ctx, param.RequestContext) {
		return "Normal"
	}
	return "Return"
}
