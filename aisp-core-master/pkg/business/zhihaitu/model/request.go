package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type IsExistRequest struct {
	Mobile string `json:"mobile"`
}

type QueryMsgRequest struct {
	ConversationID string `json:"conversationId"`
	MessageID      string `json:"messageId"`
}

type FeedBackRequest struct {
	ConversationID string `json:"conversationId"`
	MessageID      string `json:"messageId"`
	FeedbackMsg    string `json:"feedbackMsg"`
	FeedbackAction string `json:"feedbackAction"`
	Rating         string `json:"rating"`
	Role           string `json:"role"`
}

type DeleteConvMsgRequest struct {
	ConvIds []string `json:"convIds"`
}

type SuggestionRequest struct {
	Content string `json:"content"`
}

type ReportRequest struct {
	ConversationId string `json:"conversationId"`
	MessageId      string `json:"messageId"`
	ReportReason   string `json:"reportReason"`
	AIContent      string `json:"aiContent"`
}

type ChatContent struct {
	ImageId     string `json:"imageId"`
	Pairs       string `json:"pairs"`
	ContentType string `json:"type"`
}

type ChatMessage struct {
	Id          string      `json:"id"`
	MsgType     string      `json:"msgType"`
	ParentMsgId string      `json:"parentMsgId"`
	Role        interface{} `json:"role"`
	Content     ChatContent `json:"content"`
}

func (c *ChatMessage) ToDialogRecord() *model.DialogRecord {
	return &model.DialogRecord{
		MessageId:       c.Id,
		MessageType:     int64(proto.ChatMessageType_TEXT),
		ParentMessageId: c.ParentMsgId,
		MessageContent:  c.Content.Pairs,
		RoleType:        c.GetRole(),
	}
}

func (c *ChatMessage) GetRole() string {
	var role, ok = c.Role.(string)
	if !ok {
		return ""
	} else {
		return role
	}
}

type BmbChatReq struct {
	ConversationId string         `json:"conversationId"`
	ChatMessage    []*ChatMessage `json:"chatMessage"`
	GenerateType   string         `json:"generateType"`
	// ParentMessageId 前端没有传，不要用这个
	ParentMessageId string `json:"parentMessageId"`
}

type OpenApiChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

func (c *OpenApiChatMessage) ToDialogRecord() *model.DialogRecord {
	return &model.DialogRecord{
		MessageType:    int64(proto.ChatMessageType_TEXT),
		MessageContent: c.Content,
	}
}

type OpenApiConvReq struct {
	Model     string                `json:"model"`
	MaxTokens int                   `json:"max_tokens"`
	Stream    bool                  `json:"stream"`
	Dialogue  []*OpenApiChatMessage `json:"dialogue"`
}
