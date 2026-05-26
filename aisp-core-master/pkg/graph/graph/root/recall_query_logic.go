package root

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 召回服务接受 query，此 query 同 queryMerge

type RecallQueryLogic struct {
	*framework.GetListLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewRecallQueryLogic(name string, config map[string]string) *RecallQueryLogic {
	l := &RecallQueryLogic{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	l.GetListFunc = l.genQuery
	l.BizNodeType = "request"
	return l
}

func (l *RecallQueryLogic) genQuery(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.UserMessageLogic.userMessage", log.Tags{
		"aisp.member_id": cast.ToString(requestCtx.GetBizContext().MemberId()),
	})
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	requestMessage := requestCtx.GetBizContext().RequestMessage()

	item := entities.ItemFromMessage(requestMessage)
	frameItem := item.IntoFrameItem(requestCtx)
	requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent = requestMessage.Text
	requestCtx.GetBizContext().Tracing().Query = item.Text
	requestCtx.GetBizContext().SetQueryMerge(item)

	resList := []*data_frame.ItemData[entities.Item]{
		frameItem,
	}

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(requestCtx.GetBizContext().RequestMessage()))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", item.Text)

	return resList, nil
}
