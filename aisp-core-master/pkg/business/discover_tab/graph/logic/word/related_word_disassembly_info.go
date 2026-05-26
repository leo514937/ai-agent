package word

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word/word_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/suggest_query_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 相关词 拆解请求信息为知乎站内内容

// RelatedWordDisassemblyInfoLogic 相关词 拆解请求信息为知乎站内内容
type RelatedWordDisassemblyInfoLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	allowDocTypes []proto.DocType
}

func NewRelatedWordDisassemblyInfoLogic(name string, config map[string]string) *RelatedWordDisassemblyInfoLogic {
	res := &RelatedWordDisassemblyInfoLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.allowDocTypes = []proto.DocType{proto.DocType_ANSWER}
	res.MappingFunc = res.doHandle
	return res
}

func (l *RelatedWordDisassemblyInfoLogic) doHandle(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.RelatedWordDisassemblyInfoLogic.doHandle")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))
	logger := log.WithField(ctx, "func", "RelatedWordDisassemblyInfoLogic.doHandle")
	if proto.SuggestQueriesType_ASK_AGAIN_RELATED != requestCtx.GetBizContext().GetSuggestQueriesType() {
		logger.Warnf(ctx, "suggestQueriesType is not ASK_AGAIN_RELATED. suggestQueriesType: %v", requestCtx.GetBizContext().GetSuggestQueriesType())
		requestCtx.GetBizContext().SetLogicConfig(suggest_query_conf.RelatedWordChatGenerateLogic, conf.ChatDisable, cast.ToString(true))
		return []*data_frame.ItemData[entities.Item]{}, nil
	}
	if !lo.Contains(l.allowDocTypes, requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocType()) {
		logger.Warnf(ctx, "docType is not allowed. docType: %v", requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocType())
		requestCtx.GetBizContext().SetLogicConfig(suggest_query_conf.RelatedWordChatGenerateLogic, conf.ChatDisable, cast.ToString(true))
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	return []*data_frame.ItemData[entities.Item]{
		l.genItem(
			requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocId(),
			word_util.WordDocType2DocType(requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocType()),
			conf.ZSearchRecallConfig{
				IndexLevel: conf.IndexLevel0,
				OrderGroup: 0,
			}, 0.0,
		).IntoFrameItem(requestCtx),
	}, nil
}

func (l *RelatedWordDisassemblyInfoLogic) genItem(docId int64, docType content.DocType_Type, recallConfig conf.ZSearchRecallConfig, score float64) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 "",
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			Content: "",
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallerName: l.GetName(),
				IndexSource:  conf.IndexSourceZhihu,
				IndexLevel:   recallConfig.IndexLevel,
				RecallScore:  score,
				OrderGroup:   recallConfig.OrderGroup,
				KbSources:    []conf.KbSource{conf.KbSourceZhihu},
			},
		},
		Security: &model.Security{},
	}

	return item
}
