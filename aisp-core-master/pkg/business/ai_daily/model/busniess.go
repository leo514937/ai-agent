package model

import (
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type PlayListData struct {
	MostLikeQuestionIDs          []string                            // 热门问题ID
	QuestionIDs                  []string                            // 问题ID
	ThemePairs                   []ThemePair                         // 用户的兴趣数据
	HighDimensionalLabels        []string                            // 用户感兴趣的高维标签词
	HighDimensionalQuestionIDs   []string                            // 用户感兴趣的高维标签词对应的questionID
	Theme2ThemeSimMap            map[string]float64                  // theme间的相似度
	Question2QuestionSimMap      map[string]float64                  // 当天的question之间的相似度
	ViewedQuestionSimMap         map[string]float64                  // 已下发的question与当天的question相似度
	Date                         string                              // 数据日期
	MostLikeDate                 string                              // 兜底数据日期
	Latest7DaysViewedQuestionIDs []string                            // 近7天已读的questionIDs
	Latest3DaysViewedQuestionIDs []string                            // 近3天已读的questionIDs
	HighLabelQuestionDetails     []*RedisQuestionDetail              // 高维标签question详情
	QuestionDetails              []*RedisQuestionDetail              // question详情
	FinalQuestionDetails         []*RedisQuestionDetail              // question最终数据
	HashToken                    string                              // hashToken
	UserID                       int64                               // 查询快照的用户ID
	UserName                     string                              // 用户名称
	SnapShot                     *TableDailySnapshot                 // 已生成的快照
	Response                     *QueryPlaylistResponse              // 响应结果
	IsParseData                  bool                                // 是否解析快照数据
	ContentRegulateMap           map[model.Content]map[string]string // 管控结果
	SecurityRegulateMap          map[string]struct{}                 // 安全侧管控结果
	CardGenerateTime             time.Time                           // 卡片创建时间，统一TiDB和rucene中的时间
}

type ThemePair struct {
	ThemeID   string
	ThemeName string
}
