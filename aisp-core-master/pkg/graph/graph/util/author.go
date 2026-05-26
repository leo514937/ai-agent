package util

import (
	"regexp"
	"strings"
	"unicode/utf8"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/spf13/cast"
)

func GetStarAuthorIdNames() map[int64]string {
	result := map[int64]string{}

	zhidaStarAuthors := config.MustGetString(macro.ZhidaStarAuthorsConfigName)
	authorInfos := strings.Split(zhidaStarAuthors, ";")

	for _, authorInfo := range authorInfos {
		authorInfoArr := strings.Split(authorInfo, ",")
		if len(authorInfoArr) != 2 {
			continue
		}
		authorId, err := util.String2Int64(authorInfoArr[0])
		if err != nil {
			continue
		}
		result[authorId] = authorInfoArr[1]
	}

	return result
}

func BatchGetRumForwardKey(ids []int64) []string {
	var keys []string
	for _, id := range ids {
		idStr := cast.ToString(id)
		key := "1" + strings.Repeat("0", 13-utf8.RuneCountInString(idStr)) + idStr + "0001"
		keys = append(keys, key)
	}

	return keys
}

var queryAuthorRegex = regexp.MustCompile(`@[^ ]+ +的知乎创作 +`)

func CleanQueryAuthor(query string) string {
	// 匹配多个 "@用户名 的知乎创作" 模式，替换所有匹配到的模式为空字符串
	cleaned := queryAuthorRegex.ReplaceAllString(query, "")
	return strings.TrimSpace(cleaned)
}
