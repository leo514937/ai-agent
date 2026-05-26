package macro

type RouterAgentToolType string

func (r RouterAgentToolType) String() string {
	return string(r)
}

const (
	RouterAgentByJailbreak   RouterAgentToolType = "jailbreak"
	RouterAgentByDirectReply RouterAgentToolType = "direct_reply"
	RouterAgentByClarify     RouterAgentToolType = "clarify"
	RouterAgentByProfile     RouterAgentToolType = "profile"
	RouterAgentByResearch    RouterAgentToolType = "research"
)
