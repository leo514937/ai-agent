package retrieval

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 从请求参数中拿到 doc，包装成 items

type SpecifiedDocRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewSpecifiedDocRecallLogic(name string, config map[string]string) *SpecifiedDocRecallLogic {
	res := &SpecifiedDocRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.RecallFunc = res.recall

	return res
}

func (r *SpecifiedDocRecallLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "retrieval.SpecifiedDocRecallLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	for _, item := range requestCtx.GetBizContext().GetAssignmentDocs() {
		// 用户暂存或者用户上传的 docId 为 int64 类型
		docId, err := util.String2Int64(item.GetDocId())
		if err != nil {
			constant.DataOutputNodeLog.Errorf(logCtx, "docId %s parse error: %v", item.GetDocId(), err)
			continue
		}
		docType := util.ContentType2DocType(item.GetDocType())
		resList = append(resList, r.genItem(docId, docType).IntoFrameItem(requestCtx))
	}
	r.saveTracing(logCtx, requestCtx, startTime, resList)

	return resList, nil
}

func (r *SpecifiedDocRecallLogic) genItem(docId int64, docType content.DocType_Type) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			RecallSourceInfo: &model.RecallSourceInfo{
				IndexSource: conf.IndexSourceZhihu,
				KbSources:   []conf.KbSource{conf.KbSourceUserSpecified},
			},
		},
		Security: &model.Security{},
	}

	return item
}

func (r *SpecifiedDocRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	startTime int64, resList []*data_frame.ItemData[entities.Item]) {

	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicOutput: []string{fmt.Sprintf("result len:%d", len(resList))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)

	constant.DataOutputNodeLog.Infof(logCtx, fmt.Sprintf("result len:%d", len(resList)))
}
