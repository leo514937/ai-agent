package model

import "time"

type TableDailySnapshot struct {
	ID           int64     `gorm:"column:id;primaryKey;autoRandom"`
	UserID       int64     `gorm:"column:user_id;not null"`
	HashToken    string    `gorm:"column:hash_token"`
	ReqSource    string    `gorm:"column:req_source"`
	Title        string    `gorm:"column:title;type:text"`
	GenerateDate string    `gorm:"column:generate_date;not null"`
	JsonContent  string    `gorm:"column:json_content;type:text"`
	CreatedAt    time.Time `gorm:"column:created_at;not null;default:CURRENT_TIMESTAMP"`
	UpdatedAt    time.Time `gorm:"column:updated_at;not null;default:CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"`
}

func (d *TableDailySnapshot) TableName() string {
	return "daily_snapshot"
}

func (d *TableDailySnapshot) Columns() []string {
	return []string{
		"id", "user_id", "hash_token", "req_source", "title", "generate_date", "json_content", "created_at", "updated_at",
	}
}
