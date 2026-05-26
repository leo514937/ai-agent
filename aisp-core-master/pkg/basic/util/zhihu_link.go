package util

import (
	"net/url"
	"regexp"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
)

type LinkParseHostPattern struct {
	Hosts    *utils.Set
	Patterns []LinkParseURLPatten
}

type LinkParseURLPatten struct {
	Re      *regexp.Regexp
	Type    LinkType
	SubType string
}

type LinkType string

func (l LinkType) String() string {
	return string(l)
}

const (
	LinkTypeZhihu   LinkType = "ZHIHU"
	LinkTypeUnknown LinkType = "UNKNOWN"
)

var InSiteLinkParsePatterns = []LinkParseHostPattern{
	{
		Hosts: utils.NewSet("zhuanlan.zhihu.com"),
		Patterns: []LinkParseURLPatten{
			{Re: regexp.MustCompile(`^/p/(?P<token>\d+)`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeArticle},
			{Re: regexp.MustCompile(`^/(?P<token>[\w-]*)$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeColumn},
		},
	},
	{
		Hosts: utils.NewSet("www.zhihu.com", "zhihu.com"),
		Patterns: []LinkParseURLPatten{
			{Re: regexp.MustCompile(`^/question/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeQuestion},
			{Re: regexp.MustCompile(`^/question/\d+/answer/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeAnswer},
			{Re: regexp.MustCompile(`^/answer/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeAnswer},
			{Re: regexp.MustCompile(`^/collection/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeFavlist},
			{Re: regexp.MustCompile(`^/publications/(nacl|weekly|hour|book)/(?P<token>\d+)$`), Type: LinkTypeZhihu, SubType: "ebook"},
			{Re: regexp.MustCompile(`^/roundtable/(?P<token>[\w-]+)$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeRoundtable},
			{Re: regexp.MustCompile(`^/topic/(?P<token>\d+)(/hot)?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeTopic},
			{Re: regexp.MustCompile(`^/pin/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypePin},
			{Re: regexp.MustCompile(`^/zvideo/(?P<token>\d+)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeZVideo},
			{Re: regexp.MustCompile(`^/column/(?P<token>[\w-]*)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeColumn},
			{Re: regexp.MustCompile(`^/tardis/sogou/art/(?P<token>[\w-]*)/?$`), Type: LinkTypeZhihu, SubType: content_core_thrift.ContentTypeArticle},
		},
	},
}

var commentRe = regexp.MustCompile(`zhihu://[\w/]+/comment/(?P<token>\d+)`)

func regexpNamedMatch(re *regexp.Regexp, text string) (map[string]string, bool) {
	matches := re.FindStringSubmatch(text)
	result := make(map[string]string)
	for i, name := range re.SubexpNames() {
		if i != 0 && name != "" && len(matches) >= i {
			result[name] = matches[i]
		}
	}
	return result, len(matches) > 0
}

func ParseLinkInfo(link string) (linkType LinkType, subType string, token string) {
	up, _ := url.Parse(link)
	/// 无法解析返回默认值
	if up == nil {
		return LinkTypeUnknown, "other", ""
	}
	// 评论是特殊的，它没有web url，只有应用程序通用链接
	if up.Scheme == "zhihu" {
		matchMap, hasMatch := regexpNamedMatch(commentRe, link)
		if hasMatch {
			return LinkTypeZhihu, "comment", matchMap["token"]
		}
	}
	if up.Scheme == "" {
		link = "http://" + link
	}
	up, _ = url.Parse(link)
	for _, hostPattern := range InSiteLinkParsePatterns {
		if up == nil {
			continue
		}
		if !hostPattern.Hosts.Exists(up.Host) {
			continue
		}
		for _, urlPattern := range hostPattern.Patterns {
			matchMap, hasMatch := regexpNamedMatch(urlPattern.Re, up.Path)
			if hasMatch {
				return urlPattern.Type, urlPattern.SubType, matchMap["token"]
			}
		}
	}
	return LinkTypeUnknown, "UNKNOWN", ""
}
