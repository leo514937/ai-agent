package prompt

import (
	"context"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// QueryPromptBaseLogic 从OriginQueryPromptLogic copy的，baseLogic类型
// input[0]: queryText string
// input[1]: 召回的结果 zhihaitu_conf.ZagKeyRetrieveMergeItems
// output[0]: prompt []*dto.ChatRequestMessage
type QueryPromptBaseLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	promptService prompt.PromptMapperService
}

func NewQueryPromptBaseLogic(name string, config map[string]string) *QueryPromptBaseLogic {
	res := &QueryPromptBaseLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),

		promptService: prompt.DefaultPromptMapperService,
	}
	res.RealDoFunc = res.queryPrompt
	return res
}

func (o *QueryPromptBaseLogic) queryPrompt(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "buildOriginQueryPrompt",
	})

	systemPromptId := requestCtx.GetBizContext().GetLogicConfig(o.GetName(), conf.ConfigSystemPromptID)
	userPromptId := requestCtx.GetBizContext().GetLogicConfig(o.GetName(), conf.ConfigUserPromptID)
	knowledgeBasePromptId := requestCtx.GetBizContext().GetLogicConfig(o.GetName(), conf.ConfigKnowledgebasePromptID)
	promptNamespace := requestCtx.GetBizContext().GetLogicConfig(o.GetName(), conf.ConfigPromptNameSpace)

	query, _ := requestCtx.DataMap().GetString(ctx, o.GetInputName(0))
	inputRetrieveItems, ok := requestCtx.DataMap().GetObjMap(ctx, o.GetInputName(1))

	retrieveItems := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	if ok {
		retrieveItems = inputRetrieveItems.([]*rpc.OutSiteSearchRecallAnswerResult)
	}

	messages := make([]*dto.ChatRequestMessage, 0)
	systemPrompt := o.systemPrompt(ctx, systemPromptId, promptNamespace)
	if systemPrompt != nil {
		messages = append(messages, systemPrompt)
	}

	userPromptQa := o.userPromptQa(ctx, requestCtx, userPromptId, retrieveItems, promptNamespace, knowledgeBasePromptId)
	if userPromptQa != nil && len(userPromptQa) > 0 {
		messages = append(messages, userPromptQa...)
	}

	messages = append(messages, &dto.ChatRequestMessage{
		Content: query,
		Role:    dto.ChatRequestMessageRoleUser,
	})

	logger.Infof(ctx, "prompt messages:%+v", messages)
	requestCtx.DataMap().SetObjMap(ctx, o.GetOutputName(0), messages)
	return nil
}

func (o *QueryPromptBaseLogic) systemPrompt(ctx context.Context, systemPromptId string, promptNamespace string) *dto.ChatRequestMessage {
	promptTemplate := o.promptService.LoadPromptByApolloNamespace(ctx, systemPromptId, "", "", 0, promptNamespace)
	if promptTemplate == "" {
		return nil
	}

	promptInput := model.PromptInput{}

	systemPrompt, err := model.GenPrompt(&promptInput, promptTemplate, systemPromptId)
	if err != nil {
		log.Errorf(ctx, "OriginQueryPromptLogic buildPrompt template parse error: %+v", err)
		return nil
	}

	systemPromptMessage := &dto.ChatRequestMessage{
		Content: systemPrompt,
		Role:    dto.ChatRequestMessageRoleSystem,
	}
	return systemPromptMessage
}

func (o *QueryPromptBaseLogic) userPromptQa(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	userPromptId string, retrieveItems []*rpc.OutSiteSearchRecallAnswerResult, promptNamespace string, knowledgeBasePromptId string) []*dto.ChatRequestMessage {

	promptTemplate := o.promptService.LoadPromptByApolloNamespace(ctx, userPromptId, "", "", 0, promptNamespace)
	if promptTemplate == "" {
		promptTemplate = "{{.Query}}"
	}

	knowledgeBases := make([]*model.PromptInputKnowledgeBase, 0)
	if len(retrieveItems) > 0 {
		for _, item := range retrieveItems {
			knowledgeBases = append(knowledgeBases, &model.PromptInputKnowledgeBase{
				Text:                      item.Snippet,
				DocTitle:                  item.Name,
				DocPublishedTimeFormatStr: time.Unix(item.PublishedTime, 0).Format("2006-01-02"),
			})
		}
	}

	fullKnowledge := o.getFullKnowledge(ctx, knowledgeBasePromptId, 0, knowledgeBases, promptNamespace)
	promptInput := model.PromptInput{
		FullKnowledge: fullKnowledge,
	}

	userPrompt, err := model.GenPrompt(&promptInput, promptTemplate, userPromptId)
	if err != nil {
		log.Errorf(ctx, "build user prompt template error: %+v", err)
		return nil
	}

	userPromptQa := []*dto.ChatRequestMessage{
		{
			Content: userPrompt,
			Role:    dto.ChatRequestMessageRoleUser,
		},
		{
			Content: "好的，我会参考相关的参考内容来回答您的问题。",
			Role:    dto.ChatRequestMessageRoleAI,
		},
	}
	return userPromptQa
}

func (b *QueryPromptBaseLogic) getFullKnowledge(ctx context.Context, promptId string, memberId int64, knowledgeBases []*model.PromptInputKnowledgeBase, namespace string) string {
	if len(knowledgeBases) == 0 {
		return ""
	}
	promptInput := model.PromptInput{
		KnowledgeBase: knowledgeBases,
	}

	var prompt = b.promptService.LoadPromptByApolloNamespace(ctx, promptId, "", "", memberId, namespace)
	fullKnowledge, err := model.GenPrompt(&promptInput, prompt, promptId)
	if err != nil {
		return ""
	}

	return strings.TrimSpace(fullKnowledge)
}
