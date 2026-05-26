package model

import (
	"strings"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"github.com/PuerkitoBio/goquery"
)

type Image struct {
	ImgToken string                    `json:"img_token"` // 图片 token
	URL      string                    `json:"url"`       // 图片 URL
	PrevText string                    `json:"prev_text"` // 图片前面一段文字，到换行为止
	Caption  string                    `json:"caption"`   // 图片标题
	NextText string                    `json:"next_text"` // 图片后面一段文字，到换行为止
	TagInfo  map[string]*tag_core.Tags `json:"tag_info"`  // 内容的打标信息
}

func ParseImageInfos(content string) []*Image {
	var result []*Image

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(content))
	if err != nil || doc == nil {
		return result
	}

	doc.Find("figure").Each(func(i int, s *goquery.Selection) {
		img := s.Find("img")
		imgURL, _ := img.Attr("src")
		imgToken, _ := img.Attr("data-original-token")

		figcaption := s.Find("figcaption")
		caption := figcaption.Text()

		prevText := findTextParagraph(s, "previous")
		nextText := findTextParagraph(s, "next")

		if imgToken != "" {
			result = append(result, &Image{
				ImgToken: imgToken,
				URL:      imgURL,
				PrevText: prevText,
				Caption:  caption,
				NextText: nextText,
			})
		}
	})

	return result
}

func findTextParagraph(s *goquery.Selection, direction string) string {
	var paragraph *goquery.Selection
	if direction == "previous" {
		paragraph = s.Prev()
	} else {
		paragraph = s.Next()
	}

	// 如果图片前/后的段落为空，那么继续向前/后找，最远寻找 2 个段落，防止距离太远图文不匹配
	cnt := 1
	for paragraph.Text() == "" && cnt <= 2 {
		if direction == "previous" {
			paragraph = paragraph.Prev()
		} else {
			paragraph = paragraph.Next()
		}
		cnt++
	}

	return paragraph.Text()
}
