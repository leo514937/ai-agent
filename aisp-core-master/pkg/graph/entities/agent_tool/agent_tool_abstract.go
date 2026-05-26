package agent_tool

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
)

type ToolBase struct {
	name        string
	description string
	parameters  map[string]interface{}
	requestCtx  *entities.RequestContext
}

func (t *ToolBase) SetRequestCtx(requestCtx *entities.RequestContext) *ToolBase {
	t.requestCtx = requestCtx
	return t
}

func (t *ToolBase) SetName(name string) *ToolBase {
	t.name = name
	return t
}

func (t *ToolBase) SetDescription(description string) *ToolBase {
	t.description = description
	return t
}

func (t *ToolBase) SetParameters(parameters map[string]interface{}) *ToolBase {
	t.parameters = parameters
	return t
}

func (t *ToolBase) GetRequestCtx() *entities.RequestContext {
	return t.requestCtx
}
func (t *ToolBase) GetName() string {
	return t.name
}

func (t *ToolBase) GetDescription() string {
	return t.description
}

func (t *ToolBase) GetParameters() map[string]interface{} {
	return t.parameters
}

func (t *ToolBase) ToFunction() dto.Tool {
	return dto.Tool{
		Type: "function",
		Function: dto.ToolFunction{
			Name:        t.name,
			Description: t.description,
			Parameters:  t.parameters,
		},
	}
}

type IAgentTool interface {
	GetName() string
	GetDescription() string
	GetParameters() map[string]interface{}
	ToFunction() dto.Tool
	Run(ctx context.Context, toolInfo dto.FunctionCallResult) ([]*entities.Item, error)
}
