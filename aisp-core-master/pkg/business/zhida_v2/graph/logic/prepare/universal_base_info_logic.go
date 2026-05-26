package prepare

import (
	"context"
	"encoding/json"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/apollo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 挂载知识库大类 meta 信息

type UniversalBaseInfoLogic struct {
	*logic.PreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.UniversalKnowledgeBaseInfo]
}

func NewUniversalBaseInfoLogic(name string, config map[string]string) *UniversalBaseInfoLogic {
	res := &UniversalBaseInfoLogic{
		PreparerLogicDecorator: logic.NewPreparerLogicDecorator[entities.RequestContext, entities.User, entities.Item, []*model.UniversalKnowledgeBaseInfo](name, config),
	}
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

func (m *UniversalBaseInfoLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) ([]*model.UniversalKnowledgeBaseInfo, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.UniversalBaseInfoLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	startTime := time.Now().UnixMilli()

	var result []*model.UniversalKnowledgeBaseInfo
	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(m.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", m.GetName())
		return result, nil
	}

	var knowledgeBaseTypeDescription = make(map[string]string)
	err := json.Unmarshal([]byte(apollo.GetString(macro.UniversalKbDescription, "")), &knowledgeBaseTypeDescription)
	if err != nil {
		return result, err
	}

	knowledgeBaseTypes := requestCtx.GetBizContext().GetKnowledgeBases()
	for _, knowledgeBaseType := range knowledgeBaseTypes {
		knowledgeBaseTypeName := enums.KnowledgeBaseTypeNameMap[knowledgeBaseType]
		description := knowledgeBaseTypeDescription[knowledgeBaseTypeName]
		bizType := enums.KnowledgeBaseTypeBizTypeMap[knowledgeBaseType]
		if description != "" {
			result = append(result, &model.UniversalKnowledgeBaseInfo{
				KnowledgeBaseName:        knowledgeBaseTypeName,
				KnowledgeBaseDescription: description,
				KnowledgeBaseType:        bizType,
			})
		}
	}

	// 保存tracing
	m.saveTracing(startTime, knowledgeBaseTypes, result, requestCtx)

	return result, nil
}

func (m *UniversalBaseInfoLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], baseInfo []*model.UniversalKnowledgeBaseInfo) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.UniversalBaseInfoLogic.realMergeUser")
	defer span.Finish()

	requestCtx.GetBizContext().SetUniversalKnowledgeBaseInfo(baseInfo)
	return nil
}

func (m *UniversalBaseInfoLogic) saveTracing(startTime int64, kbTypes []proto.KnowledgeBaseType, result []*model.UniversalKnowledgeBaseInfo, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   m.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(kbTypes)},
		LogicOutput: []string{util.GetJSONIgnoreError(result)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(m.GetName(), logicTracing)
}
