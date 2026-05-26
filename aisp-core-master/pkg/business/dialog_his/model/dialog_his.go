package model

import "time"

type DialogHis struct {
	ID int64 `json:"id"`
	// ChatType 对话类型 SearchTab:1  AITAB:2 ...
	ChatType  int32     `json:"chat_type"`
	SessionId int64     `json:"session_id"`
	MessageId int64     `json:"message_id"`
	MemberId  int64     `json:"member_id"`
	TargetId  int64     `json:"target_id"`
	Query     string    `json:"query"`
	Answer    string    `json:"answer"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type WordMapperCreateDto struct {
	WordType int32  `json:"word_type"`
	Word     string `json:"word"`
	SourceId string `json:"source_id"`
}
