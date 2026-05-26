package util

import (
	"context"
	"encoding/json"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func FileUnmarshal(fullPath string, v interface{}) error {
	log.WithField(context.TODO(), "util", "FileUnmarshal").Info(context.TODO(), "conf path:", fullPath)
	bytes, err := os.ReadFile(fullPath)
	if err != nil {
		panic(err)
	}
	return json.Unmarshal(bytes, v)
}
