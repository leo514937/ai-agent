package prompt

import (
	"context"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"golang.org/x/exp/slices"
)

const (
	KnowledgeFormatVersionV1 = "v1"
	KnowledgeFormatVersionV2 = "v2"
)

// BuildPromptLogic 构造 prompt
// @logicAuthor: wanghao11
// @logicInfo: 构造 prompt
// @logicConfig: conf.ConfigPromptType | prompt类型，system or user
// @logicConfig: conf.ConfigPrompt | 默认prompt
// @logicConfig: conf.ConfigPromptID | 默认promptId
// @logicConfig: conf.ConfigPromptIdConcise | 简洁模式promptId
// @logicConfig: conf.ConfigPromptIdElaborated | 深入模式promptId
// @logicConfig: conf.ConfigPromptKnowledgeFormatVersion | 知识库格式版本
// @logicConfig: conf.ConfigPromptKnowledgePromptId | 知识库promptId
type BuildPromptLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
	promptType    entities.ChatMappingType
	businessStage proto.BusinessStage
	promptService prompt.PromptMapperService
}

func NewBuildPromptLogic(name string, config map[string]string) *BuildPromptLogic {
	res := &BuildPromptLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildPrompt

	promptType, _ := util.String2Int(config[conf.ConfigPromptType])
	if entities.ChatMappingType(promptType) == entities.ChatMappingTypeSystemPrompt {
		res.promptType = entities.ChatMappingTypeSystemPrompt
	} else {
		res.promptType = entities.ChatMappingTypeQueryPrompt
	}

	businessStage := proto.BusinessStage_GENERATION
	if configBusinessStage := config[conf.ConfigBusinessStage]; configBusinessStage != "" {
		businessStage = proto.BusinessStage(util2.SafeString2Int64(configBusinessStage, 0))
	}
	res.businessStage = businessStage

	res.promptService = prompt.DefaultPromptMapperService

	return res
}

func (b *BuildPromptLogic) loadPrompt(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], memberID int64) (string, string) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prompt.BuildPromptLogic.loadPrompt")
	defer span.Finish()

	promptTemp := "{{.Query}}"
	if promptTempReal := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPrompt); promptTempReal != "" {
		promptTemp = promptTempReal
	}

	promptId := b.loadPromptId(requestCtx)

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "loadPrompt",
	})
	logger.Infof(ctx, "loadPrompt start.")

	if promptId == "" {
		logger.Infof(ctx, "loadPrompt promptID is empty.")
		return promptId, promptTemp
	}
	return promptId, b.promptService.LoadPromptByApollo(ctx, promptId, promptTemp, "", memberID)
}

func (b *BuildPromptLogic) buildPrompt(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "prompt.BuildPromptLogic.buildPrompt")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "buildPrompt",
	})
	log.Infof(ctx, "BuildPromptLogic buildPrompt user: %+v itemLists: %+v", user, itemLists)

	knowledgeFormatVersion := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptKnowledgeFormatVersion)
	// 原始 query items
	sourceQueryItems, isOk := requestCtx.GetCommonContext().GetLogicData(conf.SourceQueryItemLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isOk && sourceQueryItems != nil && len(sourceQueryItems) > 0 {
		itemLists = append(itemLists, sourceQueryItems)
	}

	// 避免空list，先做合并
	itemList := lo.Flatten(itemLists)

	if len(itemList) == 0 {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// span.LogFields(log.Json("itemList", itemList))

	query := ""
	queryID := ""
	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()
	if requestCtx.GetBizContext().GetCurrentDialogue().Query != nil {
		query = requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent
		queryID = requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageId
	}

	// 获得内部知识库 和 外部知识库
	knowledgeBaseRes := b.handleKnowledge(itemLists)
	// 处理合并的知识库
	knowledge := b.mergeKnowledge(knowledgeBaseRes)
	// 处理合并的知识库(包含标题、发布时间、内容)
	var fullKnowledge string
	if knowledgeFormatVersion == KnowledgeFormatVersionV2 {
		promptId := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptKnowledgePromptId)
		fullKnowledge = b.mergeFullKnowledgeV2(ctx, promptId, requestCtx.GetBizContext().MemberId(), knowledgeBaseRes)
	} else {
		fullKnowledge = b.mergeFullKnowledge(knowledgeBaseRes)
	}

	promptInput := model.PromptInput{
		Query:         query,
		QueryMerge:    queryMerge,
		KnowledgeBase: knowledgeBaseRes,
		Knowledge:     knowledge,
		FullKnowledge: fullKnowledge,
	}

	if userMeta := requestCtx.GetBizContext().AuthorInfo().UserMeta(); userMeta != nil {
		promptInput.Topic = userMeta.GetFinalSkilledAnswer()
		promptInput.AuthorName = userMeta.GetUserName()
	}

	memberID := user.GetBizUser().MemberId
	promptId, promptTemp := b.loadPrompt(ctx, requestCtx, memberID)

	span.LogFields(
		log.Message("GenPrompt."),
		log.String("promptID", promptId),
		log.OmittedString("promptString", promptTemp),
		log.OmittedString("prompt.Query", promptInput.Query),
		log.OmittedString("prompt.QueryMerge", promptInput.QueryMerge),
		log.OmittedString("prompt.Knowledge", promptInput.Knowledge),
		log.OmittedString("prompt.Date", promptInput.Date),
		log.OmittedString("prompt.Weekday", promptInput.Weekday),
		log.OmittedString("prompt.Time", promptInput.Time),
		log.OmittedString("prompt.Yesterday", promptInput.Yesterday),
		log.OmittedString("prompt.Tomorrow", promptInput.Tomorrow),
		log.OmittedString("prompt.YesterdayWeekday", promptInput.YesterdayWeekday),
		log.OmittedString("prompt.TommorrowWeekday", promptInput.TommorrowWeekday),
	)

	promptContent, err := model.GenPrompt(&promptInput, promptTemp, promptId)
	if err != nil {
		log.Errorf(ctx, "BuildPromptLogic buildPrompt template parse error: %+v", err)
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// span.LogFields(log.String("prompt", prompt))

	logger.Infof(ctx, "prompt:%s", promptContent)

	item := entities.ItemWithTextAndType(promptContent, b.promptType)
	item.MessageId = queryID
	frameItem := item.IntoFrameItem(requestCtx)

	// span.LogFields(log.Json("frameItem", frameItem))

	resp := []*data_frame.ItemData[entities.Item]{frameItem}

	b.savePromptTracing(logCtx, promptTemp, promptContent, promptInput, requestCtx)
	// span.LogFields(log.Message("BuildPromptLogic buildPrompt done."), log.Items(resp))

	return resp, nil
}

func (b *BuildPromptLogic) handleKnowledge(itemLists [][]*data_frame.ItemData[entities.Item]) []*model.PromptInputKnowledgeBase {
	knowledgeBases := make([]*model.PromptInputKnowledgeBase, 0)

	// 1. recall 结果转成字符串分割
	// 拍平 Items
	recallItems := lo.Map(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) *entities.Item {
		return item.GetBizItem()
	})

	// 2. 取出知识库召回内容 且是标记为可使用的
	filterItems := lo.Filter(recallItems, func(item *entities.Item, index int) bool {
		return item.ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk &&
			item.GetItemMeta() != nil &&
			item.GetItemMeta().GetRecallSourceInfo().Used
	})
	if filterItems == nil || len(filterItems) == 0 {
		return knowledgeBases
	}

	for _, item := range filterItems {
		title := item.GetItemMeta().Title
		// 如果是answer内容 且标题为空 则去取question的title
		if title == "" && item.GetItemMeta().DocType == content.DocType_Answer && item.GetItemMeta().ParentContentInfo != nil {
			title = item.GetItemMeta().ParentContentInfo.GetTitle()
		}

		var knowledgeType int
		if item.ItemMeta.DocType == content.DocType_Answer || item.ItemMeta.DocType == content.DocType_Article || item.ItemMeta.DocType == content.DocType_Paper {
			knowledgeType = model.KnowledgeBaseTypeZhihuAnswerAndArticleAndPaper
		} else if item.ItemMeta.DocType == content.DocType_ZhiDaUserUpload {
			knowledgeType = model.KnowledgeBaseTypeUserUpLoad
		} else if slices.Contains(item.ItemMeta.RecallSourceInfo.KbSources, conf.KbSourceAuthorBge) {
			knowledgeType = model.KnowledgeBaseTypeZhihuAuthor
		} else {
			knowledgeType = model.KnowledgeBaseTypeWeb
		}

		docPublishedTimeFormatStr := ""
		if item.GetItemMeta().PublishedTime > 0 {
			docPublishedTimeFormatStr = time.Unix(item.GetItemMeta().PublishedTime, 0).Format("2006-01-02")
		}
		knowledgeBases = append(knowledgeBases, &model.PromptInputKnowledgeBase{
			Text:                      item.Text,
			IsOutLink:                 item.GetItemMeta().IsOutLink() || item.GetItemMeta().DocType == content.DocType_Link,
			DocTitle:                  title,
			DocPublishedTimeFormatStr: docPublishedTimeFormatStr,
			Type:                      knowledgeType,
			DocType:                   b.getKnowledgeDocTypeName(item.GetItemMeta()),
			AuthorUrl:                 item.ItemMeta.Url,
		})
	}
	return knowledgeBases
}

func (b *BuildPromptLogic) getKnowledgeDocTypeName(itemMeta *model.ItemMeta) string {
	if itemMeta.DocType == content.DocType_Answer {
		return "知乎回答"
	} else if itemMeta.DocType == content.DocType_Article {
		return "知乎文章"
	} else if itemMeta.DocType == content.DocType_Member {
		return "知乎答主"
	} else if itemMeta.DocType == content.DocType_ZhiDaUserUpload {
		return "用户上传文档"
	} else if itemMeta.DocType == content.DocType_Paper {
		contentInfo := itemMeta.ContentInfo
		if contentInfo != nil && contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
			switch contentInfo.GetBizExtDetail().GetPaperBizExt().GetSource() {
			case paper_biz_ext.PaperPublishSource_WeiPu:
				return "维普论文"
			case paper_biz_ext.PaperPublishSource_Arxiv:
				return "arxiv论文"
			}
		}

	}
	return "网页"
}

func (b *BuildPromptLogic) mergeKnowledge(knowledgeBases []*model.PromptInputKnowledgeBase) string {
	var strBuilder strings.Builder
	for i, text := range knowledgeBases {
		cleanedText := strings.ReplaceAll(text.Text, "\n", "")
		strBuilder.WriteString(fmt.Sprintf("%d. %s\n\n", i+1, cleanedText))
	}
	strBuilder.WriteString("\n\n")
	return strBuilder.String()
}

func (b *BuildPromptLogic) mergeFullKnowledge(knowledgeBases []*model.PromptInputKnowledgeBase) string {
	var strBuilder strings.Builder
	for i, text := range knowledgeBases {
		cleanedText := strings.ReplaceAll(text.Text, "\n", "")
		strBuilder.WriteString(
			fmt.Sprintf("## %d. \n### 发布时间: %s\n### 标题: %s\n### 内容: %s\n\n",
				i+1, text.DocPublishedTimeFormatStr, text.DocTitle, cleanedText))
	}
	return strBuilder.String()
}

func (b *BuildPromptLogic) mergeFullKnowledgeV2(ctx context.Context, promptId string, memberId int64, knowledgeBases []*model.PromptInputKnowledgeBase) string {
	if len(knowledgeBases) == 0 {
		return ""
	}
	promptInput := model.PromptInput{
		KnowledgeBase: knowledgeBases,
	}

	var prompt = b.promptService.LoadPromptByApollo(ctx, promptId, "", "", memberId)
	fullKnowledge, err := model.GenPrompt(&promptInput, prompt, promptId)
	if err != nil {
		return ""
	}

	return strings.TrimSpace(fullKnowledge)
}

func (b *BuildPromptLogic) savePromptTracing(logCtx context.Context, promptTemp string, prompt string, input model.PromptInput, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	description := "user prompt"
	if b.promptType == entities.ChatMappingTypeSystemPrompt {
		description = "system prompt"
	}
	promptRecord := &proto.Prompt{
		Stage:         b.businessStage,
		PromptContent: prompt,
		Description:   description,
	}
	promptChan := requestCtx.GetBizContext().ProcessTracing().Prompt
	if len(promptChan) < entities.MaxTracingChanSize {
		promptChan <- promptRecord
	}

	constant.DataInputNodeLog.Infof(logCtx, "prompt temp:%s, input:%s", promptTemp, util.GetJSONIgnoreError(input))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(promptRecord))

}

func (b *BuildPromptLogic) loadPromptId(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	promptId := "1000"
	if promptIdReal := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptID); promptIdReal != "" {
		promptId = promptIdReal
	}
	if requestCtx.GetBizContext().GetChatStyle() == proto.ChatStyle_SIMPLE && requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptIdConcise) != "" {
		promptId = requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptIdConcise)
	}
	if requestCtx.GetBizContext().GetChatStyle() == proto.ChatStyle_THOROUGH && requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptIdElaborated) != "" {
		promptId = requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigPromptIdElaborated)
	}

	return promptId
}
