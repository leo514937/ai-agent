package util

import (
	"testing"
)

func TestParseLinkInfo(t *testing.T) {
	linkType, subType, token := ParseLinkInfo("https://www.zhihu.com/answer/3412835570")
	t.Logf(linkType.String(), subType, token)

	linkType1, subType1, token1 := ParseLinkInfo("https://www.zhihu.com/question/599935979/answer/3412835570")
	t.Logf(linkType1.String(), subType1, token1)

	linkType2, subType2, token2 := ParseLinkInfo("https://zhuanlan.zhihu.com/p/403862960")
	t.Logf(linkType2.String(), subType2, token2)

	linkType3, subType3, token3 := ParseLinkInfo("https://www.zhihu.com/")
	t.Logf(linkType3.String(), subType3, token3)

	linkType4, subType4, token4 := ParseLinkInfo("https://www.zhihu.com/explore")
	t.Logf(linkType4.String(), subType4, token4)
}
