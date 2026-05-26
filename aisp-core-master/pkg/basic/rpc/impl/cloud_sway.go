package impl

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

type CloudSwayClientImpl struct {
	rpc.CloudSwayClientRPC
	httpClient *util.HttpClient
	endpoint   rpc.CloudSwayEndpoint
}

func NewCloudSwayClientHttp(endpoint rpc.CloudSwayEndpoint) rpc.CloudSwayClientRPC {
	return &CloudSwayClientImpl{
		httpClient: util.NewHttpClient(http.MethodGet, string(endpoint), 3000*time.Millisecond),
		endpoint:   endpoint,
	}
}

type cloudSwayAnswerRaw struct {
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
			Content          string    `json:"content"`
			MainText         string    `json:"mainText"`
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

func (c *CloudSwayClientImpl) Search(ctx context.Context, q string, topK int32, extParams map[string]string) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"type":     "CloudSwaySearch",
		"endpoint": string(c.endpoint),
	})

	cloudSwayAnswer := &cloudSwayAnswerRaw{}
	begin := time.Now()
	body := map[string]string{
		"q":        q,
		"mkt":      "zh-CN",
		"mainText": "true",
		"count":    cast.ToString(topK),
	}

	// 网宿接口支持 site 参数
	if site, isSiteExist := util.GetSiteDomain(q); isSiteExist {
		body["site"] = site
		body["q"] = util.RemoveSiteDomain(q)
	}

	if len(extParams) > 0 {
		for k, v := range extParams {
			body[k] = v
		}
	}
	client := c.httpClient

	err := client.Do(ctx, map[string]string{
		"Authorization": fmt.Sprintf("Bearer %s", config.GetString(macro.CloudSwayTokenConfigName, "")),
	}, body, nil, cloudSwayAnswer)

	elapsedTime := time.Since(begin).Milliseconds()
	if elapsedTime > 1500 {
		logger.Infof(ctx, "elapsedTime: %d", elapsedTime)
	}

	if err != nil {
		logger.Warnf(ctx, "failed: %v", err)
		return nil, err
	}

	res := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for _, result := range cloudSwayAnswer.WebPages.Value {
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
			MainText:      result.MainText,
			PublishedTime: publishTime,
		})
	}
	return res, nil
}
