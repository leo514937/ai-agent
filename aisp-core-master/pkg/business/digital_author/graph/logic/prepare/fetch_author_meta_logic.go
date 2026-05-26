package prepare

import (
	"context"

	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type AuthorMetaLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, *entities.UserMeta]
}

func NewAuthorMetaLogic(name string, config map[string]string) *AuthorMetaLogic {
	res := &AuthorMetaLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, *entities.UserMeta](name, config),
	}
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

// 获取 author 相关 meta 信息
func (c *AuthorMetaLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) (*entities.UserMeta, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.AuthorMetaLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	authorMeta := requestCtx.GetBizContext().AuthorInfo().UserMeta()
	if authorMeta == nil {
		authorMeta = &entities.UserMeta{}
	}

	bayesNames := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).BayesFirstCategory()
	topicNames := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).TopicNames()
	authorName := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).AuthorName()
	isEnableOnsite := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).IsEnableOnsite()
	isEnableUniversal := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).IsEnableUniversal()

	authorMeta.SetBayesNames(bayesNames)
	authorMeta.SetTopicNames(topicNames)
	authorMeta.SetUserName(authorName)
	authorMeta.SetIsEnableOnsite(isEnableOnsite)
	authorMeta.SetIsEnableUniversal(isEnableUniversal)

	return authorMeta, nil
}

func (c *AuthorMetaLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], authorMeta *entities.UserMeta) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.AuthorMetaLogic.realMergeUser")
	defer span.Finish()

	requestCtx.GetBizContext().AuthorInfo().SetUserMeta(authorMeta)

	return nil
}
