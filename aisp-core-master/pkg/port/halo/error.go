package halo

import (
	"bytes"
	"context"
	"errors"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"sync"
)

var (
	bufferPool = &sync.Pool{
		New: func() interface{} {
			return new(bytes.Buffer)
		},
	}
)

type Error interface {
	Merge(context.Context)
	IsCanceled() bool
	Error() string
	Class() string
	Unwrap() error
	Frames() []runtime.Frame
}

func NewClassErr(class string) Error {
	return &wrapError{class: class, frames: GetFrames()}
}

func WrapErr(err error, class string) Error {
	if err == nil {
		return nil
	}
	if ec, ok := err.(Error); ok {
		return ec
	}
	return &wrapError{error: err, stack: false, class: class, frames: GetFrames()}
}

func WrapErrWithUnknownClass(err error) Error {
	if err == nil {
		return nil
	}
	if ec, ok := err.(Error); ok {
		return ec
	}
	return &wrapError{error: err, stack: false, class: errorClass(err), frames: GetFrames()}
}

func WrapErrWithStack(err error) Error {
	if err == nil {
		return nil
	}
	if ec, ok := err.(Error); ok {
		return ec
	}
	return &wrapError{error: err, stack: true, class: errorClass(err), frames: GetFrames()}
}

type wrapError struct {
	error
	stack  bool
	class  string
	frames []runtime.Frame
}

func (e *wrapError) Merge(ctx context.Context) {
	if errors.Is(ctx.Err(), context.Canceled) ||
		// 当服务端向已关闭的链接写入响应时报错其实和客户端主动关闭链接是一样的，可以忽略
		strings.Contains(e.Error(), "write: broken pipe") {
		e.class = "CtxCanceled"
	}
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		e.class = "CtxDeadlineExceeded"
	}
}

func (e *wrapError) IsCanceled() bool {
	return e.class == "CtxCanceled" || errors.Is(e.error, context.Canceled)
}

func (e *wrapError) Error() string {
	if e.error == nil {
		return e.class
	}

	if e.stack {
		buffer := bufferPool.Get().(*bytes.Buffer)
		defer bufferPool.Put(buffer)
		buffer.Reset()

		buffer.WriteString(e.error.Error())
		buffer.WriteString(", stack:\n")

		for _, fr := range e.frames {
			buffer.WriteRune('\t')
			buffer.WriteString(fr.File)
			buffer.WriteRune(':')
			buffer.WriteString(strconv.Itoa(fr.Line))
			buffer.WriteByte(' ')
			buffer.WriteString(fr.Function)
			buffer.WriteByte('\n')
		}
		return buffer.String()
	}

	return e.error.Error()
}

func (e *wrapError) Class() string {
	return e.class
}

func (e *wrapError) Unwrap() error {
	return e.error
}

func (e *wrapError) Frames() []runtime.Frame {
	return e.frames
}

type Causer interface {
	Cause() error
}

type Unwraper interface {
	Unwrap() error
}

var (
	errorsErrorType = reflect.TypeOf(errors.New("")).Elem()
)

const (
	maxErrorName = 32
)

func errorClass(err error) string {
	// unwrap pkg & std error
	// https://github.com/pkg/errors#retrieving-the-cause-of-an-error
	// https://blog.golang.org/go1.13-errors
	for err != nil {
		skip := true
		unwrap, ok := err.(Unwraper)
		if ok {
			skip = false
			err = unwrap.Unwrap()
		}
		cause, ok := err.(Causer)
		if ok {
			skip = false
			err = cause.Cause()
		}
		if skip {
			break
		}
	}

	errType := reflect.TypeOf(err)
	for errType.Kind() == reflect.Ptr {
		errType = errType.Elem()
	}

	switch errType {
	case errorsErrorType:
		name := err.Error()
		if len(name) > maxErrorName {
			name = name[:maxErrorName]
		}
		return name
	}

	return errType.String()
}
