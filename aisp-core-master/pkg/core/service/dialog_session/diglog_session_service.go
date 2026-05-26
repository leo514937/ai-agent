package service

import (
	"context"
	"sort"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	dialogService "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_record"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type DialogSessionService interface {
	// CreateSession 创建Session
	CreateSession(ctx context.Context, model *proto.CreateSessionRequest) (int64, error)
	GetSessionInfo(ctx context.Context, sessionId int64) (*model.DialogSession, error)
}

type DialogSessionServiceImpl struct {
	dialogueSessionDao    dao.DialogSessionDao
	dialogueRecordDao     dao.DialogRecordDAO
	dialogueRecordService dialogService.DialogService
	idGenerator           dao.IDGenerator
}

var (
	_ DialogSessionService = (*DialogSessionServiceImpl)(nil)
)

func NewDialogSessionService() DialogSessionService {
	return &DialogSessionServiceImpl{
		dialogueSessionDao:    daoImpl.NewDialogSessionDao(),
		dialogueRecordDao:     daoImpl.DefaultDialogRecordDAO,
		dialogueRecordService: dialogService.NewDefaultDialogService(),
		idGenerator:           dao.NewIDGenerator(),
	}
}

func (d *DialogSessionServiceImpl) GetSessionInfo(ctx context.Context, sessionId int64) (*model.DialogSession, error) {
	logger := log.WithField(ctx, "GetSessionInfo-Request", sessionId)

	result, dbErr := d.dialogueSessionDao.GetSessionInfo(ctx, sessionId)
	if dbErr != nil {
		logger.WithError(ctx, dbErr).Errorf(ctx, "get session info failed, error: %v", dbErr)
		return nil, dbErr
	}

	return result, nil
}

func (d *DialogSessionServiceImpl) CreateSession(ctx context.Context, dto *proto.CreateSessionRequest) (int64, error) {
	logger := log.WithField(ctx, "CreateSession-Request", dto)
	sessionId, err := d.idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeSessionId)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "create session id failed, error: %v", err)
		return 0, err
	}

	sessionModel, mErr := model.CreateDialogSessionByProto(dto, sessionId)
	if mErr != nil {
		logger.WithError(ctx, mErr).Errorf(ctx, "create session model failed, error: %v", mErr)
		return 0, err
	}

	_, dbErr := d.dialogueSessionDao.CreateSession(ctx, sessionModel)
	if dbErr != nil {
		logger.WithError(ctx, mErr).Errorf(ctx, "create session failed, error: %v", dbErr)
		return 0, err
	}

	err = d.copyDialoguesIfFromShare(ctx, dto, sessionModel)
	if err != nil {
		return 0, err
	}

	// 存储用户指定历史
	if len(dto.GetDialogMessages()) > 0 {
		now := time.Now()
		for _, dialogWrapper := range dto.GetDialogMessages() {
			wrapper := message.DialogueWrapper{}
			if dialogWrapper.GetQuery() != nil {
				dialog := newDialogFormProtoChatRequest(dto.GetType().String(), dto.GetMemberId(), sessionId, dialogWrapper.GetQuery(), now)
				dialog.CreateType = model.DialogCreateTypeInput.ToConvert()
				dialog.RoleType = model.RoleTypeUser.ToConvert()
				wrapper.Query = dialog
				now = now.Add(1 * time.Second)
			}
			if wrapper.Query != nil && dialogWrapper.GetAnswer() != nil {
				dialog := newDialogFormProtoChatRequest(dto.GetType().String(), dto.GetMemberId(), sessionId, dialogWrapper.GetAnswer(), now)
				dialog.CreateType = model.DialogCreateTypeLLM.ToConvert()
				dialog.RoleType = model.RoleTypeAI.ToConvert()
				dialog.ParentMessageId = wrapper.Query.MessageId
				dialog.MessageGroupId = wrapper.Query.MessageId
				wrapper.Answer = dialog
				now = now.Add(1 * time.Second)
			}
			_, err := d.dialogueRecordService.SaveOrUpdateDialogWrapper(ctx, &wrapper)
			if err != nil {
				return sessionId, err
			}
		}
	}

	return sessionId, nil
}

// 分享的时候把历史对话copy一份，使用新的sessionid
func (d *DialogSessionServiceImpl) copyDialoguesIfFromShare(ctx context.Context, dto *proto.CreateSessionRequest, sessionModel *model.DialogSession) error {
	if dto == nil || dto.ExtraInfo == nil || dto.ExtraInfo.ShareSessionId <= 0 {
		return nil
	}
	if dto.ExtraInfo.ShareEndMessageId <= 0 && len(dto.ExtraInfo.ShareMessageIds) == 0 {
		return nil
	}

	logger := log.WithField(ctx, "CreateSession-CopyDialoguesIfFromShare", dto)

	// MessageIds 与 EndMessageId 二选一
	shareSessionId := dto.ExtraInfo.ShareSessionId
	shareMessageIds := lo.Map(dto.GetExtraInfo().GetShareMessageIds(), func(item int64, _ int) string {
		return cast.ToString(item)
	})
	shareEndMessageId := dto.ExtraInfo.ShareEndMessageId

	logger.Infof(ctx, "create session from share. shareSessionId: %d", shareSessionId)

	var dialogues []*model.DialogRecord
	if len(shareMessageIds) > 0 {
		dialogueRes, err := d.dialogueRecordDao.GetDialogByGroupIds(ctx, shareSessionId, shareMessageIds)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "get dialogues failed, error: %v", err)
			return err
		}
		dialogues = append(dialogues, dialogueRes...)
	} else {
		lastDialogue, err := d.dialogueRecordDao.GetDialogBySessionIdAndMessageId(ctx, shareSessionId, cast.ToString(shareEndMessageId))
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "get last dialogue failed, error: %v", err)
			return err
		}
		groupDialogue, err := d.dialogueRecordDao.GetDialogBySessionIdAndMessageId(ctx, shareSessionId, lastDialogue.ParentMessageId)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "get group dialogue failed, error: %v", err)
			return err
		}
		dialogRecord := lo.Ternary(groupDialogue.CreatedAt.After(lastDialogue.CreatedAt), groupDialogue, lastDialogue)
		dialogueRes, err := d.dialogueRecordDao.GetDialogsBySessionIdAndMaxCreateTime(ctx, shareSessionId, dialogRecord.CreatedAt)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "get dialogues failed, error: %v", err)
			return err
		}
		dialogues = append(dialogues, dialogueRes...)
	}

	// 处理对话记录，如果有存在最后一次对话被过期的情况 需要再将状态改为未过期
	groupByMessageGroupId := lo.GroupBy(dialogues, func(item *model.DialogRecord) string {
		return item.MessageGroupId
	})
	for groupId, groupList := range groupByMessageGroupId {
		if groupId == "" {
			continue
		}
		currGroupMessages := lo.GroupBy(groupList, func(item *model.DialogRecord) string {
			if item.ParentMessageId != "" {
				return item.ParentMessageId
			}
			return item.MessageId
		})

		// 时间戳,DialogueWrapper
		tmpArr := make([]*lo.Tuple2[int64, *message.DialogueWrapper], 0)
		for _, currDialogs := range currGroupMessages {
			wrapper := message.DialogueWrapper{}
			for _, dialog := range currDialogs {
				switch dialog.RoleType {
				case model.RoleTypeUser.ToConvert():
					wrapper.Query = dialog
				case model.RoleTypeAI.ToConvert():
					wrapper.Answer = dialog
				}
			}
			if wrapper.Query == nil || wrapper.Answer == nil {
				continue
			}
			tmpArr = append(tmpArr, &lo.Tuple2[int64, *message.DialogueWrapper]{A: wrapper.Query.RecordAt.UnixMilli(), B: &wrapper})
		}
		// 按照时间戳排序 倒序
		sort.Slice(tmpArr, func(i, j int) bool {
			return tmpArr[i].A > tmpArr[j].A
		})
		// 处理重答记录 同一个group下 最新记录为不过期 其余的全部过期
		for i, t := range tmpArr {
			if i == 0 {
				t.B.Query.Exceeded = cast.ToInt64(macro.Dict_No)
				t.B.Answer.Exceeded = cast.ToInt64(macro.Dict_No)
			} else {
				t.B.Query.Exceeded = cast.ToInt64(macro.Dict_Yes)
				t.B.Answer.Exceeded = cast.ToInt64(macro.Dict_Yes)
			}
		}
	}

	// 重置数据
	lo.ForEach(dialogues, func(dialogue *model.DialogRecord, _ int) {
		dialogue.SessionId = sessionModel.SessionId
		dialogue.ID = 0
	})

	result, err := d.dialogueRecordDao.SaveDialogs(ctx, dialogues)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "save dialogues failed, result: %v, error: %v", result, err)
		return err
	}
	return nil
}

// newDialogFormProtoChatRequest 新建消息
func newDialogFormProtoChatRequest(scene string, memberId int64, sessionId int64, request *proto.DialogMessage, now time.Time) *model.DialogRecord {
	return &model.DialogRecord{
		Scene:          scene,
		MemberId:       memberId,
		AiId:           macro.DefAiUserAiAndSearchTab,
		SessionId:      sessionId,
		MessageGroupId: request.GetMessageId(),
		MessageId:      request.GetMessageId(),
		MessageType:    int64(proto.ChatMessageType_TEXT),
		MessageContent: request.GetMessage(),
		ErrorType:      model.DialogErrorTypeNormal.ToConvert(),
		RecordAt:       now,
		CreatedAt:      now,
		UpdatedAt:      now,
	}
}
