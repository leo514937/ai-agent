package module

// ContentPoolCoreActionMsg 内容平台-内容池核心消息 - 内容入池 （特殊内容 topic与之前是有区别的）
type ContentPoolCoreActionMsg struct {
	ID                       string      `json:"id"`
	OutID                    string      `json:"out_id"`
	ContentType              string      `json:"content_type"`
	ContentPoolID            int64       `json:"content_pool_id"`
	Version                  int         `json:"version"`
	Weight                   int         `json:"weight"`
	ActionType               string      `json:"action_type"`
	CreatedTime              int64       `json:"created_time"`
	ExpiredTime              int         `json:"expired_time"`
	ContentPoolData          interface{} `json:"content_pool_data"`
	RuleIsEmpty              bool        `json:"rule_is_empty"`
	DependTaskCompletedCount int         `json:"depend_task_completed_count"`
}

// https://git.in.zhihu.com/zhihu/content-pool-core/-/blob/master/pkg/core/model/content_pool.go#L23
const poolActionINTO = "INTO"
const poolActionOUT = "OUTF"
const poolActionIOUT = "I_OUT_OF"

func (c *ContentPoolCoreActionMsg) IsPoolActionInsert() bool {
	return c.ActionType == poolActionINTO
}

func (c *ContentPoolCoreActionMsg) IsPoolActionDelete() bool {
	return c.ActionType == poolActionOUT || c.ActionType == poolActionIOUT
}
