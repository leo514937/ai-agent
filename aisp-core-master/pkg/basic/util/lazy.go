package util

import "sync"

func Make(f func() interface{}) func() interface{} {
	var v interface{}
	var once sync.Once
	return func() interface{} {
		once.Do(func() {
			v = f()
			f = nil
		})
		return v
	}
}
