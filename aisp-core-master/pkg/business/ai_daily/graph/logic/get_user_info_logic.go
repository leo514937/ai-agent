package logic

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetUserInfoLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetUserInfoLogic(name string, config map[string]string) *GetUserInfoLogic {
	g := &GetUserInfoLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	g.AddCondition(condition.NewGetUserInfoControl("GetUserInfo"))
	return g
}

func (g *GetUserInfoLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	userInfo, err := impl.DefaultUserCoreServiceImpl.BatchGetUserByIds(ctx, []int64{playListData.UserID}, []string{user_core_thrift.ProfileField})
	if err != nil {
		log.Errorf(ctx, "[GetUserInfoLogic] BatchGetUserByIds error: %v userID=%v", err, playListData.UserID)
		return err
	}
	if val, ok := userInfo[playListData.UserID]; ok && val.GetProfile() != nil {
		playListData.UserName = val.GetProfile().GetFullname()
	}
	return nil
}
