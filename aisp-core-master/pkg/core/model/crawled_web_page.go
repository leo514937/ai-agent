package model

import "time"

type CrawledWebPage struct {
	Id          int64  `borm:"primary_key"`
	PDate       string `borm:"column:p_date" json:"p_date"`
	QueryMerge  string
	MemberId    int64
	Scene       string
	PublishTime int64
	Url         string
	UrlHash     int64
	RawContent  string ` borm:"-"`
	Content     string
	Title       string
	CrawlAt     *time.Time
}
