package model

import "time"

type TableQuestionDetailCnt struct {
	ID             int64     `gorm:"column:id;primaryKey;autoRandom"`
	QuestionID     string    `gorm:"column:question_id"`
	ShareCount     int64     `gorm:"column:share_count"`
	ShowCount      int64     `gorm:"column:show_count"`
	FirstShareTime int64     `gorm:"column:first_share_time"`
	CreatedAt      int64     `gorm:"column:created_at"`
	UpdatedAt      time.Time `gorm:"column:updated_at;default:CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"`
}

func (d *TableQuestionDetailCnt) TableName() string {
	return "question_detail_cnt"
}

func (d *TableQuestionDetailCnt) Columns() []string {
	return []string{
		"id", "question_id", "share_count", "show_count", "first_share_time", "created_at", "updated_at",
	}
}

func (d *TableQuestionDetailCnt) InsertColumns() []string {
	return []string{
		"question_id", "share_count", "show_count", "first_share_time", "created_at",
	}
}
