package util

import "git.in.zhihu.com/go/utils"

var nowFunc = utils.NowFunc

func ResetNowFunc() {
	utils.NowFunc = nowFunc
}

func Config[O any](obj O, f func(O)) O {
	if f != nil {
		f(obj)
	}
	return obj
}
