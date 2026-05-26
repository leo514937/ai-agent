package util

import (
	"regexp"
)

var CiteRegexp = regexp.MustCompile(`<cite[^>]*>.*?</cite>`)
var PageRegexp = regexp.MustCompile(`<page>\d+</page>`)
var ThinkRegexp = regexp.MustCompile(`<zhithink>[\s\S]*</zhithink>`)

func RemoveTags(s string) string {
	s = PageRegexp.ReplaceAllString(s, "")
	s = CiteRegexp.ReplaceAllString(s, "")
	s = ThinkRegexp.ReplaceAllString(s, "")

	return s
}
