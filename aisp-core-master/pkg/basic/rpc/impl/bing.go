package impl

import (
	"context"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

type BingClientImpl struct {
	httpClient      *util.HttpClient
	httpProxyClient *util.HttpClient
}

var DefaultBingClient rpc.BingClientRPC

const (
	bingEndpoint string = "https://api.bing.microsoft.com/v7.0/search"
)

func init() {
	DefaultBingClient = NewBingClientHttp()
}

func NewBingClientHttp() rpc.BingClientRPC {
	return &BingClientImpl{
		httpProxyClient: util.NewHttpClientWithProxy(http.MethodGet, bingEndpoint, 3000*time.Millisecond),
		httpClient:      util.NewHttpClient(http.MethodGet, bingEndpoint, 3000*time.Millisecond),
	}
}

type bingAnswerRaw struct {
	Type         string `json:"_type"`
	QueryContext struct {
		OriginalQuery string `json:"originalQuery"`
	} `json:"queryContext"`
	WebPages struct {
		WebSearchURL          string `json:"webSearchUrl"`
		TotalEstimatedMatches int    `json:"totalEstimatedMatches"`
		Value                 []struct {
			ID               string    `json:"id"`
			Name             string    `json:"name"`
			URL              string    `json:"url"`
			IsFamilyFriendly bool      `json:"isFamilyFriendly"`
			DisplayURL       string    `json:"displayUrl"`
			Snippet          string    `json:"snippet"`
			DatePublished    string    `json:"datePublished"`
			DateLastCrawled  time.Time `json:"dateLastCrawled"`
			SearchTags       []struct {
				Name    string `json:"name"`
				Content string `json:"content"`
			} `json:"searchTags,omitempty"`
			About []struct {
				Name string `json:"name"`
			} `json:"about,omitempty"`
		} `json:"value"`
	} `json:"webPages"`
	RelatedSearches struct {
		ID    string `json:"id"`
		Value []struct {
			Text         string `json:"text"`
			DisplayText  string `json:"displayText"`
			WebSearchURL string `json:"webSearchUrl"`
		} `json:"value"`
	} `json:"relatedSearches"`
	RankingResponse struct {
		Mainline struct {
			Items []struct {
				AnswerType  string `json:"answerType"`
				ResultIndex int    `json:"resultIndex"`
				Value       struct {
					ID string `json:"id"`
				} `json:"value"`
			} `json:"items"`
		} `json:"mainline"`
		Sidebar struct {
			Items []struct {
				AnswerType string `json:"answerType"`
				Value      struct {
					ID string `json:"id"`
				} `json:"value"`
			} `json:"items"`
		} `json:"sidebar"`
	} `json:"rankingResponse"`
}

func (c *BingClientImpl) BingSearch(ctx context.Context, q string, topK int32, extParams map[string]string) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "BingSearch", q)

	bingAnswer := &bingAnswerRaw{}
	begin := time.Now()
	body := map[string]string{
		"q":     q,
		"mkt":   "zh-CN",
		"count": cast.ToString(topK),
	}
	if len(extParams) > 0 {
		for k, v := range extParams {
			body[k] = v
		}
	}
	client := c.httpClient
	if config.GetBool(macro.BingUseProxy, false) {
		client = c.httpProxyClient
	}

	err := client.Do(ctx, map[string]string{
		"Ocp-Apim-Subscription-Key": config.GetString(macro.BingTokenConfigName, ""),
	}, body, nil, bingAnswer)

	elapsedTime := time.Since(begin).Milliseconds()
	if elapsedTime > 1500 {
		logger.Infof(ctx, "BingSearch elapsedTime: %d", elapsedTime)
	}

	// 非代理模式下，如果请求失败，切换到代理模式再次请求
	if err != nil && client == c.httpClient {
		logger.Warnf(ctx, "BingSearch failed: %v, retry with proxy", err)
		err = c.httpProxyClient.Do(ctx, map[string]string{
			"Ocp-Apim-Subscription-Key": config.GetString(macro.BingTokenConfigName, ""),
		}, body, nil, bingAnswer)
	}

	if err != nil {
		logger.Warnf(ctx, "BingSearch failed: %v", err)
		return nil, err
	}

	res := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for _, result := range bingAnswer.WebPages.Value {
		publishTime := result.DateLastCrawled.Unix()
		if result.DatePublished != "" {
			published, err := util.Utc2Time(result.DatePublished)
			if err == nil {
				publishTime = published.Unix()
			}
		}
		res = append(res, &rpc.OutSiteSearchRecallAnswerResult{
			Name:          result.Name,
			Url:           result.URL,
			Snippet:       result.Snippet,
			PublishedTime: publishTime,
		})
	}
	return res, nil
}
