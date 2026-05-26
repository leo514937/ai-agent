package impl

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

const (
	braveSearchURL = "https://api.search.brave.com/res/v1/web/search"
	braveApiKey    = "brave_api_key"
)

type BraveSearchClient struct {
	client  *util.HttpClient
	apiKey  string
	baseURL string
}

func NewBraveSearchClient() *BraveSearchClient {
	return &BraveSearchClient{
		client:  util.NewHttpClientWithProxy(http.MethodGet, braveSearchURL, 3000*time.Millisecond),
		baseURL: braveSearchURL,
	}
}

func (c *BraveSearchClient) Search(ctx context.Context, query string, topK int32) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	if query == "" {
		return nil, fmt.Errorf("query cannot be empty")
	}

	var searchResp BraveSearchResponse
	err := c.client.Do(ctx, map[string]string{
		"Accept":               "application/json",
		"X-Subscription-Token": config.GetString(braveApiKey, ""),
	}, map[string]string{
		"q":           url.QueryEscape(query),
		"country":     "CN",
		"search_lang": "zh-hans",
	}, nil, &searchResp)

	if err != nil {
		return nil, fmt.Errorf("error making request: %v", err)
	}

	results := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for i, r := range searchResp.Web.Results {
		if int32(i) >= topK {
			break
		}

		parsedTime, err := time.ParseInLocation("2006-01-02T15:04:05", r.PageAge, time.Local)
		if err != nil {
			fmt.Println("Error parsing time:", err)
		}

		results = append(results, &rpc.OutSiteSearchRecallAnswerResult{
			Name:          r.Title,
			Snippet:       r.Description,
			Url:           r.URL,
			PublishedTime: parsedTime.Unix(),
		})
	}

	return results, nil
}

// BraveSearchResponse represents the top-level response structure
type BraveSearchResponse struct {
	Query Query  `json:"query"`
	Mixed Mixed  `json:"mixed"`
	Type  string `json:"type"`
	Web   Web    `json:"web"`
}

// Query represents the query parameters
type Query struct {
	Original             string `json:"original"`
	ShowStrictWarning    bool   `json:"show_strict_warning"`
	IsNavigational       bool   `json:"is_navigational"`
	IsNewsBreaking       bool   `json:"is_news_breaking"`
	SpellcheckOff        bool   `json:"spellcheck_off"`
	Country              string `json:"country"`
	BadResults           bool   `json:"bad_results"`
	ShouldFallback       bool   `json:"should_fallback"`
	PostalCode           string `json:"postal_code"`
	City                 string `json:"city"`
	HeaderCountry        string `json:"header_country"`
	MoreResultsAvailable bool   `json:"more_results_available"`
	State                string `json:"state"`
}

// Mixed represents the mixed results structure
type Mixed struct {
	Type string        `json:"type"`
	Main []MainItem    `json:"main"`
	Top  []interface{} `json:"top"`
	Side []interface{} `json:"side"`
}

// MainItem represents an item in the main results array
type MainItem struct {
	Type  string `json:"type"`
	Index int    `json:"index"`
	All   bool   `json:"all"`
}

// Web represents the web search results
type Web struct {
	Type           string   `json:"type"`
	Results        []Result `json:"results"`
	FamilyFriendly bool     `json:"family_friendly"`
}

// Result represents a single search result
type Result struct {
	Title          string        `json:"title"`
	URL            string        `json:"url"`
	IsSourceLocal  bool          `json:"is_source_local"`
	IsSourceBoth   bool          `json:"is_source_both"`
	Description    string        `json:"description"`
	PageAge        string        `json:"page_age,omitempty"`
	Profile        Profile       `json:"profile"`
	Language       string        `json:"language"`
	FamilyFriendly bool          `json:"family_friendly"`
	Type           string        `json:"type"`
	Subtype        string        `json:"subtype"`
	IsLive         bool          `json:"is_live"`
	MetaURL        MetaURL       `json:"meta_url"`
	Age            string        `json:"age,omitempty"`
	Thumbnail      *Thumbnail    `json:"thumbnail,omitempty"`
	Location       *Location     `json:"location,omitempty"`
	Organization   *Organization `json:"organization,omitempty"`
}

// Profile represents the profile information
type Profile struct {
	Name     string `json:"name"`
	URL      string `json:"url"`
	LongName string `json:"long_name"`
	Img      string `json:"img"`
}

// MetaURL represents the meta URL information
type MetaURL struct {
	Scheme   string `json:"scheme"`
	Netloc   string `json:"netloc"`
	Hostname string `json:"hostname"`
	Favicon  string `json:"favicon"`
	Path     string `json:"path"`
}

// Thumbnail represents thumbnail information
type Thumbnail struct {
	Src      string `json:"src"`
	Original string `json:"original"`
	Logo     bool   `json:"logo"`
}

// Location represents location information
type Location struct {
	Title          string        `json:"title"`
	URL            string        `json:"url"`
	IsSourceLocal  bool          `json:"is_source_local"`
	IsSourceBoth   bool          `json:"is_source_both"`
	Description    string        `json:"description"`
	FamilyFriendly bool          `json:"family_friendly"`
	Type           string        `json:"type"`
	ProviderURL    string        `json:"provider_url"`
	Coordinates    []float64     `json:"coordinates"`
	ZoomLevel      int           `json:"zoom_level"`
	Thumbnail      Thumbnail     `json:"thumbnail"`
	PostalAddress  PostalAddress `json:"postal_address"`
	Profiles       []Profile     `json:"profiles"`
	Pictures       Pictures      `json:"pictures"`
	Categories     []interface{} `json:"categories"`
}

// PostalAddress represents postal address information
type PostalAddress struct {
	Type            string `json:"type"`
	PostalCode      string `json:"postalCode"`
	AddressRegion   string `json:"addressRegion"`
	AddressLocality string `json:"addressLocality"`
	DisplayAddress  string `json:"displayAddress"`
	Country         string `json:"country,omitempty"`
}

// Pictures represents pictures information
type Pictures struct {
	Results []PictureResult `json:"results"`
}

// PictureResult represents a single picture result
type PictureResult struct {
	Src      string `json:"src"`
	Original string `json:"original"`
}

// Organization represents organization information
type Organization struct {
	Type          string        `json:"type"`
	Name          string        `json:"name"`
	ContactPoints []interface{} `json:"contact_points"`
}
