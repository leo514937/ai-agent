package model

import "time"

type PromptMapper struct {
	ID         int64     `json:"id"`
	PromptCode string    `json:"prompt_code"`
	Prompt     string    `json:"prompt"`
	Remark     string    `json:"remark"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

type PromptMapperDto struct {
	PromptCode string `json:"prompt_code"`
	Prompt     string `json:"prompt"`
	Remark     string `json:"remark"`
}
