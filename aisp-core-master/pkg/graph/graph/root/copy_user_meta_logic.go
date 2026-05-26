package root

import (
	"context"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// CopyUserMetaLogic 把用户信息copy到reqContext。这个算子没有输入，应该是第一个执行的算子
// @logicAuthor: keyan01@zhihu.com
// @logicInfo: 把用户信息copy到reqContext
// @logicInput: 无
// @logicOutput: 0|当前的对话query *model.DialogRecord
// @logicOutput: 1|query文本 string
// @logicOutput: 2|memberId int64
// @logicOutput: 3|scene string
// @logicOutput: 4|sessionId string
// @logicConfig: api|api名字
type CopyUserMetaLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewCopyUserMetaLogic(name string, config map[string]string) *CopyUserMetaLogic {
	res := &CopyUserMetaLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.RealDoFunc = res.copyUserMeta
	res.NeedSignal = true
	return res
}

func (t *CopyUserMetaLogic) copyUserMeta(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	reqInfo := requestCtx.GetBizContext().RequestInfo()
	requestCtx.DataMap().SetObjMap(ctx, t.GetOutputName(0), requestCtx.GetBizContext().GetCurrentDialogue().Query)
	requestCtx.DataMap().SetString(ctx, t.GetOutputName(1), strings.TrimSpace(reqInfo.GetMessage().GetText()))
	requestCtx.DataMap().SetInt64(ctx, t.GetOutputName(2), reqInfo.GetMemberId())
	requestCtx.DataMap().SetString(ctx, t.GetOutputName(3), requestCtx.GetBizContext().Scenes())
	requestCtx.DataMap().SetString(ctx, t.GetOutputName(4), reqInfo.GetSessionId())
	return nil
}
