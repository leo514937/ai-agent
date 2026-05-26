package global_search

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

// 全网搜索API响应结构
type GlobalSearchResponse struct {
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

// NewGlobalSearchServer 创建一个新的全网搜索MCP服务器
func NewGlobalSearchServer(basePath string) *server.SSEServer {
	// 创建MCP服务器
	s := server.NewMCPServer(
		"可信全网搜索服务",
		"1.0.0",
		server.WithResourceCapabilities(false, false),
		server.WithToolCapabilities(true),
		server.WithLogging(),
	)

	// 添加global_search工具
	s.AddTool(global_searchTool())

	// 创建SSE服务器
	sseServer := server.NewSSEServer(s,
		server.WithStaticBasePath(basePath),
		server.WithSSEContextFunc(custommiddleware.AccessTokenFromRequest),
		server.WithKeepAliveInterval(1*time.Second),
	)

	return sseServer
}

// global_searchTool 定义全网搜索工具
func global_searchTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("global_search",
		mcp.WithDescription("可信全网搜索，可以提供全网内容的实时搜索能力，支持知乎站内及全网优质内容的综合检索，返回XML格式的搜索结果，包括回答、文章等多种内容类型。"),
		mcp.WithString("query",
			mcp.Required(),
			mcp.Description("搜索关键词，支持中英文混合查询，长度限制2-100字符，建议输入具体、明确的关键词以获得更精准的结果。"),
		),
		mcp.WithNumber("count",
			mcp.DefaultNumber(10),
			mcp.Description("期望返回的搜索结果数量，取值范围1-20，默认返回10条结果。"),
		),
	)

	return tool, global_searchToolHandler
}

// escapeXML 对字符串进行XML转义，防止XML注入
func escapeXML(s string) string {
	var builder strings.Builder
	for _, r := range s {
		switch r {
		case '<':
			builder.WriteString("&lt;")
		case '>':
			builder.WriteString("&gt;")
		case '&':
			builder.WriteString("&amp;")
		case '"':
			builder.WriteString("&quot;")
		default:
			builder.WriteRune(r)
		}
	}
	return builder.String()
}

// escapeXML 对字符串进行XML转义，防止XML注入
func escapeXMLContent(s string) string {
	var builder strings.Builder
	for _, r := range s {
		switch r {
		case '<':
			builder.WriteString("&lt;")
		case '>':
			builder.WriteString("&gt;")
		case '&':
			builder.WriteString("&amp;")
		default:
			builder.WriteRune(r)
		}
	}
	return builder.String()
}

// global_searchToolHandler 处理全网搜索请求
func global_searchToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	// 添加recover处理逻辑
	defer func() {
		if r := recover(); r != nil {
			log.Errorf(ctx, "global_searchToolHandler panic: %+v", r)
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

	countAny, ok := request.Params.Arguments["count"]
	if !ok {
		countAny = 10
	}

	count := cast.ToInt(countAny)
	if count == 0 {
		count = 10
	}

	if count < 1 || count > 20 {
		return nil, errors.New("count参数必须在1到20之间")
	}

	// 从context中获取AccessToken
	accessToken := custommiddleware.GetAccessTokenFromContext(ctx)

	// 验证AccessToken不为空
	if accessToken == "" {
		return nil, errors.New("未提供Authorization或Access-Token")
	}

	log.Infof(ctx, "Query: %s", query)

	// 调用全网搜索API
	var items []ZhihuItem
	var err error

	if strings.HasPrefix(accessToken, "Access-Token--") {
		token := strings.TrimPrefix(accessToken, "Access-Token--")
		items, err = searchGlobalContentByToken(ctx, query, count, token)
	} else {
		accessSecret := accessToken
		items, err = searchGlobalContentBySecret(ctx, query, count, accessSecret)
	}

	if err != nil {
		log.Errorf(ctx, "全网搜索失败: %+v", err)

		return nil, fmt.Errorf("全网搜索失败: %w", err)
	}

	// 构建响应
	var resultBuilder strings.Builder

	// 添加搜索结果，对查询参数也进行转义
	resultBuilder.WriteString(fmt.Sprintf("<global_search query=\"%s\">\n", escapeXML(query)))
	for _, item := range items {
		edit_time := ""
		if item.EditTime > 0 {
			edit_time = time.Unix(int64(item.EditTime), 0).String()
		}

		resultBuilder.WriteString(fmt.Sprintf("<search_item title=\"%s\" content_type=\"%s\" url=\"%s\" author_name=\"%s\" author_avatar=\"%s\" author_badge_text=\"%s\" edit_time=\"%s\">\n",
			escapeXML(item.Title),
			escapeXML(item.ContentType),
			escapeXML(item.Url),
			escapeXML(item.AuthorName),
			escapeXML(item.AuthorAvatar),
			escapeXML(item.AuthorBadgeText),
			edit_time,
		))
		resultBuilder.WriteString(escapeXMLContent(item.ContentText))
		resultBuilder.WriteString("\n</search_item>\n")
	}

	resultBuilder.WriteString("</global_search>")

	result := resultBuilder.String()

	log.Infof(ctx, "result: %s", result)

	return mcp.NewToolResultText(result), nil
}

// searchGlobalContentByToken 调用全网搜索API
func searchGlobalContentByToken(ctx context.Context, query string, count int, accessToken string) ([]ZhihuItem, error) {
	// 构建API请求URL
	apiURL := config.GetString("content_global_search_api_url", "https://platform.zhihu.com/api/v1/content/global_search")

	// 构建查询参数
	params := url.Values{}
	params.Add("Query", query)
	params.Add("Count", cast.ToString(count))

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
	var searchResp GlobalSearchResponse
	if err := json.Unmarshal(body, &searchResp); err != nil {
		return nil, fmt.Errorf("解析JSON响应失败: %w", err)
	}

	// 检查API响应状态码
	if searchResp.Code != 0 {
		return nil, fmt.Errorf("API返回错误: %s", searchResp.Message)
	}

	return searchResp.Data.Items, nil
}

// searchGlobalContent 调用全网搜索API
func searchGlobalContentBySecret(ctx context.Context, query string, count int, accessSecret string) ([]ZhihuItem, error) {
	// 构建API请求URL
	apiURL := config.GetString("content_global_search_api_url", "https://platform.zhihu.com/api/v1/content/global_search")

	// 构建查询参数
	params := url.Values{}
	params.Add("Query", query)
	params.Add("Count", cast.ToString(count))

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
	var searchResp GlobalSearchResponse
	if err := json.Unmarshal(body, &searchResp); err != nil {
		return nil, fmt.Errorf("解析JSON响应失败: %w", err)
	}

	// 检查API响应状态码
	if searchResp.Code != 0 {
		return nil, fmt.Errorf("API返回错误: %s", searchResp.Message)
	}

	return searchResp.Data.Items, nil
}
