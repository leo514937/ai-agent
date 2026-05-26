package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 段落词召回

type WordParagraphRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK          int
	tagRecallTopK int32
	client        rpc.ContentCoreRPC
}

func NewWordParagraphRecallLogic(name string, config map[string]string) *WordParagraphRecallLogic {
	res := &WordParagraphRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认最多召回100个
	res.topK = 100
	res.tagRecallTopK = 20
	res.client = rpcImpl.NewContentCoreRPCImpl()
	res.RecallFunc = res.paragraphRecall
	return res
}

func (l *WordParagraphRecallLogic) paragraphRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordParagraphRecallLogic.paragraphRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithField(ctx, "paragraphRecall", "")

	extraInfo := requestCtx.GetBizContext().GetExtraInfo()
	if extraInfo == nil {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	err := model.CheckExtraInfoByDocParagraph(extraInfo)
	if err != nil {
		logger.Warnf(ctx, "CheckExtraInfoByDocParagraph Err => %v", err)
		return []*data_frame.ItemData[entities.Item]{}, nil
	}
	docQaExtraInfo := extraInfo.GetDocQaExtraInfo()
	words := l.client.BatchGetStructuredSegmentsByContentIDs(ctx,
		model.NewContentWithContentType(docQaExtraInfo.GetDocId(), docQaExtraInfo.GetContentType()),
		docQaExtraInfo.GetParagraphs(),
	)
	if words == nil || len(words) == 0 {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 返回词
	var frameItem []*data_frame.ItemData[entities.Item]
	for _, word := range words {
		query := entities.ItemFromQuery(&proto.Query{
			Id:        word.ID,
			Query:     word.Word,
			QueryType: proto.QueryType_PARAGRAPH,
		}, 0, macro.CensorTypeMap[proto.QueryType_PARAGRAPH])
		frameItem = append(frameItem, query.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}
