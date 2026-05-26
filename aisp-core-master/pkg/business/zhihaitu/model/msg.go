package model

import (
	"context"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// 消息定义：https://wiki.in.zhihu.com/pages/viewpage.action?pageId=530387399

const KafkaZhihaituTopic = "msg.aisp-core.zhihaitu"

type MsgType string

const MsgTypeUserQuestion MsgType = "user_question"
const MsgTypeAIAnswer MsgType = "ai_answer"
const MsgTypeUserFeedback MsgType = "user_feedback"
const MsgTypeSessionCreated MsgType = "session_created"
const MsgTypeAiQuestionStat MsgType = "ai_question_stat"

type IReportMsg interface {
	GetMsgType() MsgType
	SetHeader(header *ReportMsgHeader)
}

type ReportMsgHeader struct {
	MsgType MsgType `json:"msg_type"` // 消息类型
}

func (h *ReportMsgHeader) SetHeader(header *ReportMsgHeader) {
	*h = *header
}

const (
	UserQuestionStateQuestion = 1
	UserQuestionStateProcess  = 2
)

// UserQuestion 用户提问后
type UserQuestion struct {
	ReportMsgHeader
	QuestionID  string `json:"question_id"`  // 问题消息的id		✓
	Content     string `json:"content"`      // 问题内容		✓
	UserID      string `json:"user_id"`      //	账号id		✓
	State       int64  `json:"state"`        // 提问填1，处置填2		✓
	SessionID   string `json:"session_id"`   // 所属session的id		✓
	PublishTime string `json:"publish_time"` // 发布时间	（yyyyMMddHHmmss格式）	✓
}

func (u *UserQuestion) GetMsgType() MsgType {
	return MsgTypeUserQuestion
}

const (
	AiAnswerRegenerateTypeFirst      = 1
	AiAnswerRegenerateTypeRegenerate = 2
)

// AIAnswer 回答问题时
type AIAnswer struct {
	ReportMsgHeader
	AnswerID       string `json:"answer_id"`       //机器人回答的id		✓
	QuestionID     string `json:"question_id"`     //机器人回答的问题的id		✓
	SessionID      string `json:"session_id"`      //所属session的id		✓
	AnswerType     int64  `json:"answer_type"`     //回答的类型（富文本：1、图片：2、音频：3、视频：4、文件：5、其他：0)	（填类型对应的枚举值）	✓
	PublishTime    string `json:"publish_time"`    //发布时间	（yyyyMMddHHmmss格式）	✓
	RegenerateType int64  `json:"regenerate_type"` //类型：聊天机器人首次回答问题，以及重新回答且回答消息id发生变化时填1 重新回答时，回答消息的id没变时填2	✓
	Content        string `json:"content"`         //回答的内容
}

func (u *AIAnswer) GetMsgType() MsgType {
	return MsgTypeAIAnswer
}

// 提问者提交反馈信息时
type UserFeedback struct {
	ReportMsgHeader
	AnswerID     string `json:"answer_id"`     //机器人回答的id		✓
	QuestionID   string `json:"question_id"`   //机器人回答的问题的id		✓
	SessionID    string `json:"session_id"`    //所属session的id		✓
	UserID       string `json:"user_id"`       //提问者的账号id		✓
	FeedbackType int64  `json:"feedback_type"` //反馈操作的类型（重新回答填1、满意填2、不满意填3、其他填0）		✓
}

func (u *UserFeedback) GetMsgType() MsgType {
	return MsgTypeUserFeedback
}

// 会话创建时
type SessionCreated struct {
	ReportMsgHeader
	SessionID  string `json:"session_id"`  //所属session的id		✓
	UserID     string `json:"user_id"`     //提问者的账号id		✓
	UpdateTime string `json:"update_time"` //创建时间	（yyyyMMddHHmmss格式）	✓
}

func (u *SessionCreated) GetMsgType() MsgType {
	return MsgTypeSessionCreated
}

// AiQuestionStat 问题状态发生变化时
type AiQuestionStat struct {
	ReportMsgHeader
	QuestionId string `json:"question_id"` //问题id
	SessionId  string `json:"session_id"`  //所属session的id
	State      int64  `json:"state"`       //提问填1，处置填2
}

func (u *AiQuestionStat) GetMsgType() MsgType {
	return MsgTypeAiQuestionStat
}

func SendData(ctx context.Context, data IReportMsg) error {
	msgType := data.GetMsgType()
	header := &ReportMsgHeader{
		MsgType: msgType,
	}
	data.SetHeader(header)

	log.Infof(ctx, "send kafka msg start.  msgType: %s data: %+v", msgType, data)

	err := util.SendKafka(ctx, KafkaZhihaituTopic, data)
	if err != nil {
		log.Errorf(ctx, "send kafka error: %+v", err)
		return err
	}

	log.Infof(ctx, "send kafka msg ok. msgType: %s", msgType)

	return nil
}
