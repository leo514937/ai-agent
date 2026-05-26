package prompt

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type BuildDigitalAuthorPromptLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewBuildDigitalAuthorPromptLogic(name string, config map[string]string) *BuildDigitalAuthorPromptLogic {
	res := &BuildDigitalAuthorPromptLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping

	return res
}

func (b *BuildDigitalAuthorPromptLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prompt.BuildDigitalAuthorPromptLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(itemList))

	promptTemp := "{{.Query}}"
	if promptTempReal := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPrompt); promptTempReal != "" {
		promptTemp = promptTempReal
	}
	promptId := "1003"
	if promptIdReal := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptID); promptIdReal != "" {
		promptId = promptIdReal
	}

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "buildPrompt",
	})

	query := requestCtx.GetBizContext().RequestMessage().GetText()

	index := 1
	var knowledge []string
	for _, item := range itemList {
		bizItem := item.GetBizItem()
		if bizItem.ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk {
			knowledge = append(knowledge, fmt.Sprintf("%d. %s", index, bizItem.Text))
		}
		index++
	}

	promptInput := model.PromptInput{
		Query:     query,
		Knowledge: strings.Join(knowledge, "\n\n"),
	}

	if userMeta := requestCtx.GetBizContext().AuthorInfo().UserMeta(); userMeta != nil {
		promptInput.Topic = userMeta.GetFinalSkilledAnswer()
		promptInput.AuthorName = userMeta.GetUserName()
	}

	prompt, err := model.GenPrompt(&promptInput, promptTemp, promptId)
	if err != nil {
		log.Errorf(ctx, "BuildPromptLogic buildPrompt template parse error: %+v", err)
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	logger.Debugf(ctx, "query prompt:%s", prompt)
	item := entities.ItemWithTextAndType(prompt, entities.ChatMappingTypeQueryPrompt)
	frameItem := item.IntoFrameItem(requestCtx)

	return []*data_frame.ItemData[entities.Item]{frameItem}, nil
}
