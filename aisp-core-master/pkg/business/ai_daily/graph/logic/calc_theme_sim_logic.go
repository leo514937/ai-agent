package logic

import (
	"context"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type CalcThemeSimLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	embRpc *impl.UnifiedEmbGrpcImpl
}

func NewCalcThemeSimLogic(name string, config map[string]string) *CalcThemeSimLogic {
	c := &CalcThemeSimLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	c.UserFunc = c.userFunc
	return c
}

func (c *CalcThemeSimLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.calc_theme_sim", time.Since(start).Milliseconds())
	}()
	themeNames := make([]string, 0)
	for _, v := range playListData.QuestionDetails {
		themeNames = append(themeNames, v.LabelContent)
	}
	themeNames = util2.UniqueElementSlice(themeNames)
	resp, err := impl.DefaultSimilarGrpcImpl.GetSimilarV2(ctx, themeNames, themeNames, rpc.SimilarSourceCodeBgeSimilar)
	if err != nil || resp == nil {
		return err
	}
	for _, v := range resp.GetItems() {
		text1 := v.Target.Content
		text2 := v.Candidate.Content
		playListData.Theme2ThemeSimMap[text1+"_"+text2] = v.GetScore()
		playListData.Theme2ThemeSimMap[text2+"_"+text1] = v.GetScore()
	}
	return nil
}
