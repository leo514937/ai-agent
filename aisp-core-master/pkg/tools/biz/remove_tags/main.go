package main

import (
	"fmt"
	"regexp"
)

func main() {
	/*
			text := `
		以下是测试文本 <cite>1</cite><cite>2</cite><cite>3</cite>
		其中这里有部分原始角标 <cite>1</cite><cite>2</cite><cite>3</cite>
		其中这里有部分V2角标 <cite>1001</cite><cite>1002</cite><cite>1003</cite>
		其中这里有部分V2新版角标 <cite data-index='1001'>1001</cite><cite data-index='1002'>1002</cite><cite data-index='1003'>1003</cite>
		其中这里有部分数字角标 <cite data-index='1001' data-type='digital'>1001</cite><cite data-index='1002' data-type='digital'>1002</cite><cite data-index='1003' data-type='digital'>1003</cite>
		}`
			text = util.RemoveTags(text)
			fmt.Println(text)
	*/
	ThinkProductPat := regexp.MustCompile(`<$|<\s*$|<p[^>]*$|<pr[^>]*$|<pro[^>]*$|<prod[^>]*$|<produ[^>]*$|<product[^>]*$|</p[^>]*$|</pr[^>]*$|</pro[^>]*$|</prod[^>]*$|</produ[^>]*$|</product[^>]*$`)
	text := `<`
	fmt.Println(ThinkProductPat.MatchString(text))
	text1 := `<product>`
	fmt.Println(ThinkProductPat.MatchString(text1))
	text2 := `<pro`
	fmt.Println(ThinkProductPat.MatchString(text2))
	text3 := `</product>`
	fmt.Println(ThinkProductPat.MatchString(text3))
	text4 := `<product>1</product>2</product>3</product>4</product>`
	fmt.Println(ThinkProductPat.MatchString(text4))
}
