package constants

import (
	"testing"
)

func TestFmt(t *testing.T) {
	// 获得随机问候
	t.Logf(GetRandomGreeting())

	// 格式化输出1
	str1, err1 := FmtStr(GreetingAnswerFmt, "张三")
	if err1 != nil {
		t.Error(err1)
	} else {
		t.Logf(str1)
	}

	// 格式化输出2
	str2, err2 := FmtStr(AuthorPromptFmt, "数码科技", "索尼相机", "A7C2 性价比如何？")
	if err2 != nil {
		t.Error(err2)
	} else {
		t.Logf(str2)
	}
}
