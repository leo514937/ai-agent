package util

import (
	"fmt"
	"regexp"
	"testing"
)

// 正则
var rUniqueIdRegexp1 = regexp.MustCompile(`"unique_id":"[123]_\d+"`)

func TestSuggestQueries(t *testing.T) {
	searchResults := `{"extra_fields": [{"unique_id": "1_123"}, {"unique_id": "2_456"}, {"unique_id": "3_789"}]}`
	findString := rUniqueIdRegexp1.FindString(searchResults)
	fmt.Println("测试数据 => ", findString)
	//t.Logf(findString)
}
