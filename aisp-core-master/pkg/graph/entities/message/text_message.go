package message

import "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"

type TextMessage struct {
	Content string `json:"content"`
}

func (t TextMessage) ToJsonString() (string, error) {
	marshalArr, err := util.JsonMarshalByIgnoreHTML(t)
	if err != nil {
		return "", err
	}
	return string(marshalArr), nil
}
