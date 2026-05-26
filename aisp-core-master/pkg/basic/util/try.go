package util

import (
	"fmt"
	"runtime/debug"
)

func Try1[R1 any](f func() (R1, error)) (r R1, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v, stack: %s", r, debug.Stack())
		}
	}()
	return f()
}

func Try2[R1, R2 any](f func() (R1, R2, error)) (r1 R1, r2 R2, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v, stack: %s", r, debug.Stack())
		}
	}()
	return f()
}
