package main

import (
	"context"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/ask_related_word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/user_feedback"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	jobName := os.Args[1]
	log.Infof(context.Background(), "args: %v", os.Args)
	switch jobName {
	case "answer-ask-related-word":
		log.Info(context.Background(), "answer-ask-related-word")
		_ = ask_related_word.RunReadHiveAndRefreshAskRelatedWord()
	case "clear-session-expire-cache":
		// 清除 session 过期缓存（重答）
		log.Info(context.Background(), "clear-session-expire-cache")
		logicSessionCache := impl.NewLogicSessionCacheByTiDBImplBySource[[]*entities.Item]()
		logicSessionCache.ClearExpireCache(context.Background())
	case "clear-event-expire-trace":
		// 清除 event trace 过期数据
		log.Info(context.Background(), "clear-event-expire-trace")
		chatEventChainLinkTraceDao := impl.NewChatEventChainLinkTraceDao()
		chatEventChainLinkTraceDao.ClearExpireCache(context.Background())
	case "sync-user-feedback":
		// 同步用户反馈到 badcase 管理平台
		log.Info(context.Background(), "sync-user-feedback")
		user_feedback.SyncUserFeedBack()
	}
	log.Info(context.Background(), "job run done！")
}
