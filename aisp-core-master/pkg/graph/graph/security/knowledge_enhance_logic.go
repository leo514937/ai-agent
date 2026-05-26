package security

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	frameworkLog "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type KnowledgeEnhanceLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]

	FetchFunc     func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]string, error)
	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[entities.Item], res []string) error
}

func NewKnowledgeEnhanceLogic(name string, config map[string]string) *KnowledgeEnhanceLogic {
	l := &KnowledgeEnhanceLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	l.MappingFunc = l.fetchA
	l.BizNodeType = "fetch"

	l.FetchFunc = l.fetch
	l.ItemMergeFunc = l.itemMerge
	return l
}

func (k *KnowledgeEnhanceLogic) fetchA(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	var resMap map[data_frame.UniqueId][]string
	var err error

	err = safe_group.SafeGoWait(k.OriginName(), func() error {
		resMap, err = k.FetchFunc(ctx, requestCtx, user, itemList)
		return err
	})

	if err != nil {
		frameworkLog.RecordErrStack(requestCtx.GetCommonContext(), k.GetBizNodeType(), k.OriginName(), err)
		return itemList, nil
	}

	for _, item := range itemList {
		if res, ok := resMap[*item.GetCommonItem().GetUniqueId()]; ok {
			_ = k.ItemMergeFunc(ctx, item, res)
		}
	}

	return itemList, nil
}

func (k *KnowledgeEnhanceLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]string, error) {
	resMap := make(map[data_frame.UniqueId][]string)
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.KnowledgeEnhanceLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	// 豁免安全的，不过知识增强
	if requestCtx.GetBizContext().GetIsExemptSecurity() {
		return resMap, nil
	}

	for _, item := range items {
		knowledgeEnhance, keyword, hit := operation_base.DefaultOperationBaseService.HitKnowledgeEnhance(item.GetBizItem().Text)
		log.StatsdCheckItem(ctx, "KnowledgeEnhanceLogic.fetch.all", !hit)

		if hit {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = []string{knowledgeEnhance}
			log.WithField(ctx, "respMessageId", requestCtx.GetBizContext().RespMessageId()).Infof(ctx, "knowledge enhance:%s", knowledgeEnhance)
			k.saveSecurityTracing(knowledgeEnhance, keyword, requestCtx)
		}
	}
	return resMap, nil
}

func (k *KnowledgeEnhanceLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []string) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.KnowledgeEnhanceLogic.itemMerge")
	defer span.Finish()

	bizItem := item.GetBizItem()
	bizItem.GetSecurity().KnowLedgeEnhance = res
	if res == nil || len(res) == 0 {
		return nil
	}

	bizItem.Text = res[0] + "<用户>" + bizItem.Text

	return nil
}

func (k *KnowledgeEnhanceLogic) saveSecurityTracing(knowledgeEnhance string, keyword string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	securityTracing := &proto.SecurityTracing{
		KnowledgeEnhance:        knowledgeEnhance,
		KnowledgeEnhanceKeyword: keyword,
	}
	securityChan := requestCtx.GetBizContext().ProcessTracing().SecurityTracing
	if len(securityChan) < entities.MaxTracingChanSize {
		securityChan <- securityTracing
	}
}
