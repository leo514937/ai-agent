package util

import (
	"strconv"
	"strings"

	"github.com/getsentry/raven-go"
)

// 异常信息打印，同时会将 raven.Exception 中的堆栈信息也一起打印出来。
func ExceptionToString(ex *raven.Exception) string {
	if ex == nil {
		return ""
	}

	var msg = make([]string, 0, 20) // 预申请了一点空间
	msg = append(msg, ex.Value)
	if stackTrace := ex.Stacktrace; stackTrace != nil {
		for _, frame := range stackTrace.Frames {
			msg = append(msg,
				"File \""+frame.Filename+"\", line "+strconv.Itoa(frame.Lineno)+", in "+frame.Function,
				"\t"+strings.Trim(frame.ContextLine, "\t"))
		}
	}

	return strings.Join(msg, "\n")
}
