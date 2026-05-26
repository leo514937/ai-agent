package tracing_log

import (
	"context"
	"errors"
	"sort"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"github.com/samber/lo"
)

type TracingLogService interface {
	GetLogTracingRuceneCondition(ctx context.Context, logRucene *model.LogRucene) *model.MultiCondition
	SearchRucene(ctx context.Context, params *model.LogRucene) ([]*model.LogRucene, error)
}

type TracingLogServiceImpl struct {
	qpRpc     rpc.QueryProfileRpc
	ruceneRpc rpc.RuceneServiceRPC
}

var (
	DefaultTracingLogService TracingLogService
)

func init() {
	DefaultTracingLogService = newTracingLogService()
}

func newTracingLogService() *TracingLogServiceImpl {
	return &TracingLogServiceImpl{
		qpRpc:     impl.DefaultQpImpl,
		ruceneRpc: rpc.NewRuceneServiceRPC(8000 * time.Millisecond),
	}
}

func (t *TracingLogServiceImpl) SearchRucene(ctx context.Context, params *model.LogRucene) ([]*model.LogRucene, error) {
	condition := t.GetLogTracingRuceneCondition(ctx, params)
	if len(condition.Musts) == 0 {
		return []*model.LogRucene{}, errors.New("empty condition")
	}

	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, model.Path, model.Index, macro.LogTracingStoreFields)

	return t.searchRuceneDoc(ctx, ruceneQueryRequest)
}

func (t *TracingLogServiceImpl) searchRuceneDoc(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest) ([]*model.LogRucene, error) {
	var result = make([]*model.LogRucene, 0)
	orderField := macro.TracingFieldRequestTimeMs // 二级排序字段，相同匹配分数情况下，按照时间倒序
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               10000, // 最多返回10000条
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        macro.LogTracingStoreFields,
		TransportTimeoutMs: 8000,
		EarlyTerminate:     1000000,
		Score2Field:        &orderField,
	}

	resp, err := t.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.Path, model.Index, queryRequest)
	if err != nil || resp == nil {
		return result, err
	}

	for _, item := range resp.Hits {
		result = append(result, &model.LogRucene{
			MemberId:       item.StoreFields.GetInt64(macro.TracingFieldMemberId),
			SessionId:      item.StoreFields.GetString(macro.TracingFieldSessionId),
			MessageId:      item.StoreFields.GetString(macro.TracingFieldMessageId),
			RespMessageId:  item.StoreFields.GetString(macro.TracingFieldRespMessageId),
			Query:          item.StoreFields.GetString(macro.TracingFieldQuery),
			Response:       []string{item.StoreFields.GetString(macro.TracingFieldResponse)},
			RequestTimeMs:  item.StoreFields.GetInt64(macro.TracingFieldRequestTimeMs),
			ResponseTimeMs: item.StoreFields.GetInt64(macro.TracingFieldResponseTimeMs),
			Security:       item.StoreFields.GetStringSlice(macro.TracingFieldSecurity),
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].RequestTimeMs > result[j].RequestTimeMs
	})

	return result, nil
}

func (t *TracingLogServiceImpl) GetLogTracingRuceneCondition(ctx context.Context, params *model.LogRucene) *model.MultiCondition {
	var finalCondition *model.MultiCondition

	// 安全筛选条件
	var securityConditions []model.MultiCondition
	for _, security := range params.Security {
		securityConditions = append(securityConditions,
			model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.TracingFieldSecurity,
					FieldValue:  security,
					OperateType: model.OperateTypeEq,
				},
			})
	}

	// query筛选条件，模糊匹配
	var queryConditions []model.MultiCondition
	if params.Query != "" {
		wordSegments := t.qpRpc.GetQueryKeyWords(ctx, params.Query)
		isMustQuTerms := lo.Filter(wordSegments, func(item *query_profile.QpTerm, _ int) bool {
			return item.IsMust
		})
		for _, wordTerm := range isMustQuTerms {
			word := wordTerm.GetText()
			queryConditions = append(queryConditions, model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.TracingFieldQuerySeg,
					FieldValue:  word,
					OperateType: model.OperateTypeEq,
				},
			})
		}
	}

	// answer筛选条件，模糊匹配
	var answerConditions []model.MultiCondition
	if len(params.Response) == 1 {
		wordSegments := t.qpRpc.GetQueryKeyWords(ctx, params.Response[0])
		isMustQuTerms := lo.Filter(wordSegments, func(item *query_profile.QpTerm, _ int) bool {
			return item.IsMust
		})
		for _, wordTerm := range isMustQuTerms {
			word := wordTerm.GetText()
			answerConditions = append(answerConditions, model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.TracingFieldResponseSeg,
					FieldValue:  word,
					OperateType: model.OperateTypeEq,
				},
			})
		}
	}

	var mustConditions []model.MultiCondition
	// 场景筛选项
	if params.Scene != "" {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldScene,
				FieldValue:  params.Scene,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// memberId 筛选项
	if params.MemberId != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldMemberId,
				FieldValue:  params.MemberId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// 请求 messageId 筛选项
	if params.MessageId != "" {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldMessageId,
				FieldValue:  params.MessageId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// 返回 messageId 筛选项
	if params.RespMessageId != "" {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldRespMessageId,
				FieldValue:  params.RespMessageId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// sessionId 筛选项
	if params.SessionId != "" {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldSessionId,
				FieldValue:  params.SessionId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// traceId 筛选项，为框架层层透传，可进行上下游追溯
	if params.TraceId != "" {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldTraceId,
				FieldValue:  params.TraceId,
				OperateType: model.OperateTypeEq,
			},
		})
	}

	// 请求时间起始
	if params.RequestStartTimeMs != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldRequestTimeMs,
				FieldValue:  params.RequestStartTimeMs,
				OperateType: model.OperateTypeGe,
			},
		})
	}

	// 请求时间截止
	if params.RequestEndTimeMs != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldRequestTimeMs,
				FieldValue:  params.RequestEndTimeMs,
				OperateType: model.OperateTypeLt,
			},
		})
	}

	// 返回时间起始
	if params.ResponseStartTimeMs != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldResponseTimeMs,
				FieldValue:  params.ResponseStartTimeMs,
				OperateType: model.OperateTypeGe,
			},
		})
	}

	// 返回时间截止
	if params.ResponseEndTimeMs != 0 {
		mustConditions = append(mustConditions, model.MultiCondition{
			Condition: &model.Condition{
				FieldName:   macro.TracingFieldResponseTimeMs,
				FieldValue:  params.ResponseEndTimeMs,
				OperateType: model.OperateTypeLt,
			},
		})
	}

	finalCondition = &model.MultiCondition{
		Musts: util.MergeSlices(securityConditions, queryConditions, answerConditions, mustConditions),
	}

	return finalCondition
}
