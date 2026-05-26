package model

import "time"

type WordMapper struct {
	ID        int64     `json:"id"`
	WordId    int64     `json:"word_id"`
	WordType  int32     `json:"word_type"`
	Word      string    `json:"word"`
	SourceId  string    `json:"source_id"`
	Deleted   int64     `json:"deleted"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type WordMapperCreateDto struct {
	WordType int32  `json:"word_type"`
	Word     string `json:"word"`
	SourceId string `json:"source_id"`
}
