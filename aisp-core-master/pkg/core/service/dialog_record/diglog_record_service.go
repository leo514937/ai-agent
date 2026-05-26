package word

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/pkg/errors"
)

type DialogService interface {

	// SaveOrUpdateDialogWrapper 保存/更新 对话历史
	SaveOrUpdateDialogWrapper(ctx context.Context, wrapper *message.DialogueWrapper) (bool, error)

	// GetDialogListBySessionId 查询wrapper历史
	GetDialogListBySessionId(ctx context.Context, sessionId int64, limit uint64) ([]*model.DialogRecord, error)

	// GetDialogBySessionIdAndMessageId 根据SessionId 和 消息Id  获取会话
	GetDialogBySessionIdAndMessageId(ctx context.Context, sessionId int64, messageId string) (*model.DialogRecord, error)
}

type DialogServiceImpl struct {
	dao dao.DialogRecordDAO
}

var (
	_                    DialogService = (*DialogServiceImpl)(nil)
	DefaultDialogService DialogService
)

func init() {
	DefaultDialogService = NewDefaultDialogService()
}

func NewDefaultDialogService() *DialogServiceImpl {
	return &DialogServiceImpl{
		dao: daoImpl.DefaultDialogRecordDAO,
	}
}

// GetDialogListBySessionId 保存消息
func (s *DialogServiceImpl) GetDialogListBySessionId(ctx context.Context, sessionId int64, limit uint64) ([]*model.DialogRecord, error) {
	return s.dao.GetDialogListBySessionId(ctx, sessionId, limit)
}

// GetDialogBySessionIdAndMessageId 根据SessionId 和 消息Id  获取会话
func (s *DialogServiceImpl) GetDialogBySessionIdAndMessageId(ctx context.Context, sessionId int64, messageId string) (*model.DialogRecord, error) {
	return s.dao.GetDialogBySessionIdAndMessageId(ctx, sessionId, messageId)
}

// SaveOrUpdateDialogWrapper 保存/修改 消息
func (s *DialogServiceImpl) SaveOrUpdateDialogWrapper(ctx context.Context, wrapper *message.DialogueWrapper) (bool, error) {
	newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 2*time.Second)
	defer cancel()

	logger := log.WithField(ctx, "SaveOrUpdateDialogWrapper", wrapper)
	if wrapper == nil {
		err := errors.New("SaveOrUpdateDialogWrapper wrapper is nil")
		logger.Error(ctx, err)
		return false, err
	}

	wg := sync.WaitGroup{}
	if wrapper.Query != nil && wrapper.Query.MessageId != "" {
		s.saveOrUpdateDialog(newCtx, wrapper.Query, &wg, "Query")
	}
	if wrapper.Answer != nil && wrapper.Answer.MessageId != "" {
		// 强制Answer的MessageGroupId 与 Query的MessageGroupId 保持一致, 捆绑数据组
		// 在同一个query 有 多次回答时 或 修改query时，便于将这一批次的数据组绑定在一起
		if wrapper.Query != nil {
			wrapper.Answer.MessageGroupId = wrapper.Query.MessageGroupId
		}
		s.saveOrUpdateDialog(newCtx, wrapper.Answer, &wg, "Answer")
	}
	wg.Wait()
	return true, nil
}

func (s *DialogServiceImpl) saveOrUpdateDialog(
	ctx context.Context, dto *model.DialogRecord, wg *sync.WaitGroup, flag string) {
	logger := log.WithField(ctx, "SaveOrUpdateDialogWrapper", dto)
	wg.Add(1)
	safe_group.SafeGo(func() error {
		defer wg.Done()
		_, err := s.dao.SaveOrUpdateDialog(ctx, dto)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "save %s diglog error => dto:%+v msg:%+v \n", flag, dto, err)
			return err
		}
		return nil
	}, "SaveOrUpdateDialog-"+flag)
}
