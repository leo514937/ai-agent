package generate_post

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// 大模型回答后处理节点，用于跟业务相关的结果矫正
const (
	defaultSentFmt = "我已将您的情况反馈给答主「%s」，建议您向他本人做进一步的深入咨询"
	defaultNameFmt = "我是由「%s」设定的智能体"
)

var replaceKeyWords = []string{
	"AI助手",
	"大型语言模型",
	"人工智能语言模型",
	"语言模型",
	"人工智能助手",
	"数字助手",
	"智能助手",
}

type ChatPostLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewChatPostLogic(name string, config map[string]string) *ChatPostLogic {
	res := &ChatPostLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.chatPost

	return res
}

func (c *ChatPostLogic) chatPost(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "generate_post.ChatPostLogic.chatPost")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	itemList := lo.Flatten(itemLists)

	authorName := requestCtx.GetBizContext().AuthorInfo().UserMeta().GetUserName()

	for _, item := range itemList {
		text := item.GetBizItem().Text

		// 对于包含咨询律师和建议律师的句子，统一替换成默认句式
		re := regexp.MustCompile(`[。？！.?!]`)
		sentences := re.Split(text, -1)
		var needReplaceSentences []string
		for _, sentence := range sentences {
			if (strings.Contains(sentence, "咨询") && strings.Contains(sentence, "律师")) ||
				(strings.Contains(sentence, "建议") && strings.Contains(sentence, "律师")) {
				needReplaceSentences = append(needReplaceSentences, sentence)
			}
		}
		for _, sentence := range needReplaceSentences {
			text = strings.ReplaceAll(text, sentence, fmt.Sprintf(defaultSentFmt, authorName))
		}

		// 对于包含特殊关键词的，统一替换成默认句式
		re = regexp.MustCompile(`[。？！，.?!,]`)
		sentences = re.Split(text, -1)
		needReplaceSentences = []string{}
		for _, sentence := range sentences {
			for _, keyword := range replaceKeyWords {
				if strings.Contains(sentence, keyword) {
					needReplaceSentences = append(needReplaceSentences, sentence)
				}
			}
		}
		for _, sentence := range needReplaceSentences {
			text = strings.ReplaceAll(text, sentence, fmt.Sprintf(defaultNameFmt, authorName))
		}

		item.GetBizItem().Text = text
	}

	return itemList, nil
}
