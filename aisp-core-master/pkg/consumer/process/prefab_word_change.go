package process

import (
	"context"
	"encoding/json"
	"errors"

	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type PrefabWordChangeProcessor struct {
	redisDao dao.PrefabWordDao
}

func NewPrefabWordChangeProcessor() *PrefabWordChangeProcessor {
	return &PrefabWordChangeProcessor{
		redisDao: impl.NewPrefabWordDao(),
	}
}

func (d *PrefabWordChangeProcessor) TopicName() macro.TopicName {
	return macro.PrefabWord
}

func (d *PrefabWordChangeProcessor) Process(ctx context.Context, message *stream.Message) error {
	logger := log.WithFields(ctx, map[string]any{
		"class": "PrefabWordChangeProcessor",
		"func":  "Process",
	})

	msg := &module.PrefabWordKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		return errors.New("unmarshal error")
	}

	err = d.redisDao.SavePrefabWordToRedisSet(ctx, msg.GetQueryType(), &dao.PrefabWord{
		AiQuestion:     msg.AiQuestion,
		SourceQuestion: msg.QuestionContent,
	})
	if err != nil {
		logger.Errorf(ctx, "SavePrefabWordToRedisSet sourceMsg:%s error: %v", message.Value, err)
	}
	return err
}
