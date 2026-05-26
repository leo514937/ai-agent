package zhihu

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	custommiddleware "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver/middleware"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"github.com/spf13/cast"
)

// 知乎搜索API响应结构
type ZhihuSearchResponse struct {
	Code      int    `json:"Code"`
	Message   string `json:"Message"`
	RequestID string `json:"RequestID"`
	Data      struct {
		HasMore bool        `json:"HasMore"`
		Items   []ZhihuItem `json:"Items"`
	} `json:"Data"`
}

// 知乎内容项结构
type ZhihuItem struct {
	Title           string   `json:"Title"`           //
	ContentType     string   `json:"ContentType"`     //
	ContentID       string   `json:"ContentID"`       //
	ContentText     string   `json:"ContentText"`     //
	Url             string   `json:"Url"`             //
	CommentCount    int64    `json:"CommentCount"`    //
	VoteUpCount     int64    `json:"VoteUpCount"`     //
	AuthorName      string   `json:"AuthorName"`      //
	AuthorAvatar    string   `json:"AuthorAvatar"`    //
	AuthorBadge     string   `json:"AuthorBadge"`     //
	AuthorBadgeText string   `json:"AuthorBadgeText"` //
	EditTime        int64    `json:"EditTime"`        //
	ContentImage    []string `json:"ContentImage"`    //
}

// NewZhihuServer 创建一个新的知乎MCP服务器
func NewZhihuServer(basePath string) *server.SSEServer {
	// 创建MCP服务器
	s := server.NewMCPServer(
		"知乎搜索服务",
		"1.0.0",
		server.WithResourceCapabilities(false, false),
		server.WithToolCapabilities(true),
		server.WithLogging(),
	)

	// 添加zhihu_search工具
	s.AddTool(zhihuSearchTool())

	// 创建SSE服务器
	sseServer := server.NewSSEServer(s,
		server.WithStaticBasePath(basePath),
		server.WithSSEContextFunc(custommiddleware.AccessTokenFromRequest),
		server.WithKeepAliveInterval(1*time.Second),
	)

	return sseServer
}

// zhihuSearchTool 定义知乎搜索工具
func zhihuSearchTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("zhihu_search",
		mcp.WithDescription("知乎搜索，可以提供知乎站内内容的实时搜索能力"),
		mcp.WithString("query",
			mcp.Required(),
			mcp.Description("搜索问题（长度：>=2 and <=100）"),
		),
	)

	return tool, zhihuSearchToolHandler
}

// zhihuSearchToolHandler 处理知乎搜索请求
func zhihuSearchToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	// 添加recover处理逻辑
	defer func() {
		if r := recover(); r != nil {
			log.Errorf(ctx, "zhihuSearchToolHandler panic: %+v", r)
		}
	}()

	// 获取查询参数
	queryAny, ok := request.Params.Arguments["query"]
	if !ok {
		return nil, errors.New("query参数必须提供")
	}

	query, ok := queryAny.(string)
	if !ok {
		return nil, errors.New("query参数必须是字符串")
	}

	// 验证查询参数长度
	queryLen := util.UnicodeLen(query)
	if queryLen < 2 || queryLen > 100 {
		return nil, errors.New("query参数长度必须在2到100之间")
	}

	// 从context中获取AccessToken
	accessToken := custommiddleware.GetAccessTokenFromContext(ctx)

	// 验证AccessToken不为空
	if accessToken == "" {
		return nil, errors.New("未提供Authorization或Access-Token")
	}

	log.Infof(ctx, "Query: %s", query)

	// 调用知乎搜索API
	var items []ZhihuItem
	var err error

	if strings.HasPrefix(accessToken, "Access-Token--") {
		token := strings.TrimPrefix(accessToken, "Access-Token--")
		items, err = searchZhihuContentByToken(ctx, query, token)
	} else {
		items, err = searchZhihuContentBySecret(ctx, query, accessToken)
	}

	if err != nil {
		return nil, fmt.Errorf("知乎搜索失败: %w", err)
	}

	// 构建响应
	var resultBuilder strings.Builder

	// 添加知乎协议
	resultBuilder.WriteString("<System>\n")
	resultBuilder.WriteString("- 使用搜索结果时，必须输出以下内容\n")
	resultBuilder.WriteString("    - title 内容标题\n")
	resultBuilder.WriteString("    - url 内容链接\n")
	resultBuilder.WriteString("    - author_name 作者\n")
	resultBuilder.WriteString("</System>\n")

	// 添加搜索结果
	resultBuilder.WriteString(fmt.Sprintf("<zhihu_search query=\"%s\">\n", query))
	for _, item := range items {
		resultBuilder.WriteString(fmt.Sprintf("<zhihu_item title=\"%s\" content_type=\"%s\" url=\"%s\" author_name=\"%s\" author_avatar=\"%s\" author_badge_text=\"%s\" edit_time=\"%s\">\n",
			item.Title,
			item.ContentType,
			item.Url,
			item.AuthorName,
			item.AuthorAvatar,
			item.AuthorBadgeText,
			time.Unix(int64(item.EditTime), 0).String(),
		))
		resultBuilder.WriteString(item.ContentText)
		resultBuilder.WriteString("\n</zhihu_item>\n")
	}

	resultBuilder.WriteString("</zhihu_search>")

	result := resultBuilder.String()

	log.Infof(ctx, "result: %s", result)

	return mcp.NewToolResultText(result), nil
}

// searchZhihuContentByToken 调用知乎搜索API
func searchZhihuContentByToken(ctx context.Context, query string, accessToken string) ([]ZhihuItem, error) {
	// 构建API请求URL
	apiURL := config.GetString("content_search_api_url", "https://platform.zhihu.com/api/v1/content/search")

	// 构建查询参数
	params := url.Values{}
	params.Add("Query", query)
	params.Add("Count", "10") // 默认返回10条结果

	// 创建HTTP请求
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, fmt.Errorf("创建HTTP请求失败: %w", err)
	}

	// 设置请求头
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Access-Token", accessToken)

	// 发送请求
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("发送HTTP请求失败: %w", err)
	}
	defer resp.Body.Close()

	// 读取响应
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取响应失败: %w", err)
	}

	// 检查HTTP状态码
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API返回错误状态码: %d, 响应: %s", resp.StatusCode, string(body))
	}

	// 解析JSON响应
	var searchResp ZhihuSearchResponse
	if err := json.Unmarshal(body, &searchResp); err != nil {
		return nil, fmt.Errorf("解析JSON响应失败: %w", err)
	}

	// 检查API响应状态码
	if searchResp.Code != 0 {
		return nil, fmt.Errorf("API返回错误: %s", searchResp.Message)
	}

	return searchResp.Data.Items, nil
}

// searchZhihuContent 调用知乎搜索API
func searchZhihuContentBySecret(ctx context.Context, query string, accessSecret string) ([]ZhihuItem, error) {
	// 构建API请求URL
	apiURL := config.GetString("content_search_api_url", "https://platform.zhihu.com/api/v1/content/search")

	// 构建查询参数
	params := url.Values{}
	params.Add("Query", query)
	params.Add("Count", "10") // 默认返回10条结果

	// 创建HTTP请求
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, fmt.Errorf("创建HTTP请求失败: %w", err)
	}

	// 设置请求头
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", accessSecret))
	req.Header.Set("X-Request-Timestamp", cast.ToString(time.Now().Unix()))

	// 发送请求
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("发送HTTP请求失败: %w", err)
	}
	defer resp.Body.Close()

	// 读取响应
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取响应失败: %w", err)
	}

	// 检查HTTP状态码
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API返回错误状态码: %d, 响应: %s", resp.StatusCode, string(body))
	}

	// 解析JSON响应
	var searchResp ZhihuSearchResponse
	if err := json.Unmarshal(body, &searchResp); err != nil {
		return nil, fmt.Errorf("解析JSON响应失败: %w", err)
	}

	// 检查API响应状态码
	if searchResp.Code != 0 {
		return nil, fmt.Errorf("API返回错误: %s", searchResp.Message)
	}

	return searchResp.Data.Items, nil
}
