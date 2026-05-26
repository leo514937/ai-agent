package recall

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util3 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

type ForwardIndexRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	authorDescService author.AuthorDescService
	kbSource          conf.KbSource
}

func NewForwardIndexRecallLogic(name string, config map[string]string) *ForwardIndexRecallLogic {
	res := &ForwardIndexRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.authorDescService = author.DefaultAuthorDescService
	res.kbSource = conf.KbSource(config[conf.SummaryRecallSource.ToConvert()])
	res.RecallFunc = res.recall

	return res
}

func (r *ForwardIndexRecallLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, r.GetName(), logic_context.CacheSourceByTidb, "recall.ForwardIndexRecallLogic.recall")
	ctx = logicContext.Ctx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&resList))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		// data_frame 有些内部参数无法序列化，所以需要重新创建一下 item
		entities_util.ItemList2DataFrameListAndPush(&logicContext.CacheResp.Resp, requestCtx, &resList)
		return resList, nil
	}

	query := requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent
	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()

	starAuthors := util3.GetStarAuthorIdNames()
	var selfAuthorIds []int64

	if strings.Contains(query, "知乎") || strings.Contains(query, "答主") || strings.Contains(query, "创作者") {
		selfAuthorIds = append(selfAuthorIds, requestCtx.GetBizContext().MemberId())
		for authorId, authorName := range starAuthors {
			// 包含星标创作者的名称
			if authorNameInQuery(query, queryMerge, authorName) {
				// 当成搜自己处理
				selfAuthorIds = append(selfAuthorIds, authorId)
			}
		}
	}

	authorDetailMap := r.authorDescService.BatchGetAuthorDetail(ctx, selfAuthorIds)
	for _, authorId := range selfAuthorIds {
		if authorDetail, ok := authorDetailMap[authorId]; ok && authorDetail.Description != "" && authorDetail.AuthorName != "" && authorNameInQuery(query, queryMerge, authorDetail.AuthorName) {
			item := &entities.Item{
				TimestampMs:          time.Now().UnixMilli(),
				ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
				Type:                 proto.ChatMessageType_TEXT,
				Text:                 authorDetail.Description,
				ItemMeta: &model.ItemMeta{
					IndexDocUniqueId: cast.ToInt64(authorDetail.RecallIndexId),
					Title:            authorDetail.AuthorName,
					Content:          authorDetail.Description,
					AuthorId:         authorId,
					DocType:          content2.DocType_Member,
					RecallSourceInfo: &model.RecallSourceInfo{
						KbSources:  []conf.KbSource{conf.KbSourceAuthorSelf},
						RecallRank: 1,
					},
					Url:            authorDetail.Url,
					AuthorUserMeta: authorDetail,
				},
			}
			publishTime, err := util.Date2TimeStamp(authorDetail.Time)
			if err == nil {
				item.ItemMeta.PublishedTime = publishTime
			}

			resList = append(resList, item.IntoFrameItem(requestCtx))
		}

	}

	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(len(resList)), "rum_forward_recall")
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), "rum_forward_recall"), float64(len(resList)))
	r.saveTracing(requestCtx, selfAuthorIds, startTime, resList)

	constant.DataInputNodeLog.Infof(logicContext.LogCtx, " %s", util.GetJSONIgnoreError(selfAuthorIds))
	constant.DataOutputNodeLog.Infof(logicContext.LogCtx, "%s", util.GetJSONIgnoreError(resList))

	return resList, nil
}

func authorNameInQuery(query string, queryMerge string, authorName string) bool {
	return strings.Contains(query, authorName) || strings.Contains(queryMerge, authorName)
}

func (r *ForwardIndexRecallLogic) saveTracing(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	selfAuthorIds []int64, startTime int64, resList []*data_frame.ItemData[entities.Item]) {

	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{fmt.Sprintf("selfAuthorIds:%s, memberId:%d", util.GetJSONIgnoreError(selfAuthorIds), requestCtx.GetBizContext().MemberId())},
		LogicOutput: []string{fmt.Sprintf("result len:%d", len(resList))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)
}
