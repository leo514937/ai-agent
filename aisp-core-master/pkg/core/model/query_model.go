package model

import "git.in.zhihu.com/zhsearch/rucenego/v2/client"

// 条件
type Condition struct {
	FieldName   string      `json:"field_name"`   // 字段名
	FieldValue  interface{} `json:"field_value"`  // 字段值
	OperateType string      `json:"operate_type"` // 运算符
	Boost       float64     `json:"boost"`        // boost
	Weight      float64     `json:"weight"`       // weight
}

// 条件组
type MultiCondition struct {
	Musts     []MultiCondition `json:"musts"`     // AND - 查询除了关注文档是否满足查询条件，还需要额外的计算相关性分数
	Shoulds   []MultiCondition `json:"shoulds"`   // OR
	MustNots  []MultiCondition `json:"must_nots"` // NOT
	Condition *Condition       `json:"condition"` // 条件
}

// 排序条件
type SortCondition struct {
	FiledName string `json:"filed_name"` // 字段名
	Desc      bool   `json:"desc"`       // 是否倒序排序
}

type ContentQuery struct {
	ContentIndexID             int64                  `json:"content_index_id"`
	SelectFields               []string               `json:"select_fields"`
	QueryConditionCode         string                 `json:"query_condition_code"`
	QueryConditionValues       map[string]interface{} `json:"query_condition_values"`
	ShouldQueryConditionValues map[string]interface{} `json:"should_query_condition_values" omitempty:"true"`
	SortConditions             []*SortCondition       `json:"sort_fields"`
	Offset                     int64                  `json:"offset"`
	Limit                      int64                  `json:"limit"`
}

const (
	OperateTypeEq string = "eq"
	OperateTypeGt string = "gt"
	OperateTypeLt string = "lt"
	OperateTypeGe string = "ge"
	OperateTypeLe string = "le"
	OperateTypeIn string = "in"
)

func NewRangeQuery(field string, lower string, includeLower bool, upper string, includeUpper bool) client.Query {
	return client.Query{
		QueryType: client.QueryTypeRange,
		RangeQuery: &client.RangeQuery{
			Field:        field,
			Lower:        lower,
			Upper:        upper,
			IncludeLower: includeLower,
			IncludeUpper: includeUpper,
		},
	}
}

func NewTermQuery(field string, value string, boost float64, weight float64) client.Query {
	realBoost := 1.0
	if boost != 0 {
		realBoost = boost
	}
	var realWeight *float64
	if weight != 0 {
		realWeight = &weight
	}
	return client.Query{
		QueryType: client.QueryTypeTermQuery,
		TermQuery: &client.TermQuery{
			Field:  field,
			Value:  value,
			Boost:  realBoost,
			Weight: realWeight,
		},
	}
}

func NewBoolQuery(musts []client.Query, shoulds []client.Query, mustNots []client.Query) client.Query {
	return client.Query{
		QueryType: client.QueryTypeBooleanQuery,
		BooleanQuery: &client.BooleanQuery{
			Musts:          musts,
			MustNots:       mustNots,
			Shoulds:        shoulds,
			Filters:        nil,
			Boost:          1.0,
			MinShouldMatch: 0,
		},
	}
}
