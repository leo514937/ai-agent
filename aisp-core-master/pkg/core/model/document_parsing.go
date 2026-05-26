package model

import (
	"time"
)

type DocumentParsingBase struct {
	ID               int64     `json:"id" borm:"primary_key"`
	DocId            int64     `json:"doc_id"`
	DocType          string    `json:"doc_type"`
	ProcessorType    string    `json:"processor_type"`
	ProcessorName    string    `json:"processor_name"`
	ProcessorVersion string    `json:"processor_version"`
	ItemName         string    `json:"item_name"`
	Content          string    `json:"content"`
	ContentUrl       string    `json:"content_url"`
	CreatedAt        time.Time `json:"created_at" borm:"readonly"`
	UpdatedAt        time.Time `json:"updated_at" borm:"readonly"`
}
