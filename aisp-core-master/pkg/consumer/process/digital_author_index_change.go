package process

import (
	"context"
	"encoding/json"
	"errors"

	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type DigitalAuthorIndexChangeProcessor struct {
	redisDao dao.DigitalAuthorIndexDao
}

func NewDigitalAuthorIndexChangeProcessor() *DigitalAuthorIndexChangeProcessor {
	return &DigitalAuthorIndexChangeProcessor{
		redisDao: impl.DefaultFeatureUsageInfoDaoImpl,
	}
}

func (d *DigitalAuthorIndexChangeProcessor) TopicName() macro.TopicName {
	return macro.DigitalAuthorIndexChange
}

func (d *DigitalAuthorIndexChangeProcessor) Process(ctx context.Context, message *stream.Message) error {
	msg := &module.IndexChangeKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		return errors.New("unmarshal error")
	}

	// 只处理单条内容增删操作
	if msg.OpType != module.Single {
		return nil
	}

	if msg.MethodType != module.Upsert && msg.MethodType != module.Delete {
		return nil
	}

	log.Infof(ctx, "index change msg:%s", util.GetJSONIgnoreError(msg))

	var docStatus = msg.MethodType == module.Upsert

	docId := msg.DocId
	docType := content.DocType_Type(content.DocType_Type_value[msg.DocType])

	if docId != 0 && docType != content.DocType_Unknown {
		return d.redisDao.SetOnSiteIndexStatus(ctx, docId, docType, docStatus)
	}

	return nil
}
