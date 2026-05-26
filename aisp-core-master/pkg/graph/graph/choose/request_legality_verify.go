package choose

import (
	"context"
	"fmt"
	"strings"
	"time"

	apollo "git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 请求合法性校验

type RequestLegalityVerifyLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	wordService word_service.WordMapperService
	redisDao    dao.UserRequestDao
	filterMap   map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool
}

func NewRequestLegalityVerifyLogic(name string, config map[string]string) *RequestLegalityVerifyLogic {
	res := &RequestLegalityVerifyLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
		wordService:         word_service.DefaultWordMapperService,
		redisDao:            impl.DefaultUserRequestDaoImpl,
	}
	res.MergeFunc = res.realMerge
	res.filterMap = map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool{
		macro.IsUnRegisterNotPrefabWord:   res.IsUnRegisterNotPrefabWord,
		macro.IsBlockedUser:               res.IsBlockedUser,
		macro.IsUserQpsOverLimit:          res.IsUserQpsOverLimit,
		macro.IsNotHasKbOrPersonalKbOrDoc: res.IsNotHasKbOrPersonalKbOrDoc,
	}
	// 选择条件边
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (r *RequestLegalityVerifyLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "choose.ExpLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	startTime := time.Now().UnixMilli()
	rules := requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.RequestLegalityRule)
	ruleSlice := strings.Split(rules, ",")

	defaultMessage := apollo.GetString("stream_chat.sec_message", graph_constant.DefaultSecurityRefuseMessage)

	for _, rule := range ruleSlice {
		if filterFunc, ok := r.filterMap[rule]; ok {
			if filterFunc(ctx, requestCtx) {
				msg := &proto.ChatMessage{
					MessageId:   requestCtx.GetBizContext().RespMessageId(),
					TimestampMs: time.Now().UnixMilli(),
					Type:        proto.ChatMessageType_TEXT,
					Text:        defaultMessage,
				}
				item := entities.ItemFromMessageByAnswerAndType(msg, proto.ChatRespType_UNANSWERABLE)
				requestCtx.GetBizContext().SetRequestIllegal(true)
				r.saveTracing(logCtx, rule, false, startTime, requestCtx)
				util.Increment(ctx, macro.CommonStatsPrefix+".request_filter.%s.count", rule)
				log.Infof(ctx, "RequestLegalityVerifyLogic request is blocked. request:%s", util.GetJSONIgnoreError(requestCtx.GetBizContext().RequestInfo()))

				return []*data_frame.ItemData[entities.Item]{item.IntoFrameItem(requestCtx)}, nil
			}
		}
	}

	r.saveTracing(logCtx, rules, true, startTime, requestCtx)
	return lo.Flatten(itemLists), nil
}

func (r *RequestLegalityVerifyLogic) saveTracing(logCtx context.Context, rule string, isPass bool, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{rule},
		LogicOutput: []string{fmt.Sprintf("ispass:%v", isPass)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%s", rule)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", fmt.Sprintf("ispass:%v", isPass))
}

func (r *RequestLegalityVerifyLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "RequestLegalityVerifyLogic.chooseKey")
	defer span.Finish()

	if param.RequestContext.GetBizContext().IsRequestIllegal() {
		return entities.Break
	}
	return entities.Normal
}

// 是否是未登录用户非预置词请求
func (r *RequestLegalityVerifyLogic) IsUnRegisterNotPrefabWord(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	// 登录用户返回 false
	if requestCtx.GetBizContext().MemberId() != 0 {
		return false
	}
	// 判断是否是非预置词请求
	query := requestCtx.GetBizContext().RequestMessage().GetText()
	return !r.wordService.IsPrefabWord(ctx, query)
}

// 是否是黑名单用户
func (r *RequestLegalityVerifyLogic) IsBlockedUser(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	blockMemberIds := apollo.GetStringArray(macro.BlockMemberIdConfigName, ",", []string{})
	return util.StringInSlice(util.Int64String(requestCtx.GetBizContext().MemberId()), blockMemberIds)
}

// 是否是用户请求频率超限
func (r *RequestLegalityVerifyLogic) IsUserQpsOverLimit(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	requestInterval := apollo.GetInt(macro.RequestIntervalSecondsConfigName, 0)
	if requestInterval == 0 || requestCtx.GetBizContext().MemberId() == 0 {
		return false
	}
	return !r.redisDao.GetUserRequestFrequencyLock(ctx, requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().GetBizType(), requestInterval)
}

// 是否包含 指定知识库\指定的docs\指定的个人知识库
func (r *RequestLegalityVerifyLogic) IsNotHasKbOrPersonalKbOrDoc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	if len(requestCtx.GetBizContext().GetAssignmentDocs()) == 0 &&
		len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()) == 0 &&
		len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) == 0 {
		return true
	}
	return false
}
