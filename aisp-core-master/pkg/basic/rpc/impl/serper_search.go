package impl

import (
	"context"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

const SerperUrl = "https://google.serper.dev/search"

type SerperClientImpl struct {
	httpClient *util.HttpClient
}

func NewSerperHttpClient() rpc.OutSiteSearchApi {
	return &SerperClientImpl{
		httpClient: util.NewHttpClient(http.MethodPost, SerperUrl, 3000*time.Millisecond),
	}
}

func (q *SerperClientImpl) Search(ctx context.Context, query string, topK int32) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "SerperSearch", query)

	var res = make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	begin := time.Now()
	var resp = &SerperSearchResponse{}
	var err error
	runFunc := func(ctx context.Context) error {
		errTmp := q.httpClient.Do(ctx, map[string]string{
			"X-API-KEY":    config.GetString(macro.SerperTokenConfigName, ""),
			"Content-Type": "application/json",
		}, map[string]string{
			"q":        query,
			"location": "China",
			"gl":       "cn",
			"hl":       "zh-cn",
		}, nil, resp)

		if err != nil {
			err = errTmp
			return err
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	elapsedTime := time.Since(begin).Milliseconds()
	if elapsedTime > 1500 {
		logger.Infof(ctx, "elapsedTime: %d", elapsedTime)
	}
	if err != nil {
		logger.Warnf(ctx, "failed: %v", err)
		return res, err
	}

	for _, item := range resp.Organic {
		// 时间格式比较特殊
		publishedTime, publishedTimeErr := util.StringDate2TimeByFmt(item.Date, "2006年1月2日")
		publishedTimeUnix := publishedTime.Unix()
		if publishedTimeErr != nil {
			publishedTimeUnix = 0
		}
		res = append(res, &rpc.OutSiteSearchRecallAnswerResult{
			Name:          item.Title,
			Url:           item.Link,
			Snippet:       item.Snippet,
			PublishedTime: publishedTimeUnix,
		})
	}

	// 由于Serper搜索暂时还不能指定召回数量 所以这里先暂时做后limit限制
	return res[:zrecUtil.Min(int(topK), len(res))], nil
}

type SerperSearchResponse struct {
	SearchParameters struct {
		Q        string `json:"q"`
		GL       string `json:"gl"`
		HL       string `json:"hl"`
		Type     string `json:"type"`
		Location string `json:"location"`
		Engine   string `json:"engine"`
	} `json:"searchParameters"`
	KnowledgeGraph struct {
		Title      string            `json:"title"`
		Type       string            `json:"type"`
		ImageUrl   string            `json:"imageUrl"`
		Attributes map[string]string `json:"attributes"`
	} `json:"knowledgeGraph"`
	AnswerBox struct {
		Snippet            string   `json:"snippet"`
		SnippetHighlighted []string `json:"snippetHighlighted"`
		Title              string   `json:"title"`
		Link               string   `json:"link"`
		Date               string   `json:"date"`
	} `json:"answerBox"`
	Organic []struct {
		Title    string `json:"title"`
		Link     string `json:"link"`
		Snippet  string `json:"snippet"`
		Position int    `json:"position"`
		Date     string `json:"date"`
	} `json:"organic"`
	PeopleAlsoAsk []struct {
		Question string `json:"question"`
		Snippet  string `json:"snippet"`
		Title    string `json:"title"`
		Link     string `json:"link"`
	} `json:"peopleAlsoAsk"`
	RelatedSearches []struct {
		Query string `json:"query"`
	} `json:"relatedSearches"`
	Credits int `json:"credits"`
}
