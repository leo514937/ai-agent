package model

import (
	"encoding/json"
	"strconv"
	"time"
)

type HotContentProducts struct {
	Id                     uint64 `json:"id" borm:"primary_key"`
	PDate                  string `json:"p_date"`
	BayesFirstCategoryName string `json:"bayes_first_category_name" borm:"column:bayes_firstcategory_name"`
	FirstLevelTop          string `json:"first_level_top"`
	SecondLevelTop         string `json:"second_level_top"`
	EntityName             string `json:"entity_name"`
	EntityScore            int64  `json:"entity_score"`
	EntityRank             int64  `json:"entity_rank"`
	EvaluationListJson     string `json:"evaluation_list_json"`
}

func (s *HotContentProducts) TableName() string {
	return "hot_extract_products_ranking_evaluation"
}

type HotContentFilterParams struct {
	Page                   int
	PageSize               int
	BayesFirstCategoryName string
	FirstLevelTop          string
	SecondLevelTop         string
	EntityName             string
	EntityScoreLowerBound  int64
	EntityScoreUpperBound  int64
	PDateStart             string
	PDateEnd               string
}

type HotContentProductScore struct {
	ProductScore int64  `json:"product_score"`
	PDate        string `json:"p_date"`
}

type HotContentSynonymFilterParams struct {
	BayesFirstCategoryName string `json:"bayes_first_category_name"`
	Keyword                string `json:"keyword"`
	CreateUserId           string `json:"create_user_id"`
	Page                   int
	PageSize               int
}

type HotContentProductSynonym struct {
	Id                     uint64    `json:"id" borm:"primary_key"`
	BayesFirstCategoryName string    `json:"bayes_first_category_name"`
	TakeEffectField        string    `json:"take_effect_field"`
	Keyword                string    `json:"keyword"`
	Synonyms               string    `json:"synonyms"`
	CreateUserId           string    `json:"create_user_id"`
	UpdateUserId           string    `json:"update_user_id"`
	StatusCode             int       `json:"status_code"`
	CreatedAt              time.Time `json:"created_at" borm:"readonly"`
	UpdatedAt              time.Time `json:"updated_at" borm:"readonly"`
}

func (s *HotContentProductSynonym) TableName() string {
	return "hot_content_products_synonym"
}

// MarshalJSON Id字段序列化为string，使用uint64时，前端的number接不住2^63-1以上的数值
func (s *HotContentProductSynonym) MarshalJSON() ([]byte, error) {
	type Alias HotContentProductSynonym
	return json.Marshal(&struct {
		Id string `json:"id"`
		*Alias
	}{
		Id:    strconv.FormatUint(s.Id, 10),
		Alias: (*Alias)(s),
	})
}

type StatusCode int

const (
	StatusCodeInit      StatusCode = 0 // 初始化状态
	StatusCodeNotOnline StatusCode = 1 // 未上线
	StatusCodeOnline    StatusCode = 2 // 已上线
	StatusCodeDeleted   StatusCode = 3 // 已删除
)
