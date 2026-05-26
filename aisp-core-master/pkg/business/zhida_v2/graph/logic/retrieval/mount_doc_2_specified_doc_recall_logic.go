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
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 获取当前挂载或历史挂载doc，转换为召回items

type MountDoc2SpecifiedDocRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewMountDoc2SpecifiedDocRecallLogic(name string, config map[string]string) *MountDoc2SpecifiedDocRecallLogic {
	res := &MountDoc2SpecifiedDocRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.RecallFunc = res.convertSpecifiedRecall

	return res
}

func (r *MountDoc2SpecifiedDocRecallLogic) convertSpecifiedRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "retrieval.ConvertSpecifiedDocRecallLogic.convertSpecifiedRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	universalKnowledgeBaseType := enums.KnowledgeBaseTypeCurrDoc
	docIdEntityArr := requestCtx.GetBizContext().GetCurrReferenceMount().GetMountDocs()
	if len(docIdEntityArr) == 0 {
		docIdEntityArr = requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountDocs()
		universalKnowledgeBaseType = enums.KnowledgeBaseTypeHistoryDoc
	}

	for _, docIdEntity := range docIdEntityArr {
		docType := util.ContentType2DocType(docIdEntity.GetDocType())
		resList = append(resList, r.genItem(docIdEntity.GetDocId(), docType, universalKnowledgeBaseType).IntoFrameItem(requestCtx))
	}
	r.saveTracing(logCtx, requestCtx, startTime, resList)

	return resList, nil
}

func (r *MountDoc2SpecifiedDocRecallLogic) genItem(docId int64, docType content.DocType_Type, bizBaseType enums.KnowledgeBaseType) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			RecallSourceInfo: &model.RecallSourceInfo{
				UniversalKnowledgeBaseType: bizBaseType,
				IndexSource:                conf.IndexSourceZhihu,
				KbSources:                  []conf.KbSource{conf.KbSourceUserSpecified},
			},
		},
		Security: &model.Security{},
	}

	return item
}

func (r *MountDoc2SpecifiedDocRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
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
