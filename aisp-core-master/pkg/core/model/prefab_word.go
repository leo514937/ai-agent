package model

import (
	"encoding/json"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type PrefabWord struct {
	DocId             int64                `json:"doc_id"`              // DocId 文章ID
	DocType           content.DocType_Type `json:"doc_type"`            // DocType 文章类型
	ContentType       string               `json:"content_type"`        // ContentType 内容类型
	QueryType         proto.QueryType      `json:"query_type"`          // QueryType 词类型
	SourceChannel     string               `json:"source_channel"`      // SourceChannel 数据源
	SourceQuestion    string               `json:"source_question"`     // SourceQuestion 源问题
	AiRewriteQuestion string               `json:"ai_rewrite_question"` // AiRewriteQuestion AI改写问题
}

type PrefabWordInfo struct {
	WordId    int64                `json:"word_id"`
	Word      string               `json:"word"`
	QueryType proto.QueryType      `json:"query_type"`
	ExtraInfo *PrefabWordExtraInfo `json:"extra_info"`
}

type PrefabWordExtraInfo struct {
	Word           string `json:"word,omitempty"`            // 引导词内容
	SourceQuestion string `json:"source_question,omitempty"` // SourceQuestion 源问题
}

func (p *PrefabWordExtraInfo) GetWord() string {
	if p == nil {
		return ""
	}
	return p.Word
}
func (p *PrefabWordExtraInfo) GetSourceQuestion() string {
	if p == nil {
		return ""
	}
	return p.SourceQuestion
}

// ToJsonString 将自身PrefabWord对象 转换为json字符串
func (p *PrefabWord) ToJsonString() (string, error) {
	jsonStr, err := json.Marshal(p)
	if err != nil {
		return "", err
	}
	return string(jsonStr), nil
}

// ParsePrefabWord 根据字符串 解析json为 PrefabWord 对象
func ParsePrefabWord(jsonStr string) (*PrefabWord, error) {
	var word PrefabWord
	err := json.Unmarshal([]byte(jsonStr), &word)
	if err != nil {
		return nil, err
	}
	return &word, nil
}

type AIPredefinedWordBizExt struct {
	SourceChannel  string `json:"source_channel"`   // SourceChannel 数据源
	SourceQuestion string `json:"question_content"` // SourceQuestion 源问题
}

// ParseAIPredefinedWordBizExt 根据字符串 解析json为 AIPredefinedWordBizExt 对象
func ParseAIPredefinedWordBizExt(jsonStr string) (*AIPredefinedWordBizExt, error) {
	var ext AIPredefinedWordBizExt
	err := json.Unmarshal([]byte(jsonStr), &ext)
	if err != nil {
		return nil, err
	}
	return &ext, nil
}
