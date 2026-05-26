package root

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/spf13/cast"
)

// @logicAuthor: wanghao11
// @logicInfo: 用户输入消息获取并流转

type UserMessageLogic struct {
	*framework.GetListLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewUserMessageLogic(name string, config map[string]string) *UserMessageLogic {
	l := &UserMessageLogic{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	l.GetListFunc = l.userMessage
	l.BizNodeType = "request"
	return l
}

func (l *UserMessageLogic) userMessage(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.UserMessageLogic.userMessage", log.Tags{
		"aisp.message":       requestCtx.GetBizContext().RequestMessage().Text,
		"aisp.message_type":  cast.ToString(requestCtx.GetBizContext().RequestMessage().Type),
		"aisp.message_id":    cast.ToString(requestCtx.GetBizContext().RequestMessage().MessageId),
		"aisp.message_ts_ms": cast.ToString(requestCtx.GetBizContext().RequestMessage().TimestampMs),
		"aisp.member_id":     cast.ToString(requestCtx.GetBizContext().MemberId()),
	})
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	log.Infof(ctx, "UserMessageLogic userMessage user: %+v", user)
	requestMessage := requestCtx.GetBizContext().RequestMessage()

	// 如果存在引用文本，将引用文本加入到 query 之前
	mountTexts := requestCtx.GetBizContext().GetCurrReferenceMount().GetMountTexts()
	if len(mountTexts) > 0 {
		requestMessage.Text = fmt.Sprintf("%s\n%s", strings.Join(mountTexts, "\n"), requestMessage.Text)
	}

	// 如果是机器学习平台请求，解析 klara-tag 标签，清洗输入文本
	if requestCtx.GetBizContext().RequestHeader().GetTrafficSource() == proto.TrafficSource_internal_qa {
		text, klaraTags := parseKlaraTag(requestMessage.Text)
		requestMessage.Text = text
		if klaraTags != "" {
			requestCtx.GetBizContext().SetQueryTags(strings.Split(klaraTags, ","))
		}
	}

	item := entities.ItemFromMessage(requestCtx.GetBizContext().RequestMessage())
	frameItem := item.IntoFrameItem(requestCtx)
	requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent = requestMessage.Text
	requestCtx.GetBizContext().Tracing().Query = item.Text

	resList := []*data_frame.ItemData[entities.Item]{
		frameItem,
	}

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(requestCtx.GetBizContext().RequestMessage()))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", item.Text)

	return resList, nil
}

var klaraTagRegex = regexp.MustCompile(`([\s\S]*)<klara-tag>(.*)</klara-tag>`)

func parseKlaraTag(input string) (string, string) {
	// 解析特定标签后缀
	matches := klaraTagRegex.FindStringSubmatch(input)
	if len(matches) == 3 {
		return strings.TrimSpace(matches[1]), strings.TrimSpace(matches[2])
	}
	return input, ""
}
