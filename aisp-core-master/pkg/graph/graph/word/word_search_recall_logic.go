package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 搜索词召回

type WordSearchRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK int
}

func NewWordSearchRecallLogic(name string, config map[string]string) *WordSearchRecallLogic {
	res := &WordSearchRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认召回最多30个
	res.topK = 30
	res.RecallFunc = res.searchRecall
	return res
}

func (b *WordSearchRecallLogic) searchRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordSearchRecallLogic.searchRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	// 调用猜你想搜词接口
	guessWords, err := rpcImpl.DefaultGuessThriftRpcService.GetUserGuessQueries(
		ctx, int32(proto.QueryType_GUESS_WORD),
		user.GetBizUser().GetMemberId(),
		requestCtx.GetBizContext().RequestInfo().GetMessage().GetMessageId())
	if err != nil {
		return []*data_frame.ItemData[entities.Item]{}, err
	}

	// 返回词
	var frameItem []*data_frame.ItemData[entities.Item]
	for _, guessWord := range guessWords {
		queryItem := entities.ItemFromQuery(&proto.Query{
			Id:        guessWord.SourceId,
			Query:     guessWord.Word,
			QueryType: proto.QueryType_GUESS_WORD,
		}, -1, macro.CensorTypeMap[proto.QueryType_PARAGRAPH])
		frameItem = append(frameItem, queryItem.IntoFrameItem(requestCtx))
	}

	return frameItem, nil
}
