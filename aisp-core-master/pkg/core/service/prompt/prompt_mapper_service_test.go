package prompt

import (
	"context"
	"testing"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
)

func TestPrompt(t *testing.T) {

	content, err := DefaultPromptMapperService.FormatPromptById(context.Background(),
		macro.PromptQueryIntention, map[string]string{
			"Content": "你好啊小姐姐，请问你芳龄多大？",
		})
	if err != nil {
		t.Errorf("err: %v", err)
	}
	t.Log(content)
}
