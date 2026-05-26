package main

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/ask_related_word"
)

func main() {
	_ = ask_related_word.RunReadHiveAndRefreshAskRelatedWord()
}
