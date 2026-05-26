package exception

import "fmt"

type Error struct {
	code        string // 错误码，长度为2的字符串组成：两位英文字母+4位数字，格式: 业务模块+操作类型+错误码
	name        string // 错误名称
	description string // 错误描述，运行时没用，辅助开发时用，相当于文档
	message     string // 运行时信息，动态生成
}

func (e *Error) Code() string {
	if e == nil {
		return ""
	}
	return e.code
}

func (e *Error) Name() string {
	if e == nil {
		return ""
	}
	return e.name
}

func (e *Error) Error() string {
	if e == nil {
		return ""
	}
	return fmt.Sprintf("[%s,%s]:%s", e.code, e.name, e.message)
}

func (e *Error) String() string {
	return e.Error()
}

func (e *Error) New(format string, args ...interface{}) error {
	return &Error{
		code:        e.code,
		name:        e.name,
		description: e.description,
		message:     fmt.Sprintf(format, args...),
	}
}

func (e *Error) Wrap(err error) error {
	if err == nil {
		return nil
	}

	msg := err.Error()
	// 防止各种嵌套，只取 message 部分
	switch err := err.(type) {
	case *Error:
		msg = err.message
	}
	return e.New(msg)
}

// Make 用来初始化一个错误常量
func Make(code, name, description string) *Error {
	return &Error{
		code:        code,
		name:        name,
		description: description,
		message:     "",
	}
}
