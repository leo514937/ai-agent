package security

import (
	"context"
	"encoding/json"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// SecurityReviewBaseLogic 安全审核逻辑。 从SecurityReviewLogic copy过来，使用baseLogic，不然目前框架无法把mappingLogic接在consumerLogic之后，所以需要把当前算子重新写成baseLogic
// input[0]：query *model.DialogRecord
// input[1]: respMessage *proto.ChatMessage
// input[2]: redLineAnswer string
// input[3]: faqAnswer string
// output[0]: reviewResult bool
type SecurityReviewBaseLogic struct {
	*logic.BaseLogic[entities.RequestContext]

	FetchFunc     func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*model.ReviewResult, error)
	ItemMergeFunc func(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error
}

func NewSecurityReviewBaseLogic(name string, config map[string]string) *SecurityReviewBaseLogic {

	l := &SecurityReviewBaseLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}

	l.RealDoFunc = l.do
	l.ItemMergeFunc = l.itemMerge

	return l
}

func (u *SecurityReviewBaseLogic) do(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.SecurityReviewBaseLogic.do")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	// query := requestCtx.GetBizContext().GetCurrentDialogue().Query
	var query *model.DialogRecord
	inputQuery, ok := requestCtx.DataMap().GetObjMap(logCtx, u.GetInputName(0))
	if ok {
		query = inputQuery.(*model.DialogRecord)
	}

	respMessage, ok := requestCtx.DataMap().GetObjMap(logCtx, u.GetInputName(1))
	var answer *entities.Item
	if ok {
		answer = entities.ItemFromMessageByAnswer(respMessage.(*proto.ChatMessage))
	}
	redLineAnswer, _ := requestCtx.DataMap().GetString(logCtx, u.GetInputName(2))
	faqAnswer, _ := requestCtx.DataMap().GetString(logCtx, u.GetInputName(3))

	itemList := u.buildQueryAnswer(requestCtx, query, answer)

	var resMap map[data_frame.UniqueId]*model.ReviewResult
	var err error

	err = safe_group.SafeGoWait(u.OriginName(), func() error {
		resMap, err = u.fetch(ctx, requestCtx, itemList, redLineAnswer, faqAnswer)
		return err
	})

	if err != nil {
		log.Error(ctx, requestCtx.GetCommonContext(), u.GetBizNodeType(), u.OriginName(), err)
		return nil
	}

	for _, item := range itemList {
		if res, ok := resMap[*item.GetCommonItem().GetUniqueId()]; ok {
			_ = u.ItemMergeFunc(ctx, item, res)
		}
	}

	return nil
}

func (u *SecurityReviewBaseLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item],
	redLineAnswer string, faqAnswer string) (map[data_frame.UniqueId]*model.ReviewResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.SecurityReviewBaseLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*model.ReviewResult)

	configStr := requestCtx.GetBizContext().GetLogicConfig(u.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "SecurityReviewBaseLogic getConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), u.GetName()))
		return resMap, nil
	}
	securityConfig := conf.SecurityConfig{}
	unmarshalErr := json.Unmarshal([]byte(configStr), &securityConfig)
	if unmarshalErr != nil {
		log.Errorf(ctx, "SecurityReviewBaseLogic getConfig error => unmarshal config error => %s", unmarshalErr)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), u.GetName()))
		return resMap, nil
	}

	sourceId := rpc.RiskCheckSourceId(securityConfig.SourceId)
	chatMappingType := entities.ChatMappingType(securityConfig.ChatMappingType)
	scene := securityConfig.Scene
	sceneContextKey := securityConfig.SceneContextKey
	storeSource := securityConfig.StoreSource
	extraStoreSource := securityConfig.ExtraStoreSource
	setRedLineAnswer := securityConfig.SetRedLineAnswer && (redLineAnswer != "" || faqAnswer != "")
	callSecurityIfExempt := securityConfig.CallSecurityIfExempt // 当需要豁免安全结果时，如果为true，则仍然会调用安全接口，但是会忽略接口结果

	sceneTmp := requestCtx.GetBizContext().GetBizType()
	if len(scene) != 0 {
		sceneTmp = scene
	} else if sceneContextKey != "" {
		sceneNew, ok := requestCtx.DataMap().GetString(logCtx, sceneContextKey)
		if ok {
			sceneTmp = sceneNew
		}
	}
	log.Infof(ctx, "security review, sourceId:%v scene:%v  items: %s", sourceId, sceneTmp, util.GetJSONIgnoreError(items))

	reviewResult := &model.ReviewResult{
		IsAvailable: true,
	}

	if !requestCtx.GetBizContext().GetIsExemptSecurity() {
		reviewResult = CheckItem(ctx, requestCtx, items, sourceId, sceneTmp, chatMappingType, storeSource, extraStoreSource, setRedLineAnswer, false, "")
	} else {
		// 豁免结果，但是仍然调用安全接口
		if callSecurityIfExempt {
			CheckItem(ctx, requestCtx, items, sourceId, sceneTmp, chatMappingType, storeSource, extraStoreSource, setRedLineAnswer, false, "")
		}
	}

	log.StatsdCheckItem(ctx, "SecurityReviewBaseLogic.fetch.all", reviewResult.IsAvailable)
	log.StatsdCheckItem(ctx, "SecurityReviewBaseLogic.fetch."+cast.ToString(sourceId), reviewResult.IsAvailable)

	for _, item := range items {
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = reviewResult
	}
	log.Infof(ctx, "security review, resMap: %s", util.GetJSONIgnoreError(lo.Values(resMap)))

	requestCtx.DataMap().SetBool(logCtx, u.GetOutputName(0), reviewResult.IsAvailable)

	return resMap, nil
}

func (u *SecurityReviewBaseLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *model.ReviewResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "security.SecurityReviewBaseLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetSecurity().ReviewResult = res
	return nil
}

// buildQueryAnswer 这里不需要merge history，CheckItem中会merge
func (u *SecurityReviewBaseLogic) buildQueryAnswer(ctx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query *model.DialogRecord, answer *entities.Item) []*data_frame.ItemData[entities.Item] {
	var items []*data_frame.ItemData[entities.Item]

	items = append(items, entities.ItemFromDialogueRecord(query).IntoFrameItem(ctx))
	if answer != nil {
		items = append(items, answer.IntoFrameItem(ctx))
	}
	return items
}
