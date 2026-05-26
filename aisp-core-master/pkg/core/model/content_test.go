package model

import (
	"testing"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"github.com/stretchr/testify/assert"
)

func TestContent(t *testing.T) {
	content1 := NewContentWithDocType(1001, content.DocType_Answer)
	content2 := NewContentWithDocType(1002, content.DocType_Unknown)
	content3 := NewContentWithContentType(1003, "ANSWER")
	content4 := NewContentWithContentType(1004, "answer")
	content5 := NewContentWithToken("1005", "ANSWER")
	assert.Equal(t, "ANSWER", content1.GetContentType())
	assert.Equal(t, "", content2.GetContentType())
	assert.Equal(t, content.DocType_Answer, content3.GetDocType())
	assert.Equal(t, content.DocType_Unknown, content4.GetDocType())
	assert.Equal(t, content.DocType_Answer, content5.GetDocType())
	assert.Equal(t, 1005, content5.ContentID)
}
