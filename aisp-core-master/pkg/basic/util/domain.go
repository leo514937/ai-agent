package util

import (
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"golang.org/x/net/publicsuffix"
)

// URLDomainInfo 包含从URL中提取的域名信息
type URLDomainInfo struct {
	FullDomain string // 完整域名，如 www.example.com
	RootDomain string // 一级域名，如 example.com
}

// ExtractDomainInfo 从URL中提取完整域名和一级域名
// 参数 rawURL 可以是带协议的完整URL，也可以是纯域名
// 返回包含域名信息的结构体和可能的错误
func ExtractDomainInfo(rawURL string) (*URLDomainInfo, error) {
	// 预处理URL
	if rawURL == "" {
		return nil, errors.New("the url cannot be empty")
	}

	// 确保URL有协议前缀
	processedURL := rawURL
	if !strings.HasPrefix(processedURL, "http://") && !strings.HasPrefix(processedURL, "https://") {
		processedURL = "https://" + processedURL
	}

	// 解析URL
	parsedURL, err := url.Parse(processedURL)
	if err != nil {
		return nil, fmt.Errorf("failed to parse the url:%s, err:%w", processedURL, err)
	}

	// 获取完整域名
	fullDomain := parsedURL.Hostname()
	if fullDomain == "" {
		return nil, fmt.Errorf("the domain name cannot be obtained, url:%s", processedURL)
	}

	// 获取一级域名（根域名）
	rootDomain, err := publicsuffix.EffectiveTLDPlusOne(fullDomain)
	if err != nil {
		// 部分特殊情况(如localhost或IP地址)可能导致错误
		// 此时将完整域名也作为根域名返回
		return &URLDomainInfo{
			FullDomain: fullDomain,
			RootDomain: fullDomain,
		}, fmt.Errorf("failed to obtain the first-level domain name. The full domain name will be used., url:%s, err:%w", processedURL, err)
	}
	return &URLDomainInfo{
		FullDomain: fullDomain,
		RootDomain: rootDomain,
	}, nil
}

// 正则匹配 site: 后接域名
var siteRe = regexp.MustCompile(`site:([\w.-]+)`)

func GetSiteDomain(query string) (string, bool) {
	matches := siteRe.FindStringSubmatch(query)
	if len(matches) > 1 {
		return matches[1], true
	}
	return "", false
}

func RemoveSiteDomain(query string) string {
	return siteRe.ReplaceAllString(query, "")
}
