package main

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	hotContentDao := impl.DefaultHotContentProductDAO

	pDate := "2024-12-16"
	err := hotContentDao.DeleteByPDate(context.Background(), pDate)
	if err != nil {
		log.Errorf(context.Background(), "delete hot content by p_date failed, p_date: %s, err: %v", pDate, err)
	}
}
