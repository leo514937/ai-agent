package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
)

const DigitalAuthorProductName = "digital_author"

type DigitalAuthorContext struct {
	requestInfo        *proto.DigitalAuthorRequestInfo
	conversationId     string
	message            *proto.ChatMessage
	respMessageId      string
	senderId           string
	receiverId         string
	histChat           []*proto.HistChatMessage
	bayesFirstCategory []string
	topicNames         []string
	authorName         string
	tasks              []*proto.TaskInfo
	isEnableOnsite     bool
	isEnableUniversal  bool
	recallKnowledge    []*RecallKnowledge
	hitTask            *proto.TaskInfo // 命中的任务
	needSummary        bool            // 是否需要单独生成summary
	multiChatSummary   string          // 多轮对话summary
}

type RecallKnowledge struct {
	DocId        int64   `json:"doc_id"`
	DocType      string  `json:"doc_type"` // zai-proto/ai/content/doc.proto 里 docType.string
	RecallSource BizType `json:"recall_source"`
	SimilarScore float64 `json:"similar_score"`
	Text         string  `json:"text"`
}

type BizType string

const (
	SelfEdited       BizType = "SELF_EDITED"        // 个人编辑知识库 P0
	OnSiteChoice     BizType = "ON_SITE"            // 站内知识库同步 P1
	OnSiteUniversal  BizType = "ON_SITE_UNIVERSAL"  // 站内通用知识库 P2
	OffSiteUniversal BizType = "OFF_SITE_UNIVERSAL" // 站外通用知识库 P2
)

func IndexLevelSourceToBizType(indexSource conf.IndexSourceType, indexLevel conf.IndexLevelType) BizType {
	switch indexLevel {
	case conf.IndexLevel0:
		return SelfEdited
	case conf.IndexLevel1:
		return OnSiteChoice
	case conf.IndexLevel2:
		if indexSource == conf.IndexSourceZhihu {
			return OnSiteUniversal
		} else if indexSource == conf.IndexSourceLaw {
			return OffSiteUniversal
		}
	}
	return ""
}

func (d *DigitalAuthorContext) GetProductName() string {
	return DigitalAuthorProductName
}

func NewDigitalAuthorContext(request *proto.DigitalAuthorRequestInfo) *DigitalAuthorContext {
	return &DigitalAuthorContext{
		requestInfo:        request,
		conversationId:     request.GetConversationId(),
		message:            request.GetMessage(),
		respMessageId:      request.GetRespMessageId(),
		senderId:           request.GetSenderId(),
		receiverId:         request.GetReceiverId(),
		histChat:           request.GetBizInfo().GetHistChat(),
		bayesFirstCategory: request.GetBizInfo().GetBayesFirstcategory(),
		topicNames:         request.GetBizInfo().GetTopicNames(),
		authorName:         request.GetBizInfo().GetAuthorName(),
		tasks:              request.GetBizInfo().GetTasks(),
		isEnableOnsite:     request.GetBizInfo().GetEnableOnsite(),
		isEnableUniversal:  request.GetBizInfo().GetEnableUniversal(),
	}
}

func (d *DigitalAuthorContext) HistChat() []*proto.HistChatMessage {
	return d.histChat
}

func (d *DigitalAuthorContext) Task() []*proto.TaskInfo {
	return d.tasks
}

func (d *DigitalAuthorContext) SenderId() string {
	return d.senderId
}

func (d *DigitalAuthorContext) ReceiverId() string {
	return d.receiverId
}

func (d *DigitalAuthorContext) BayesFirstCategory() []string {
	return d.bayesFirstCategory
}

func (d *DigitalAuthorContext) TopicNames() []string {
	return d.topicNames
}

func (d *DigitalAuthorContext) IsEnableOnsite() bool {
	return d.isEnableOnsite
}

func (d *DigitalAuthorContext) IsEnableUniversal() bool {
	return d.isEnableUniversal
}

func (d *DigitalAuthorContext) RecallKnowledge() []*RecallKnowledge {
	return d.recallKnowledge
}

func (d *DigitalAuthorContext) SetRecallKnowledge(recallKnowledge []*RecallKnowledge) {
	d.recallKnowledge = recallKnowledge
}

func (d *DigitalAuthorContext) RequestInfo() *proto.DigitalAuthorRequestInfo {
	return d.requestInfo
}

func (d *DigitalAuthorContext) HitTask() *proto.TaskInfo {
	return d.hitTask
}

func (d *DigitalAuthorContext) SetHitTask(hitTask *proto.TaskInfo) {
	d.hitTask = hitTask
}

func (d *DigitalAuthorContext) AuthorName() string {
	return d.authorName
}

func (d *DigitalAuthorContext) NeedSummary() bool {
	return d.needSummary
}

func (d *DigitalAuthorContext) SetNeedSummary(needSummary bool) {
	d.needSummary = needSummary
}

func (d *DigitalAuthorContext) MultiChatSummary() string {
	return d.multiChatSummary
}

func (d *DigitalAuthorContext) SetMultiChatSummary(multiChatSummary string) {
	d.multiChatSummary = multiChatSummary
}

var _ entities.ProductContext = (*DigitalAuthorContext)(nil) // 检测是否实现全部方法
