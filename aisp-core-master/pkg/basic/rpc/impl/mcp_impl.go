package impl

import (
	"context"
	"fmt"
	"os"

	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config/config_struct"
	mcpclient "github.com/mark3labs/mcp-go/client"
	"github.com/mark3labs/mcp-go/mcp"
)

type McpClient struct {
	ServerName    string
	ServerVersion string
	Client        *mcpclient.Client
}

var mcpClientMap map[string]*McpClient

// 对每一个 mcp server 创建一个 mcp client，保持 1:1 连接
func init() {
	mcpClientMap = make(map[string]*McpClient)
	mcpConfig := getMcpConfig()

	if mcpConfig == nil {
		return
	}

	for name, config := range mcpConfig.McpServers {
		client, err := genMcpClient(config.URL)
		if err != nil {
			panic(fmt.Sprintf("failed to create mcp client for %s: %v", name, err))
		}
		mcpClientMap[name] = client
	}
}

func getMcpConfig() *config_struct.McpConfig {
	mcpConfig := conf.GetMcpConfig()
	if mcpConfig == nil {
		return nil
	}
	// ACCESS_TOKEN 是云平台登录秘钥，点击云平台左下角头像获取，todo: 后面改成统一鉴权
	accessToken := os.Getenv("ACCESS_TOKEN")
	if accessToken == "" {
		return nil
	}
	for _, item := range mcpConfig.McpServers {
		item.URL = item.URL + "?token=" + accessToken
	}
	return mcpConfig
}

func genMcpClient(url string) (*McpClient, error) {
	ctx := context.Background()
	client, err := mcpclient.NewSSEMCPClient(url)
	if err != nil {
		return nil, fmt.Errorf("new sse mcp client error: %v", err)
	}

	if err = client.Start(ctx); err != nil {
		return nil, fmt.Errorf("start error: %v", err)
	}

	initResult, err := client.Initialize(ctx, mcp.InitializeRequest{})
	if err != nil {
		return nil, fmt.Errorf("initialize error: %v", err)
	}

	return &McpClient{
		ServerName:    initResult.ServerInfo.Name,
		ServerVersion: initResult.ServerInfo.Version,
		Client:        client,
	}, nil
}

func GetMCPClient(serverName string) *McpClient {
	return mcpClientMap[serverName]
}

func (m *McpClient) ListTools(ctx context.Context) (*mcp.ListToolsResult, error) {
	return m.Client.ListTools(ctx, mcp.ListToolsRequest{})
}

func (m *McpClient) CallTool(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return m.Client.CallTool(ctx, request)
}
