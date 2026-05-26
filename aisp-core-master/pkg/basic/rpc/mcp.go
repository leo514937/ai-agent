package rpc

import (
	"context"

	"github.com/mark3labs/mcp-go/mcp"
)

type MCPClient interface {
	ListTools(ctx context.Context) (*mcp.ListToolsResult, error)
	CallTool(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error)
}

func GetDemoCallToolRequest() *mcp.CallToolRequest {
	request := &mcp.CallToolRequest{}
	request.Method = "tools/call"
	request.Params.Name = "test-tool"
	request.Params.Arguments = map[string]interface{}{
		"parameter-1": "value1",
	}
	return request
}
