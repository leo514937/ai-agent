package knowledge_base

import (
	"context"
	"math"
	"strconv"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
)

// TODO: 优化支持按分数排序。可参考 rucene 文档：https://wiki.in.zhihu.com/pages/viewpage.action?pageId=170560308
func BuildRuceneQueryRequest(_ context.Context, condition *model.MultiCondition, path string, index string, storeFields []string) *model.RuceneSearchRequest {
	// 构建查询条件
	queries := make([]client.Query, 0)
	if condition != nil {
		ruceneClientQuery := buildRuceneClientQuery(condition)
		if ruceneClientQuery.QueryType != client.QueryTypeUnknown {
			queries = append(queries, ruceneClientQuery)
		}
	}

	booleanQuery := &client.BooleanQuery{
		Musts:   queries,
		Shoulds: []client.Query{},
		Filters: []client.Query{},
		Boost:   1.0,
	}

	queryDef := client.Query{
		QueryType:    client.QueryTypeBooleanQuery,
		BooleanQuery: booleanQuery,
	}

	ruceneSearchRequest := &model.RuceneSearchRequest{
		RucenePath:  path,
		Index:       index,
		QueryFields: storeFields,
		QueryDef:    queryDef,
	}

	return ruceneSearchRequest
}

func buildRuceneClientQuery(condition *model.MultiCondition) client.Query {
	if condition.Condition == nil && len(condition.Musts) == 0 && len(condition.Shoulds) == 0 && len(condition.MustNots) == 0 {
		return client.Query{QueryType: client.QueryTypeUnknown}
	}

	mustQueries := make([]client.Query, 0)
	shouldQueries := make([]client.Query, 0)
	mustNotQueries := make([]client.Query, 0)

	if condition.Condition != nil {
		switch condition.Condition.OperateType {
		case model.OperateTypeEq:
			return model.NewTermQuery(condition.Condition.FieldName, util.Strval(condition.Condition.FieldValue), condition.Condition.Boost, condition.Condition.Weight)
		case model.OperateTypeGt:
			return model.NewRangeQuery(condition.Condition.FieldName, util.Strval(condition.Condition.FieldValue), false, strconv.FormatInt(math.MaxInt64, 10), true)
		case model.OperateTypeGe:
			return model.NewRangeQuery(condition.Condition.FieldName, util.Strval(condition.Condition.FieldValue), true, strconv.FormatInt(math.MaxInt64, 10), true)
		case model.OperateTypeLt:
			return model.NewRangeQuery(condition.Condition.FieldName, "0", true, util.Strval(condition.Condition.FieldValue), false)
		case model.OperateTypeLe:
			return model.NewRangeQuery(condition.Condition.FieldName, "0", true, util.Strval(condition.Condition.FieldValue), true)
		case model.OperateTypeIn:
			values := strings.Split(condition.Condition.FieldValue.(string), ",") // demo: a,b,c
			for _, value := range values {
				shouldQueries = append(shouldQueries, model.NewTermQuery(condition.Condition.FieldName, value, condition.Condition.Boost, condition.Condition.Weight))
			}
			return model.NewBoolQuery(mustQueries, shouldQueries, mustNotQueries)
		}
	}

	if len(condition.Musts) > 0 {
		for i := range condition.Musts {
			query := buildRuceneClientQuery(&condition.Musts[i])
			if query.QueryType != client.QueryTypeUnknown {
				mustQueries = append(mustQueries, query)
			}
		}
	}
	if len(condition.Shoulds) > 0 {
		for i := range condition.Shoulds {
			query := buildRuceneClientQuery(&condition.Shoulds[i])
			if query.QueryType != client.QueryTypeUnknown {
				shouldQueries = append(shouldQueries, query)
			}
		}
	}
	if len(condition.MustNots) > 0 {
		for i := range condition.MustNots {
			query := buildRuceneClientQuery(&condition.MustNots[i])
			if query.QueryType != client.QueryTypeUnknown {
				mustNotQueries = append(mustNotQueries, query)
			}
		}
	}

	return model.NewBoolQuery(mustQueries, shouldQueries, mustNotQueries)
}
