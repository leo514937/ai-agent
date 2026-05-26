package model

import "time"

const (
	NotDeleted = 1
	Deleted    = 2
)

const (
	AccountStatusNotAuth = 1
	AccountStatusAuth    = 2
)

const (
	RoleNormalUser = 1
	RoleAdmin      = 2
)

// 账户表
type TableOpenapiAccount struct {
	ID            int64     `borm:"primary_key"`
	Name          string    `borm:"column:name"`           // 用户姓名
	Mobile        string    `borm:"column:mobile"`         // 用户手机号，由于安全原因已经废弃
	EncryptMobile string    `borm:"column:encrypt_mobile"` // 用户加密的手机号
	Email         string    `borm:"column:email"`          // 用户邮箱
	Corporation   string    `borm:"column:corporation"`    // 公司/学校名称
	CreateTime    time.Time `borm:"column:create_time"`    // 创建时间
	UpdateTime    time.Time `borm:"column:update_time"`    // 更新时间
	Industry      string    `borm:"column:industry"`       // 行业
	Position      string    `borm:"column:position"`       // 职位
	Status        int64     `borm:"column:status"`         // 账号状态，1-未认证，2-已认证
	IsDeleted     int64     `borm:"column:is_deleted"`     // 1-未删除，2-已删除
	Role          int64     `borm:"column:role"`           // 账号角色，1-普通用户，2-管理员
	MemberID      int64     `borm:"column:member_id"`      // 知乎内部member_id
}

func (t *TableOpenapiAccount) TableName() string {
	return "openapi_account"
}
