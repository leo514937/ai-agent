package impl

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

const (
	tavilySearchURL = "https://api.tavily.com/search"
	tavilyApiKey    = "tavily_api_key"
)

type TavilySearchClient struct {
	client  *util.HttpClient
	baseURL string
}

func NewTavilySearchClient() *TavilySearchClient {
	return &TavilySearchClient{
		client: util.NewHttpClient(http.MethodPost, tavilySearchURL, 3000*time.Millisecond),

		baseURL: tavilySearchURL,
	}
}

func (c *TavilySearchClient) Search(ctx context.Context, query string, topK int32) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	if query == "" {
		return nil, fmt.Errorf("query cannot be empty")
	}

	var searchResp SearchResult
	err := c.client.Do(ctx, map[string]string{
		"Content-Type":  "application/json",
		"Authorization": "Bearer " + config.GetString(tavilyApiKey, ""),
	}, map[string]string{
		"query": query,
	}, nil, &searchResp)

	if err != nil {
		return nil, fmt.Errorf("error making request: %v", err)
	}

	results := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for i, r := range searchResp.Results {
		if int32(i) >= topK {
			break
		}
		results = append(results, &rpc.OutSiteSearchRecallAnswerResult{
			Name:    r.Title,
			Snippet: r.Content,
			Url:     r.URL,
		})
	}

	return results, nil
}

// SearchResult represents the complete search result structure
type SearchResult struct {
	Query             string        `json:"query"`
	FollowUpQuestions []string      `json:"follow_up_questions"`
	Answer            string        `json:"answer"`
	Images            []string      `json:"images"`
	Results           []*SearchItem `json:"results"`
	ResponseTime      float64       `json:"response_time"`
}

// SearchItem represents an individual search result item
type SearchItem struct {
	Title      string  `json:"title"`
	URL        string  `json:"url"`
	Content    string  `json:"content"`
	Score      float64 `json:"score"`
	RawContent string  `json:"raw_content"`
}
