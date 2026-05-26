package dialogue

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"text/template"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/exception"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/metrics"
	"github.com/samber/lo"
)

type Service interface {
	// CreateDialogue 会创建对话, 并将对话状态设置为 PROCESSING
	CreateDialogue(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}) (*model.Dialogue, error)

	// ProcessDialogue 会处理对话的主要逻辑(如送审, 生成 ai_message), 并处理整个流程的错误处理, 超时处理.
	ProcessDialogue(ctx context.Context, dialogue *model.Dialogue) (*model.Dialogue, string, error)

	ProcessDialogueStream(ctx context.Context, dialogue *model.Dialogue) (<-chan util.Progress[*model.Dialogue], string, error)
}

var DefaultService Service

type ServiceImpl struct {
	dialogueDAO       dao.DialogueDAO
	conversationDAO   dao.ConversationDAO
	taskDAO           dao.TaskDAO
	promptTemplateDAO dao.PromptTemplateDAO
	idGenerator       dao.IDGenerator

	historyExtractor MessageExtractor
	contentModerator ContentModerator

	modelGatewayRPC modelapi.ModelTarget

	metricsClient metrics.Client
}

var _ Service = (*ServiceImpl)(nil)

func NewServiceImpl() *ServiceImpl {
	return &ServiceImpl{
		dialogueDAO:       dao.DefaultDialogueDAO,
		conversationDAO:   dao.DefaultConversationDAO,
		taskDAO:           dao.DefaultTaskDAO,
		idGenerator:       dao.DefaultIDGenerator,
		promptTemplateDAO: dao.DefaultPromptTemplateDAO,
		historyExtractor:  DefaultHistoryExtractor,
		contentModerator:  DefaultContentModerator,
		modelGatewayRPC:   rpc.DefaultModelGatewayRouter,
		metricsClient:     metrics.NewClient("core.service.dialogue"),
	}
}

func (s *ServiceImpl) CreateDialogue(ctx context.Context, tenantID, taskID int64, userID string, conversationID int64, userMessage string, custom map[string]interface{}) (*model.Dialogue, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenantID":       tenantID,
		"taskID":         taskID,
		"conversationID": conversationID,
		"userID":         userID,
		"userMessage":    userMessage,
		"custom":         custom,
	})
	s.metricsClient.Count(ctx, "create", 1)
	dialogueID, err := s.idGenerator.GenerateID(ctx)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to generate dialogue id")
		return nil, err
	}
	dialogue := &model.Dialogue{
		ID:             dialogueID,
		TenantID:       tenantID,
		TaskID:         taskID,
		ConversationID: conversationID,
		UserID:         userID,
		UserMessage:    userMessage,
		Custom:         custom,
		State:          model.DialogueStateProcessing,
		AuditState:     model.DialogueAuditStateUnset,
	}
	_, err = s.dialogueDAO.CreateDialogue(ctx, dialogue)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to create dialogue")
		return nil, err
	}
	return s.dialogueDAO.GetDialogueByID(ctx, tenantID, dialogueID)
}

func (s *ServiceImpl) ProcessDialogue(ctx context.Context, dialogue *model.Dialogue) (*model.Dialogue, string, error) {
	logger := log.WithField(ctx, "dialogue", dialogue)
	s.metricsClient.Count(ctx, "process", 1)
	defer s.metricsClient.T(ctx, "process.time").Submit()
	// 实际的对话处理
	dialogueResult, modelName, err := util.Try2(func() (*model.DialogueResult, string, error) {
		return s.processDialogue(ctx, dialogue)
	})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to process dialogue")
	}

	// 更新对话状态
	if dialogueResult == nil {
		dialogueResult = &model.DialogueResult{
			State:      lo.ToPtr(model.DialogueStateFail),
			AuditState: lo.ToPtr(model.DialogueAuditStateUnset),
		}
	}
	s.metricsClient.Count(ctx, "process.setResult.state."+string(*dialogueResult.State)+"."+string(*dialogueResult.AuditState), 1)
	s.metricsClient.Count(ctx, "process.setResult.token.input", lo.FromPtrOr(dialogueResult.InputTokenCount, 0))
	s.metricsClient.Count(ctx, "process.setResult.token.output", lo.FromPtrOr(dialogueResult.OutputTokenCount, 0))
	err = s.dialogueDAO.SetChatResult(ctx, dialogue.TenantID, dialogue.ID, dialogueResult)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to set chat result")
		return nil, "", err
	}
	dialogue, err = s.dialogueDAO.GetDialogueByID(ctx, dialogue.TenantID, dialogue.ID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get dialogue by id")
		return nil, "", err
	}
	if dialogue == nil {
		logger.Errorf(ctx, "dialogue not found")
		return nil, "", exception.ErrInternal.Wrap(exception.ErrTenantNotFound)
	}
	return dialogue, modelName, nil
}

func (s *ServiceImpl) ProcessDialogueStream(ctx context.Context, dialogue *model.Dialogue) (<-chan util.Progress[*model.Dialogue], string, error) {
	logger := log.WithField(ctx, "dialogue", dialogue)

	resultStream := s.processDialogueStream(ctx, dialogue)
	ret := make(chan util.Progress[*model.Dialogue])
	utils.SafelyGo(func() {
		defer close(ret)
		for progress := range resultStream {
			if progress.E != nil {
				ret <- util.Progress[*model.Dialogue]{E: progress.E}
				return
			}
			err := s.dialogueDAO.SetChatResult(ctx, dialogue.TenantID, dialogue.ID, progress.V)
			if err != nil {
				ret <- util.Progress[*model.Dialogue]{E: err}
				logger.WithError(ctx, err).Errorf(ctx, "failed to set chat result")
				return
			}
			dialogue, err = s.dialogueDAO.GetDialogueByID(ctx, dialogue.TenantID, dialogue.ID)
			if err != nil {
				ret <- util.Progress[*model.Dialogue]{E: err}
				logger.WithError(ctx, err).Errorf(ctx, "failed to get dialogue by id")
				return
			}
			if dialogue == nil {
				ret <- util.Progress[*model.Dialogue]{E: exception.ErrInternal.Wrap(exception.ErrDialogueNotFound)}
				logger.Errorf(ctx, "dialogue not found")
				return
			}
			ret <- util.Progress[*model.Dialogue]{V: dialogue}
		}
	}, func(_ error) {})
	return ret, "", nil
}

func (s *ServiceImpl) processDialogue(ctx context.Context, dialogue *model.Dialogue) (*model.DialogueResult, string, error) {
	logger := log.WithField(ctx, "dialogue", dialogue)

	// 数据准备
	if dialogue.State != model.DialogueStateProcessing {
		logger.Errorf(ctx, "dialogue not in processing state")
		return nil, "", exception.ErrDialogueStateInvalid.New("dialogue state is %s", dialogue.State)
	}

	task, err := s.taskDAO.GetTaskByID(ctx, dialogue.TenantID, dialogue.TaskID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get task by id")
		return nil, "", err
	}

	var recentDialogues []*model.Dialogue
	if task.ConversationModel == model.ConversationModelFreeConversation {
		recentDialogues, err = s.historyExtractor.Extract(ctx, dialogue.TenantID, dialogue.ConversationID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to extract recentDialogues")
			return nil, "", err
		}
	}

	conversation, err := s.conversationDAO.GetConversationByID(ctx, dialogue.TenantID, dialogue.ConversationID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get conversation by id")
		return nil, "", err
	}

	// 对 user_message 审核
	result, reason, err := s.contentModerator.Review(ctx, &ReviewRequest{
		TenantID:       dialogue.TenantID,
		TaskID:         dialogue.TaskID,
		UserID:         dialogue.UserID,
		ConversationID: dialogue.ConversationID,
		DialogueID:     dialogue.ID,
		UserMessage:    dialogue.UserMessage,
		AIMessage:      "",
		History: lo.Map(recentDialogues, func(d *model.Dialogue, _ int) *HistoryEntry {
			return &HistoryEntry{
				DialogueID:  dialogue.ID,
				UserMessage: d.UserMessage,
				AIMessage:   d.AIMessage,
			}
		}),
	})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to review content")

		if task.AuditMode == model.AuditModeNoFallback {
			return nil, "", err
		} else if task.AuditMode == model.AuditModeFallbackToNotPass {
			result = ReviewResultNotPass
			reason = "content review failed, fallback to not pass"
		} else {
			panic(errors.New("invalid review mode"))
		}
	}
	if result == ReviewResultNotPass {
		logger.Warnf(ctx, "content not pass")
		return &model.DialogueResult{
			State:       lo.ToPtr(model.DialogueStateFail),
			AuditState:  lo.ToPtr(model.DialogueAuditStateUserMessageNotPass),
			AuditReason: &reason,
		}, "", nil
	}

	// 送大模型编排引擎
	prompt := dialogue.UserMessage
	if task.PromptTemplateID != 0 {
		var err error
		prompt, err = s.generatePrompt(ctx, dialogue.TenantID, dialogue.UserMessage, task.PromptTemplateID, logger)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to generate prompt")
			return nil, "", err
		}
	}

	aiProfile := task.AIProfile

	if !conversation.CreatedAt.IsZero() {
		createTime := conversation.CreatedAt
		aiProfile += fmt.Sprintf("当前时间是%d年%d月%d日。", createTime.Year(), createTime.Month(), createTime.Day())
	}

	req := s.buildReq(task, aiProfile, prompt, recentDialogues)
	context := s.buildContext(task, aiProfile, prompt, recentDialogues)

	resp, err := s.modelGatewayRPC.Chat(ctx, req)
	if err != nil {
		logger.WithField(ctx, "req", req).WithError(ctx, err).Errorf(ctx, "failed to chat with model gateway")
		return nil, "", err
	}

	content := resp.Content
	usage := resp.Usage
	modelName := resp.ModelName

	contentList := []string{content}
	if dialogue.TaskID == macro.TaskGenTitle {
		contentList = strings.Split(content, "\n")
	}

	newContentList := make([]string, 0)
	auditState := model.DialogueAuditStateAIMessageNotPass
	reviewReason := ""
	for _, content := range contentList {
		// 对 ai_message 审核
		reviewResult := ReviewResultPass
		result, reason, err = s.contentModerator.Review(ctx, &ReviewRequest{
			TenantID:       dialogue.TenantID,
			TaskID:         dialogue.TaskID,
			UserID:         dialogue.UserID,
			ConversationID: dialogue.ConversationID,
			DialogueID:     dialogue.ID,
			UserMessage:    dialogue.UserMessage,
			AIMessage:      content,
			History: lo.Map(recentDialogues, func(d *model.Dialogue, _ int) *HistoryEntry {
				return &HistoryEntry{
					DialogueID:  dialogue.ID,
					UserMessage: d.UserMessage,
					AIMessage:   d.AIMessage,
				}
			}),
		})
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to review content")

			if task.AuditMode == model.AuditModeNoFallback {
				return nil, "", err
			} else if task.AuditMode == model.AuditModeFallbackToNotPass {
				result = ReviewResultNotPass
				reason = "content review failed, fallback to not pass"
			} else {
				panic(errors.New("invalid review mode"))
			}
		}
		reviewResult = result
		reviewReason = reason

		if reviewResult == ReviewResultNotPass {
			logger.Warnf(ctx, "content not pass")
		} else {
			auditState = model.DialogueAuditStatePass
			newContentList = append(newContentList, content)
		}
	}

	content = strings.Join(newContentList, "\n")

	if auditState == model.DialogueAuditStatePass {
		reviewReason = ""
	}

	// 完成
	return &model.DialogueResult{
		AIMessage:        &content,
		Context:          lo.ToPtr(string(lo.Must(json.Marshal(context)))),
		State:            lo.ToPtr(model.DialogueStateSuccess),
		AuditState:       &auditState,
		AuditReason:      &reviewReason,
		InputTokenCount:  &usage.InputTokenCount,
		OutputTokenCount: &usage.OutputTokenCount,
	}, modelName, nil
}

func (s *ServiceImpl) processDialogueStream(ctx context.Context, dialogue *model.Dialogue) <-chan util.Progress[*model.DialogueResult] {
	logger := log.WithField(ctx, "dialogue", dialogue)

	ret := make(chan util.Progress[*model.DialogueResult])

	utils.SafelyGo(func() {
		defer close(ret)

		defer func() {
			panic_ := recover()
			if panic_ != nil {
				logger.WithField(ctx, "panic", panic_).Errorf(ctx, "panic in processDialogueStream")
				ret <- util.Progress[*model.DialogueResult]{E: exception.ErrInternal.Wrap(fmt.Errorf("%v", panic_))}
			}
		}()

		// 数据准备
		if dialogue.State != model.DialogueStateProcessing {
			logger.Errorf(ctx, "dialogue not in processing state")
			ret <- util.Progress[*model.DialogueResult]{E: exception.ErrDialogueStateInvalid.New("dialogue state is %s", dialogue.State)}
			return
		}

		task, err := s.taskDAO.GetTaskByID(ctx, dialogue.TenantID, dialogue.TaskID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to get task by id")
			ret <- util.Progress[*model.DialogueResult]{E: err}
			return
		}

		var recentDialogues []*model.Dialogue
		if task.ConversationModel == model.ConversationModelFreeConversation {
			recentDialogues, err = s.historyExtractor.Extract(ctx, dialogue.TenantID, dialogue.ConversationID)
			if err != nil {
				logger.WithError(ctx, err).Errorf(ctx, "failed to extract recentDialogues")
				ret <- util.Progress[*model.DialogueResult]{E: err}
				return
			}
		}

		conversation, err := s.conversationDAO.GetConversationByID(ctx, dialogue.TenantID, dialogue.ConversationID)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to get conversation by id")
			ret <- util.Progress[*model.DialogueResult]{E: err}
			return
		}

		// 对 user_message 审核
		result, reason, err := s.contentModerator.Review(ctx, &ReviewRequest{
			TenantID:       dialogue.TenantID,
			TaskID:         dialogue.TaskID,
			UserID:         dialogue.UserID,
			ConversationID: dialogue.ConversationID,
			DialogueID:     dialogue.ID,
			UserMessage:    dialogue.UserMessage,
			AIMessage:      "",
			History: lo.Map(recentDialogues, func(d *model.Dialogue, _ int) *HistoryEntry {
				return &HistoryEntry{
					DialogueID:  dialogue.ID,
					UserMessage: d.UserMessage,
					AIMessage:   d.AIMessage,
				}
			}),
		})
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "failed to review content")

			if task.AuditMode == model.AuditModeNoFallback {
				ret <- util.Progress[*model.DialogueResult]{E: err}
				return
			} else if task.AuditMode == model.AuditModeFallbackToNotPass {
				result = ReviewResultNotPass
				reason = "content review failed, fallback to not pass"
			} else {
				panic(errors.New("invalid review mode"))
			}
		}
		if result == ReviewResultNotPass {
			logger.Warnf(ctx, "content not pass")
			ret <- util.Progress[*model.DialogueResult]{V: &model.DialogueResult{
				State:       lo.ToPtr(model.DialogueStateFail),
				AuditState:  lo.ToPtr(model.DialogueAuditStateUserMessageNotPass),
				AuditReason: &reason,
			}}
			return
		}

		// 送大模型编排引擎
		prompt := dialogue.UserMessage
		if task.PromptTemplateID != 0 {
			var err error
			prompt, err = s.generatePrompt(ctx, dialogue.TenantID, dialogue.UserMessage, task.PromptTemplateID, logger)
			if err != nil {
				logger.WithError(ctx, err).Errorf(ctx, "failed to generate prompt")
				ret <- util.Progress[*model.DialogueResult]{E: err}
				return
			}
		}

		aiProfile := task.AIProfile

		if !conversation.CreatedAt.IsZero() {
			createTime := conversation.CreatedAt
			aiProfile += fmt.Sprintf("当前时间是%d年%d月%d日。", createTime.Year(), createTime.Month(), createTime.Day())
		}

		req := s.buildReq(task, aiProfile, prompt, recentDialogues)
		context := s.buildContext(task, aiProfile, prompt, recentDialogues)

		ret <- util.Progress[*model.DialogueResult]{V: &model.DialogueResult{
			State:   lo.ToPtr(model.DialogueStateProcessing),
			Context: lo.ToPtr(string(lo.Must(json.Marshal(context)))),
		}}

		resultStream := s.modelGatewayRPC.StreamChat(ctx, req)
		for progress := range resultStream {
			err := progress.E
			if err != nil {
				logger.WithField(ctx, "req", req).WithError(ctx, err).Errorf(ctx, "failed to chat with model gateway")
				ret <- util.Progress[*model.DialogueResult]{E: err}
				return
			}

			resp := progress.V

			content := resp.Content
			usage := resp.Usage

			contentList := []string{content}
			if dialogue.TaskID == macro.TaskGenTitle {
				contentList = strings.Split(content, "\n")
			}

			newContentList := make([]string, 0)
			auditState := model.DialogueAuditStateAIMessageNotPass
			reviewReason := ""
			for _, content := range contentList {
				// 对 ai_message 审核
				reviewResult := ReviewResultPass
				result, reason, err = s.contentModerator.Review(ctx, &ReviewRequest{
					TenantID:       dialogue.TenantID,
					TaskID:         dialogue.TaskID,
					UserID:         dialogue.UserID,
					ConversationID: dialogue.ConversationID,
					DialogueID:     dialogue.ID,
					UserMessage:    dialogue.UserMessage,
					AIMessage:      content,
					History: lo.Map(recentDialogues, func(d *model.Dialogue, _ int) *HistoryEntry {
						return &HistoryEntry{
							DialogueID:  dialogue.ID,
							UserMessage: d.UserMessage,
							AIMessage:   d.AIMessage,
						}
					}),
				})
				if err != nil {
					logger.WithError(ctx, err).Errorf(ctx, "failed to review content")

					if task.AuditMode == model.AuditModeNoFallback {
						ret <- util.Progress[*model.DialogueResult]{E: err}
						return
					} else if task.AuditMode == model.AuditModeFallbackToNotPass {
						result = ReviewResultNotPass
						reason = "content review failed, fallback to not pass"
					} else {
						panic(errors.New("invalid review mode"))
					}
				}
				reviewResult = result
				reviewReason = reason

				if reviewResult == ReviewResultNotPass {
					logger.Warnf(ctx, "content not pass")
				} else {
					auditState = model.DialogueAuditStatePass
					newContentList = append(newContentList, content)
				}
			}

			content = strings.Join(newContentList, "\n")

			if auditState == model.DialogueAuditStatePass {
				reviewReason = ""
			}

			ret <- util.Progress[*model.DialogueResult]{V: &model.DialogueResult{
				AIMessage:        &content,
				State:            lo.ToPtr(model.DialogueStateProcessing),
				AuditState:       lo.ToPtr(auditState),
				AuditReason:      lo.ToPtr(reviewReason),
				InputTokenCount:  lo.ToPtr(usage.InputTokenCount),
				OutputTokenCount: lo.ToPtr(usage.OutputTokenCount),
			}}
		}
		ret <- util.Progress[*model.DialogueResult]{V: &model.DialogueResult{
			State: lo.ToPtr(model.DialogueStateSuccess),
		}}
	}, func(_ error) {})
	return ret
}

func (s *ServiceImpl) buildReq(task *model.Task, aiProfile string, prompt string, recentDialogues []*model.Dialogue) *dto.ChatRequest {
	messages := make([]*dto.ChatRequestMessage, 0)
	for _, dialogue := range recentDialogues {
		messages = append(messages, &dto.ChatRequestMessage{Content: dialogue.UserMessage, Role: dto.ChatRequestMessageRoleUser})
		messages = append(messages, &dto.ChatRequestMessage{Content: dialogue.AIMessage, Role: dto.ChatRequestMessageRoleAI})
	}
	messages = append(messages, &dto.ChatRequestMessage{Content: prompt, Role: dto.ChatRequestMessageRoleUser})

	req := dto.ChatRequest{
		ModelName: task.ModelEngineTaskName,
		AIProfile: aiProfile,
		Messages:  messages,
	}

	return &req
}

func (s *ServiceImpl) buildContext(task *model.Task, aiProfile string, prompt string, recentDialogues []*model.Dialogue) *model.Context {
	context := &model.Context{
		AIProfile:   aiProfile,
		UserProfile: "", // 目前没有 UserProfile 的数据
		Prompt:      prompt,
		RecentMessages: lo.Flatten(lo.Map(recentDialogues, func(dialogue *model.Dialogue, _ int) []*model.Message {
			return []*model.Message{
				{
					Role:    model.MessageRoleUser,
					Content: dialogue.UserMessage,
				},
				{
					Role:    model.MessageRoleAI,
					Content: dialogue.AIMessage,
				},
			}
		})),
	}
	return context
}

func (s *ServiceImpl) generatePrompt(ctx context.Context, tenantID int64, primaryContent string, promptTemplateID int64, logger *log.ZhihuLogger) (string, error) {
	promptTemplate, err := s.promptTemplateDAO.GetPromptTemplateByID(ctx, tenantID, promptTemplateID)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to get prompt template by id")
		return "", err
	}
	template, err := template.New(promptTemplate.IDString).Parse(promptTemplate.Template)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to parse prompt template")
		return "", err
	}
	promptBuffer := &bytes.Buffer{}
	var primaryContentJSON map[string]interface{}
	err = json.Unmarshal([]byte(primaryContent), &primaryContentJSON)
	if err != nil {
		logger.WithError(ctx, err).Warn(ctx, "failed to unmarshal primary content")
	}

	// 清洗 content 里的 html
	primaryContentFilterHtml, err := util.ContentFilterHtml(ctx, primaryContent)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to filter html")

		primaryContentFilterHtml = primaryContent
	}

	err = template.Execute(promptBuffer, map[string]interface{}{
		"primary_content":             primaryContent,
		"primary_content_json":        primaryContentJSON,
		"primary_content_filter_html": primaryContentFilterHtml,
	})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "failed to execute prompt template")
		return "", err
	}
	return promptBuffer.String(), nil
}

func init() {
	DefaultService = NewServiceImpl()
}
