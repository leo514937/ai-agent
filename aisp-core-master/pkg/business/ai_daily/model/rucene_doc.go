package model

import "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"

type RuceneDoc struct {
	AnswerID      string            `json:"answer_id"`      // answerID
	DocId         string            `json:"doc_id"`         // 索引唯一id
	ParentID      string            `json:"parent_id"`      // questionID
	QuestionTitle model.SegmentInfo `json:"question_title"` // 问题标题
	Theme         model.SegmentInfo `json:"theme"`          // 问题主题
	Summary       model.SegmentInfo `json:"summary"`        // 回答摘要
	QuesSummary   model.SegmentInfo `json:"ques_summary"`   // 问题摘要
	AuthorID      string            `json:"author_id"`      // 作者hashID
	CreateTime    int64             `json:"create_time"`    // 生成时间
	ShareTime     int64             `json:"share_time"`     // 首次分享时间
}
