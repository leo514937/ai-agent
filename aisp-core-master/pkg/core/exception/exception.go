package exception

var (
	ErrInternal                 = Make("AB0000", "内部错误", "内部错误")
	ErrTenantNotFound           = Make("AB0001", "租户不存在", "租户不存在")
	ErrTenantStateInvalid       = Make("AB0002", "租户状态无效", "租户状态无效")
	ErrTaskNotFound             = Make("AB0003", "任务不存在", "任务不存在")
	ErrTaskStateInvalid         = Make("AB0004", "任务状态无效", "任务状态无效")
	ErrConversationNotFound     = Make("AB0005", "会话不存在", "会话不存在")
	ErrConversationStateInvalid = Make("AB0006", "会话状态无效", "会话状态无效")
	ErrDialogueNotFound         = Make("AB0007", "对话不存在", "对话不存在")
	ErrDialogueStateInvalid     = Make("AB0008", "对话状态无效", "对话状态无效")
	ErrSpamDetected             = Make("AB0009", "检测到反作弊行为", "系统根据用户行为和用户指纹检测到反作弊行为")
	ErrRateLimitExceeded        = Make("AB0010", "超过频率限制", "请求速度超过任务设置的频率限制")
)

var (
	ErrUserMessageTooLong = Make("AB0100", "用户消息过长", "用户消息过长")
	ErrBudgetExceeded     = Make("AB0101", "超过预算", "超过预算")
)
