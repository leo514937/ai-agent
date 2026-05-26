package macro

type SERVICE_CODE int64

const (
	SERVICE_CODE_SUCCESS SERVICE_CODE = 0 // 成功

	SERVICE_CODE_DB_ERR                 SERVICE_CODE = 999001 // 数据库错误
	SERVICE_CODE_CONVERSATION_NOT_FOUND SERVICE_CODE = 999002 // 会话不存在
	SERVICE_CODE_MESSAGE_NOT_FOUND      SERVICE_CODE = 999003 // 消息不存在
	SERVICE_CODE_USER_NOT_FOUND         SERVICE_CODE = 999004 // 用户不存在
	SERVICE_CODE_AUDIT_NOT_FOUND        SERVICE_CODE = 999005 // 安审记录不存在
	SERVICE_ILLEGAL_PARAM               SERVICE_CODE = 999006 // 请求参数不合法

	SERVICE_TRANSLATE_HTML_INIT_ERR        SERVICE_CODE = 999101 // HTML解释器初始化失败
	SERVICE_TRANSLATE_HTML_ERR             SERVICE_CODE = 999102 // HTML翻译失败
	SERVICE_TRANSLATE_NOT_FULLY_TRANSLATED SERVICE_CODE = 999103 // HTML未完全翻译

	SERVICE_FILE_PARSE_ERR SERVICE_CODE = 999201 // 文件解析失败
)

var ServiceCode2Message = map[SERVICE_CODE]string{
	SERVICE_CODE_SUCCESS: "SUCCESS",

	SERVICE_CODE_DB_ERR:                 "db error",
	SERVICE_CODE_CONVERSATION_NOT_FOUND: "conversation not found",
	SERVICE_CODE_MESSAGE_NOT_FOUND:      "message not found",
	SERVICE_CODE_USER_NOT_FOUND:         "user not found",
	SERVICE_CODE_AUDIT_NOT_FOUND:        "audit record not found",
	SERVICE_ILLEGAL_PARAM:               "illegal param",

	SERVICE_TRANSLATE_HTML_INIT_ERR:        "HTML interpreter initialization failed",
	SERVICE_TRANSLATE_HTML_ERR:             "HTML translation failed",
	SERVICE_TRANSLATE_NOT_FULLY_TRANSLATED: "HTML not fully translated",

	SERVICE_FILE_PARSE_ERR: "file parse error",
}

func (e SERVICE_CODE) Code() int64 {
	return int64(e)
}

func (e SERVICE_CODE) Message() string {
	if msg, ok := ServiceCode2Message[e]; ok {
		return msg
	}
	return "unknown error"
}

type ServiceError struct {
	ServiceCode SERVICE_CODE
	error
}

func NewServiceError(code SERVICE_CODE, err error) *ServiceError {
	return &ServiceError{
		ServiceCode: code,
		error:       err,
	}
}

func (e *ServiceError) Code() int64 {
	return int64(e.ServiceCode)
}

func (e *ServiceError) Message() string {
	if msg, ok := ServiceCode2Message[e.ServiceCode]; ok {
		return msg
	}
	return "unknown error"
}

func (e *ServiceError) Error() error {
	return e.error
}
