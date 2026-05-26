package dialogue

//
//import (
//	"context"
//	"reflect"
//	"testing"
//	"time"
//
//	"git.in.zhihu.com/go/utils"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
//	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/metrics"
//)
//
//func TestServiceImpl_ProcessDialogue(t *testing.T) {
//	type fields struct {
//		dialogueDAO       dao.DialogueDAO
//		conversationDAO   dao.ConversationDAO
//		taskDAO           dao.TaskDAO
//		promptTemplateDAO dao.PromptTemplateDAO
//		historyExtractor  MessageExtractor
//		contentModerator  ContentModerator
//		modelGateway      modelapi.ModelTarget
//	}
//	type args struct {
//		ctx      context.Context
//		dialogue *model.Dialogue
//	}
//	type T struct {
//		name    string
//		fields  fields
//		args    args
//		want    *model.Dialogue
//		wantErr bool
//	}
//	tests := []T{
//		func() T {
//			c := T{
//				name: "正常流程",
//			}
//			c.args = args{
//				ctx: context.Background(),
//				dialogue: &model.Dialogue{
//					ID:             1,
//					TenantID:       2,
//					TaskID:         3,
//					ConversationID: 4,
//					UserID:         "5",
//					UserMessage:    "你好",
//					State:          model.DialogueStateProcessing,
//					AuditState:     model.DialogueAuditStateUnset,
//				},
//			}
//			now := time.Now()
//			task := &model.Task{
//				ID:                  c.args.dialogue.TaskID,
//				TenantID:            c.args.dialogue.TenantID,
//				PromptTemplateID:    10,
//				Name:                "测试任务",
//				Owner:               "majingyang@zhihu.com",
//				Description:         "测试任务",
//				ModelEngineTaskName: "chat",
//				State:               model.TaskStateNormal,
//				ConversationModel:   model.ConversationModelTask,
//				AuditMode:           model.AuditModeNoFallback,
//				RateLimit:           1000,
//				CreatedAt:           now,
//				UpdatedAt:           now,
//			}
//			template := &model.PromptTemplate{
//				ID:        task.PromptTemplateID,
//				TenantID:  c.args.dialogue.TenantID,
//				TaskID:    c.args.dialogue.TaskID,
//				State:     model.PromptTemplateStateNormal,
//				Template:  "{{ .primary_content }}",
//				CreatedAt: now,
//				UpdatedAt: now,
//			}
//			conversation := &model.Conversation{
//				ID:        c.args.dialogue.ConversationID,
//				TenantID:  c.args.dialogue.TenantID,
//				TaskID:    c.args.dialogue.TaskID,
//				CreatorID: "1",
//				State:     model.ConversationStateNormal,
//				System: map[string]any{
//					"system1": "abc",
//				},
//				CreatedAt: now,
//				UpdatedAt: now,
//			}
//			context := &model.Context{
//				Prompt:         "你好",
//				RecentMessages: []*model.Message{},
//			}
//			c.fields = fields{
//				dialogueDAO: util.Config(dao.NewMockDialogueDAO(t), func(dialogueDAO *dao.MockDialogueDAO) {
//					dialogueDAO.EXPECT().GetDialogueByID(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.ID).Return(c.args.dialogue, nil)
//					dialogueDAO.EXPECT().SetChatResult(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.ID, &model.DialogueResult{
//						AIMessage:        "你好, 我是 AI",
//						Context:          utils.MustMarshalToString(context),
//						State:            model.DialogueStateSuccess,
//						AuditState:       model.DialogueAuditStatePass,
//						InputTokenCount:  1,
//						OutputTokenCount: 2,
//					}).Return(nil)
//				}),
//				conversationDAO: util.Config(dao.NewMockConversationDAO(t), func(conversationDAO *dao.MockConversationDAO) {
//					conversationDAO.EXPECT().GetConversationByID(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.ConversationID).Return(conversation, nil)
//				}),
//				taskDAO: util.Config(dao.NewMockTaskDAO(t), func(taskDAO *dao.MockTaskDAO) {
//					taskDAO.EXPECT().GetTaskByID(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.TaskID).Return(task, nil)
//				}),
//				promptTemplateDAO: util.Config(dao.NewMockPromptTemplateDAO(t), func(templateDAO *dao.MockPromptTemplateDAO) {
//					templateDAO.EXPECT().GetPromptTemplateByID(c.args.ctx, task.TenantID, task.PromptTemplateID).Return(template, nil)
//				}),
//				historyExtractor: util.Config(NewMockMessageExtractor(t), nil),
//				contentModerator: util.Config(NewMockContentModerator(t), func(moderator *MockContentModerator) {
//					moderator.EXPECT().Review(c.args.ctx, &ReviewRequest{
//						TenantID:       c.args.dialogue.TenantID,
//						TaskID:         c.args.dialogue.TaskID,
//						UserID:         c.args.dialogue.UserID,
//						ConversationID: c.args.dialogue.ConversationID,
//						DialogueID:     c.args.dialogue.ID,
//						UserMessage:    c.args.dialogue.UserMessage,
//						AIMessage:      "",
//						History:        []*HistoryEntry{},
//					}).Return(ReviewResultPass, "", nil)
//					moderator.EXPECT().Review(c.args.ctx, &ReviewRequest{
//						TenantID:       c.args.dialogue.TenantID,
//						TaskID:         c.args.dialogue.TaskID,
//						UserID:         c.args.dialogue.UserID,
//						ConversationID: c.args.dialogue.ConversationID,
//						DialogueID:     c.args.dialogue.ID,
//						UserMessage:    c.args.dialogue.UserMessage,
//						AIMessage:      "你好, 我是 AI",
//						History:        []*HistoryEntry{},
//					}).Return(ReviewResultPass, "", nil)
//				}),
//				modelGateway: util.Config(modelapi.NewMockModelEngineRPC(t), func(modelEngineRPC *modelapi.MockModelEngineRPC) {
//					modelEngineRPC.EXPECT().Chat(c.args.ctx, context, task.ModelEngineTaskName).Return("你好, 我是 AI", &modelapi.Usage{
//						InputTokenCount:  1,
//						OutputTokenCount: 2,
//					}, "modelName", nil)
//				}),
//			}
//			c.want = c.args.dialogue
//			return c
//		}(),
//		func() T {
//			c := T{
//				name: "内部 panic",
//			}
//			c.args = args{
//				ctx: context.Background(),
//				dialogue: &model.Dialogue{
//					ID:             1,
//					TenantID:       2,
//					TaskID:         3,
//					ConversationID: 4,
//					UserID:         "5",
//					UserMessage:    "你好",
//					State:          model.DialogueStateProcessing,
//					AuditState:     model.DialogueAuditStateUnset,
//				},
//			}
//			c.fields = fields{
//				dialogueDAO: util.Config(dao.NewMockDialogueDAO(t), func(dialogueDAO *dao.MockDialogueDAO) {
//					dialogueDAO.EXPECT().GetDialogueByID(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.ID).Return(c.args.dialogue, nil)
//					dialogueDAO.EXPECT().SetChatResult(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.ID, &model.DialogueResult{
//						State:      model.DialogueStateFail,
//						AuditState: model.DialogueAuditStateUnset,
//					}).Return(nil)
//				}),
//				conversationDAO: util.Config(dao.NewMockConversationDAO(t), func(conversationDAO *dao.MockConversationDAO) {}),
//				taskDAO: util.Config(dao.NewMockTaskDAO(t), func(taskDAO *dao.MockTaskDAO) {
//					taskDAO.EXPECT().GetTaskByID(c.args.ctx, c.args.dialogue.TenantID, c.args.dialogue.TaskID).Panic("panic")
//				}),
//				promptTemplateDAO: util.Config(dao.NewMockPromptTemplateDAO(t), nil),
//				historyExtractor:  util.Config(NewMockMessageExtractor(t), nil),
//				contentModerator:  util.Config(NewMockContentModerator(t), nil),
//				modelGateway: util.Config(rpc.NewMockModelEngineRPC(t), func(engineRPC *rpc.MockModelEngineRPC) {
//
//				}),
//			}
//			c.want = c.args.dialogue
//			return c
//		}(),
//	}
//	for _, tt := range tests {
//		t.Run(tt.name, func(t *testing.T) {
//			s := &ServiceImpl{
//				dialogueDAO:       tt.fields.dialogueDAO,
//				conversationDAO:   tt.fields.conversationDAO,
//				taskDAO:           tt.fields.taskDAO,
//				promptTemplateDAO: tt.fields.promptTemplateDAO,
//				historyExtractor:  tt.fields.historyExtractor,
//				contentModerator:  tt.fields.contentModerator,
//				modelGatewayRPC:   rpc.DefaultModelGatewayRouter,
//				metricsClient:     metrics.NewClient("test"),
//			}
//			got, _, err := s.ProcessDialogue(tt.args.ctx, tt.args.dialogue)
//			if (err != nil) != tt.wantErr {
//				t.Errorf("ProcessDialogue() error = %v, wantErr %v", err, tt.wantErr)
//				return
//			}
//			if !reflect.DeepEqual(got, tt.want) {
//				t.Errorf("ProcessDialogue() got = %v, want %v", got, tt.want)
//			}
//		})
//	}
//}
