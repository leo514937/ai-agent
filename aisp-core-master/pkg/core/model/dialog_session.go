package model

import (
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/pkg/errors"
)

type DialogSession struct {
	ID        int64     `json:"id" borm:"primary_key"`
	SessionId int64     `json:"session_id"`                 // 会话Id
	MemberId  int64     `json:"member_id"`                  // 用户Id
	Scene     string    `json:"scene"`                      // 场景 AI_TAB SEARCH_TAB DISCOVERY_TAB PC_DISCOVERY_TAB
	ExtraInfo string    `json:"extra_info" borm:""`         // 额外扩展信息
	Deleted   int64     `json:"deleted"`                    // 是否删除 0否 1是
	CreatedAt time.Time `json:"created_at" borm:"readonly"` // 创建时间 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt time.Time `json:"updated_at" borm:"readonly"` // 修改时间 设置borm只读，利用数据库的能力生成 CreatedAt
}

// CreateDialogSessionByProto 创建
func CreateDialogSessionByProto(dto *proto.CreateSessionRequest, sessionId int64) (*DialogSession, error) {
	dialogSession := &DialogSession{
		MemberId:  dto.GetMemberId(),
		Scene:     dto.GetType().String(),
		SessionId: sessionId,
		Deleted:   0,
	}

	dialogSession.ExtraInfo = util.GetJSONIgnoreError(dto.GetExtraInfo())
	return dialogSession, nil
}

// CheckExtraInfoByDocParagraph 检查附加信息
func CheckExtraInfoByDocParagraph(extraInfo *proto.ExtraInfo) error {
	// 校验附加参数是否为空
	if extraInfo.GetDocQaExtraInfo() == nil {
		return errors.Errorf("extraInfo DocQaExtraInfo is nil")
	}

	// 校验文章信息是否为空
	if extraInfo.GetDocQaExtraInfo().GetDocId() == 0 ||
		extraInfo.GetDocQaExtraInfo().GetContentType() == "" {
		return errors.Errorf("extraInfo DocQaExtraInfo doc is nil")
	}

	return nil
}
