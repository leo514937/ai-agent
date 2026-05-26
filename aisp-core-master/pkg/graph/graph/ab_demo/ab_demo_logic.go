package empty

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources/ab"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// show ab 如何判断的 demo
// todo @zhoupengcheng 可以参考下面 ab 的判断方式，真正业务接入的时候把这个算子删了
type AbDemoLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewEmptyLogic(name string, config map[string]string) *AbDemoLogic {
	res := &AbDemoLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (q *AbDemoLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	// 获取 ab 的值
	requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdRecommendMemberStrategyDomain).GetZlabABValue(ab.WarmUpCb2CfExp1)

	// 判断 ab 属于实验组 exp1（这个也许适合你）
	if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdRecommendMemberStrategyDomain).GetZlabAB(ab.WarmUpCb2CfExp1) {
		log.Infof(ctx, "is WarmUpCb2CfExp1")
	}

	// 判断 ab 属于实验组 exp2
	if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdRecommendMemberStrategyDomain).GetZlabAB(ab.WarmUpCb2CfExp2) {
		log.Infof(ctx, "is WarmUpCb2CfExp2")
	}

	// 判断 ab 属于实验组1或实验组2（当俩实验组都需要执行某一个策略时，可以用这个）
	if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdRecommendMemberStrategyDomain).ContainsAny(ab.WarmUpCb2CfExp1, ab.WarmUpCb2CfExp2) {
		log.Infof(ctx, "is WarmUpCb2CfExp1 or WarmUpCb2CfExp2")
	}

	return lo.Flatten(itemLists), nil
}
