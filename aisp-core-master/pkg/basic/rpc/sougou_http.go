package rpc

import (
	"context"
	"encoding/json"
)

type SougouClientHttp interface {
	SougouSearch(ctx context.Context, q string, topK int32) ([]*OutSiteSearchRecallAnswerResult, error)
}

// SougouAnswerRaw 搜狗Raw 结构体
type SougouAnswerRaw struct {
	Response struct {
		RequestId string `json:"RequestId"`
		Pages     []struct {
			Display    string `json:"Display"` // This is a JSON string. To parse it, you would need to define another struct that matches its structure and unmarshal it separately.
			JsonData   string `json:"JsonData"`
			TplId      string `json:"TplId"`
			ClassifyId string `json:"ClassifyId"`
		} `json:"Pages"`
	} `json:"Response"`
}

type DisplayInfo struct {
	ContentTitle                string `json:"ContentTitle"`
	FullTitle                   string `json:"FullTitle"`
	RedContentTitle             string `json:"RedContentTitle"`
	VideoDetected               string `json:"VideoDetected"`
	AbstractInfo                string `json:"abstract_info"`
	CiteUrl                     string `json:"citeUrl"`
	Content                     string `json:"content"`
	ContentScore                string `json:"content_score"`
	Date                        string `json:"date"`
	HasMoreWebSite              string `json:"hasmorewebsinsite"`
	HqTitle                     string `json:"hq_title"`
	ImageFrom                   string `json:"image_from"`
	ImageContent                string `json:"imagecontent"`
	ImageNumDb                  string `json:"imagenum_db"`
	ImageURL                    string `json:"imageurl"`
	NewsExpand                  string `json:"news_expand"`
	PageSize                    string `json:"pagesize"`
	ShowURL                     string `json:"showurl"`
	SmartSummaryParaAnnoContent string `json:"smart_summary_para_anno_content"`
	SmartSummaryParaAnnoTitle   string `json:"smart_summary_para_anno_title"`
	Title                       string `json:"title"`
	TitleRevised                string `json:"title_revised"`
	URL                         string `json:"url"`
	WapFriendly                 string `json:"wap_friendly"`
}

func (s *SougouAnswerRaw) ParseDisplayInfo() ([]*DisplayInfo, error) {
	displayInfos := make([]*DisplayInfo, 0)
	if len(s.Response.Pages) == 0 {
		return displayInfos, nil
	}

	for _, page := range s.Response.Pages {
		di := new(DisplayInfo)
		err := json.Unmarshal([]byte(page.Display), di)
		if err != nil {
			return displayInfos, err
		}
		displayInfos = append(displayInfos, di)
	}
	return displayInfos, nil
}
