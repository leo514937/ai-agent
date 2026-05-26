package finalizer

import (
	"context"
	"encoding/json"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// LastNRecordLogic
// @logicAuthor: wangran
// @logicInfo: 用户在 ai 搜索的 lastn 行为记录，用于推荐等场景，需求：https://one.in.zhihu.com/rfcs/59484
// @logicInput: 0 | query是否通过了所有安全相关的校验 bool
// @logicInput: 1 | queryMerge是否通过了所有安全相关的校验 bool
// @logicInput: 2 | 召回items合并截断后的结果 []*data_frame.ItemData[entities.Item]
type LastNRecordLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewLastNRecordLogic(name string, config map[string]string) *LastNRecordLogic {
	res := &LastNRecordLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.RealDoFunc = res.consume
	res.NeedSignal = true
	return res
}

type LastNRecord struct {
	MemberId         int64     `json:"member_id"`
	SessionId        string    `json:"session_id"`
	Index            int       `json:"index"`
	Query            string    `json:"query"`
	QueryMerge       string    `json:"query_merge"`
	TrafficSource    int       `json:"traffic_source"`
	ClientSource     int       `json:"client_source"`
	RequestTimeStamp int64     `json:"request_timestamp"`
	RelatedItems     []itemKey `json:"related_items"`
}
type itemKey struct {
	DocId   int64 `json:"doc_id"`
	DocType int   `json:"doc_type"`
}

var validBizTypes = []string{
	proto.ChatType_ZHIDA_TAB.String(),
	proto.ChatType_ZHIDA_V2.String(),
	proto.ChatType_ZHIDA_AGENT.String(),
	proto.ChatType_DISCOVER_TAB.String(),
}

func (l *LastNRecordLogic) consume(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "finalizer.TracingRecordLogic.consume")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogMemberId(requestCtx.GetBizContext().MemberId()))

	requestContext := requestCtx.GetBizContext()

	// 执行 case 模式下不落 lastn
	if requestContext.GetRunCaseConfig().IsOpen {
		return nil
	}

	// 限制只要直答场景
	if !util.StringInSlice(requestContext.GetBizType(), validBizTypes) {
		return nil
	}

	// 限制主动直答入口，没有命中安全拦截
	querySecurityAllPassed, _ := requestCtx.DataMap().GetBool(logCtx, l.GetInputName(0))
	queryMergeSecurityAllPassed, _ := requestCtx.DataMap().GetBool(logCtx, l.GetInputName(1))
	if requestContext.RequestHeader().GetTrafficSource() != proto.TrafficSource_zhida || !querySecurityAllPassed || !queryMergeSecurityAllPassed {
		return nil
	}

	memberId := requestContext.MemberId()
	sessionId := requestContext.GetSessionId()
	index := len(requestContext.GetRealHistoryDialogue())
	query := requestContext.RequestInfo().GetMessage().GetText()
	queryMerge := requestContext.GetQueryMergeText()
	trafficSource := requestContext.RequestHeader().GetTrafficSource()
	clientSource := requestContext.RequestHeader().GetClientSource()
	requestTimeStamp := requestContext.RequestMessage().GetTimestampMs()
	recallResult, recallOk := requestCtx.DataMap().GetObjMap(logCtx, l.GetInputName(2))

	var relatedItems = make([]itemKey, 0)
	if recallOk {
		recallCardItems, _ := recallResult.([]*data_frame.ItemData[entities.Item])
		for _, item := range recallCardItems {
			if item.GetBizItem().GetItemMeta().IsNotAllowSend {
				continue
			}

			docType := item.GetBizItem().GetItemMeta().DocType
			if docType == content.DocType_Text || docType == content.DocType_Link {
				continue
			}

			if docType == content.DocType_Answer || docType == content.DocType_Article {
				relatedItems = append(relatedItems, itemKey{
					DocId:   item.GetBizItem().GetItemMeta().DocId,
					DocType: int(docType),
				})
			}
			if docType == content.DocType_Member {
				relatedItems = append(relatedItems, itemKey{
					DocId:   item.GetBizItem().GetItemMeta().AuthorId,
					DocType: int(docType),
				})
			}
		}
	}

	if util.IsMillisecond(requestTimeStamp) {
		requestTimeStamp = requestTimeStamp / 1000
	}

	lastNRecord := &LastNRecord{
		MemberId:         memberId,
		SessionId:        util.Int64String(sessionId),
		Index:            index,
		Query:            util.UnicodeSubstr(query, 0, 1000),
		QueryMerge:       util.UnicodeSubstr(queryMerge, 0, 1000),
		TrafficSource:    int(trafficSource),
		ClientSource:     int(clientSource),
		RequestTimeStamp: requestTimeStamp,
		RelatedItems:     relatedItems[0:util2.Min(len(relatedItems), 20)],
	}

	// 发送 kafka 消息，由 ubs lastN 消费
	kafkaErr := l.sendKafka(ctx, lastNRecord)
	if kafkaErr != nil {
		log.WithError(ctx, kafkaErr).Error(ctx, "send kafka failed")
	}
	return kafkaErr
}

func (l *LastNRecordLogic) sendKafka(ctx context.Context, lastNRecord *LastNRecord) error {
	lastNRecordJson := lo.Must(json.Marshal(lastNRecord))

	producer, err := kafka.GetProducer(context.Background(), string(macro.LastNSearchActivity))
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "get producer failed:%s", macro.LastNSearchActivity)
		return err
	}

	newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 5*time.Second)
	defer cancel()

	return producer.AsyncSend(newCtx, &kafka.ProducerMessage{
		Value: lastNRecordJson,
	})
}
