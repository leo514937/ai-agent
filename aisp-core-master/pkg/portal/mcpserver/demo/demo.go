package demo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strconv"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/author"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func NewDemoServer(basePath string) *server.SSEServer {
	// Create MCP server
	s := server.NewMCPServer(
		"Demo 🚀",
		"1.0.0",
		server.WithResourceCapabilities(true, true),
		server.WithLogging(),
	)

	// Add tool
	s.AddTool(helloWorldTool())
	s.AddTool(helloSamplingTool())
	s.AddTool(calculateTool())
	s.AddTool(profileTool())

	// Add resource
	s.AddResource(readmeResource())
	s.AddResourceTemplate(profileResourceTemplate())

	// Add prompt
	s.AddPrompt(greetingPrompt())
	s.AddPrompt(profilePrompt())

	sseServer := server.NewSSEServer(s, server.WithStaticBasePath(basePath))

	return sseServer
}

func helloWorldTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("hello_world",
		mcp.WithDescription("Say hello to someone"),
		mcp.WithString("name",
			mcp.Required(),
			mcp.Description("Name of the person to greet"),
		),
	)

	return tool, helloWorldToolHandler
}
func helloWorldToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sseServer := server.ServerFromContext(ctx)

	nameAny, ok := request.Params.Arguments["name"]
	if !ok {
		return nil, errors.New("name must be provided")
	}

	name, ok := nameAny.(string)
	if !ok {
		return nil, errors.New("name must be a string")
	}

	sessionID := ""
	session := server.ClientSessionFromContext(ctx)
	if session != nil {
		sessionID = session.SessionID()
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/helloWorldToolHandler", map[string]any{
			"name":      name,
			"sessionID": sessionID,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return mcp.NewToolResultText(fmt.Sprintf("Hello, %s! sessionID: %s", name, sessionID)), nil
}

func helloSamplingTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("hello_world",
		mcp.WithDescription("Say hello to someone"),
		mcp.WithString("name",
			mcp.Required(),
			mcp.Description("Name of the person to greet"),
		),
	)

	return tool, helloSamplingToolHandler
}

func helloSamplingToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sseServer := server.ServerFromContext(ctx)

	nameAny, ok := request.Params.Arguments["name"]
	if !ok {
		return nil, errors.New("name must be provided")
	}

	name, ok := nameAny.(string)
	if !ok {
		return nil, errors.New("name must be a string")
	}

	message := mcp.SamplingMessage{
		Role:    mcp.RoleUser,
		Content: mcp.NewTextContent(fmt.Sprintf("What's the name %s mean?", name)),
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/helloSamplingToolHandler", map[string]any{
			"name": name,
		})
		log.Info(ctx, "send notification to client")

		req := mcp.CreateMessageRequest{
			Request: mcp.Request{
				Method: "sampling/createMessage",
			},
		}
		req.Params.Messages = []mcp.SamplingMessage{message}

		sseServer.SendNotificationToClient(ctx, "sampling/createMessage", map[string]any{
			"params": req.Params,
		})
		log.Info(ctx, "send sampling/createMessage to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return mcp.NewToolResultText(fmt.Sprintf("Hello, %s!\n", name)), nil
}

func calculateTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("calculate",
		mcp.WithDescription("Perform basic arithmetic operations"),
		mcp.WithString("operation",
			mcp.Required(),
			mcp.Description("The operation to perform (add, subtract, multiply, divide)"),
			mcp.Enum("add", "subtract", "multiply", "divide"),
		),
		mcp.WithNumber("x",
			mcp.Required(),
			mcp.Description("First number"),
		),
		mcp.WithNumber("y",
			mcp.Required(),
			mcp.Description("Second number"),
		),
	)

	return tool, calculateToolHandler
}

func calculateToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sseServer := server.ServerFromContext(ctx)

	opAny, ok := request.Params.Arguments["operation"]
	if !ok {
		return nil, errors.New("operation must be provided")
	}

	op, ok := opAny.(string)
	if !ok {
		return nil, errors.New("operation must be a string")
	}

	xAny, ok := request.Params.Arguments["x"]
	if !ok {
		return nil, errors.New("x must be provided")
	}

	x, ok := xAny.(float64)
	if !ok {
		return nil, errors.New("x must be a float64")
	}

	yAny, ok := request.Params.Arguments["y"]
	if !ok {
		return nil, errors.New("y must be provided")
	}

	y, ok := yAny.(float64)
	if !ok {
		return nil, errors.New("y must be a float64")
	}

	var result float64
	switch op {
	case "add":
		result = x + y
	case "subtract":
		result = x - y
	case "multiply":
		result = x * y
	case "divide":
		if y == 0 {
			return nil, errors.New("Cannot divide by zero")
		}
		result = x / y
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/calculateToolHandler", map[string]any{
			"operation": op,
			"x":         x,
			"y":         y,
			"result":    result,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}
	return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
}

func profileTool() (mcp.Tool, server.ToolHandlerFunc) {
	tool := mcp.NewTool("profile",
		mcp.WithDescription("Get user profile"),
		mcp.WithString("user_id",
			mcp.Required(),
		),
	)

	return tool, profileToolHandler
}

func profileToolHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sseServer := server.ServerFromContext(ctx)

	userIDAny, ok := request.Params.Arguments["user_id"]
	if !ok {
		return nil, errors.New("user_id is required")
	}

	userID, ok := userIDAny.(string)
	if !ok {
		return nil, errors.New("user_id must be a string")
	}

	log.Info(ctx, "profileToolHandler userID: %s", userID)

	profile, err := getUserProfile(ctx, userID) // Your DB/API call here
	if err != nil {
		return nil, err
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/profileResourceTemplateHandler", map[string]any{
			"userID":  userID,
			"profile": profile,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return mcp.NewToolResultText(profile), nil

}
func readmeResource() (mcp.Resource, server.ResourceHandlerFunc) {
	resource := mcp.NewResource(
		"docs://readme",
		"Project README",
		mcp.WithResourceDescription("The project's README file"),
		mcp.WithMIMEType("text/markdown"),
	)

	return resource, readmeResourceHandler
}

func readmeResourceHandler(ctx context.Context, request mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
	sseServer := server.ServerFromContext(ctx)

	content, err := os.ReadFile("README.md")
	if err != nil {
		return nil, err
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/readmeResourceHandler", map[string]any{
			"content": string(content),
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return []mcp.ResourceContents{
		mcp.TextResourceContents{
			URI:      "docs://readme",
			MIMEType: "text/markdown",
			Text:     string(content),
		},
	}, nil
}

func profileResourceTemplate() (mcp.ResourceTemplate, server.ResourceTemplateHandlerFunc) {
	template := mcp.NewResourceTemplate(
		"users://{id}/profile",
		"User Profile",
		mcp.WithTemplateDescription("Returns user profile information"),
		mcp.WithTemplateMIMEType("application/json"),
	)

	return template, profileResourceTemplateHandler
}

func profileResourceTemplateHandler(ctx context.Context, request mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
	sseServer := server.ServerFromContext(ctx)

	// Extract ID from the URI using regex matching
	// The server automatically matches URIs to templates
	userID := extractIDFromURI(request.Params.URI)

	log.Info(ctx, "profileResourceTemplateHandler userID: %s", userID)

	profile, err := getUserProfile(ctx, userID) // Your DB/API call here
	if err != nil {
		return nil, err
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/profileResourceTemplateHandler", map[string]any{
			"userID":  userID,
			"profile": profile,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}
	return []mcp.ResourceContents{
		mcp.TextResourceContents{
			URI:      request.Params.URI,
			MIMEType: "application/json",
			Text:     profile,
		},
	}, nil
}

func extractIDFromURI(uri string) string {
	// 解析users://{id}/profile
	re := regexp.MustCompile(`users://(\d+)/profile`)
	matches := re.FindStringSubmatch(uri)
	if len(matches) > 1 {
		return matches[1]
	}
	return ""
}

// 调用创作者信息API
func getUserProfile(ctx context.Context, userID string) (string, error) {

	// 将userID转换为int64
	userIDInt, err := strconv.ParseInt(userID, 10, 64)
	if err != nil {
		return "", fmt.Errorf("用户ID格式错误: %w", err)
	}

	// 调用AuthorDescService获取创作者信息
	authorDetails := author.DefaultAuthorDescService.BatchGetAuthorDetail(ctx, []int64{userIDInt})

	// 检查是否获取到用户信息
	userInfo, ok := authorDetails[userIDInt]
	if !ok {
		return "", errors.New("未找到用户信息")
	}

	// 构建JSON响应
	response := map[string]interface{}{
		"id":             userIDInt,
		"name":           userInfo.AuthorName,
		"description":    userInfo.Description,
		"headline":       userInfo.Headline,
		"follower_count": userInfo.FollowerCnt,
		"answer_count":   userInfo.AnswerCnt,
		"article_count":  userInfo.ArticleCnt,
	}

	// 将map转换为JSON字符串
	jsonData, err := json.Marshal(response)
	if err != nil {
		return "", fmt.Errorf("JSON序列化失败: %w", err)
	}

	return string(jsonData), nil
}

func greetingPrompt() (mcp.Prompt, server.PromptHandlerFunc) {
	prompt := mcp.NewPrompt("greeting",
		mcp.WithPromptDescription("A friendly greeting prompt"),
		mcp.WithArgument("name",
			mcp.ArgumentDescription("Name of the person to greet"),
		),
	)

	return prompt, greetingPromptHandler
}

func greetingPromptHandler(ctx context.Context, request mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
	sseServer := server.ServerFromContext(ctx)

	name, ok := request.Params.Arguments["name"]
	if !ok {
		return nil, errors.New("name must be provided")
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/greetingPromptHandler", map[string]any{
			"name": name,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return mcp.NewGetPromptResult(
		"A friendly greeting",
		[]mcp.PromptMessage{
			mcp.NewPromptMessage(
				mcp.RoleAssistant,
				mcp.NewTextContent(fmt.Sprintf("Hello, %s! How can I help you today?", name)),
			),
		},
	), nil
}

func profilePrompt() (mcp.Prompt, server.PromptHandlerFunc) {
	prompt := mcp.NewPrompt("user_profile",
		mcp.WithPromptDescription("User profile assistance"),
		mcp.WithArgument("user_id",
			mcp.ArgumentDescription("User ID to get profile"),
			mcp.RequiredArgument(),
		))

	return prompt, profilePromptHandler
}

func profilePromptHandler(ctx context.Context, request mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
	sseServer := server.ServerFromContext(ctx)

	userID := request.Params.Arguments["user_id"]
	if userID == "" {
		return nil, fmt.Errorf("user_id is required")
	}

	if sseServer != nil {
		sseServer.SendNotificationToClient(ctx, "AispDebug/profilePromptHandler", map[string]any{
			"userID": userID,
		})
		log.Info(ctx, "send notification to client")
	} else {
		log.Error(ctx, "sseServer is nil")
	}

	return mcp.NewGetPromptResult(
		"User profile assistance",
		[]mcp.PromptMessage{
			mcp.NewPromptMessage(
				mcp.RoleUser,
				mcp.NewTextContent(fmt.Sprintf("Please provide the user profile for user ID: %s", userID)),
			),
			mcp.NewPromptMessage(
				mcp.RoleAssistant,
				mcp.NewEmbeddedResource(mcp.TextResourceContents{
					URI:      fmt.Sprintf("users://%s/profile", userID),
					MIMEType: "application/json",
				}),
			),
		},
	), nil
}
