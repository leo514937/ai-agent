package request

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/offline"
)

type QuestionPhraseThriftClient interface {
	DoSaveQuestionPhrase(ctx context.Context, questionPhrases []string)
}

type QuestionPhraseThriftClientImpl struct {
	client *offline.OfflineServiceClient
}

func NewQuestionPhraseThriftClientImpl() *QuestionPhraseThriftClientImpl {
	return &QuestionPhraseThriftClientImpl{
		client: offline.NewOfflineServiceClient(tzone.NewClient(
			"OfflineService",
			tzone.HostPort("localhost", "9999"),
			//tzone.TargetName("aisp-core-thrift-service"),
			tzone.Timeout(1*time.Minute),
		)),
	}
}

func (c *QuestionPhraseThriftClientImpl) DoSaveQuestionPhrase(ctx context.Context, questionPhrases []string) {
	r, err := c.client.SaveQuestionPhrase(ctx, &offline.SaveQuestionPhraseRequest{
		Questions: questionPhrases,
	})
	if err != nil {
		fmt.Printf("error: %v\n", err)
		return
	}
	if r.Code != 0 {
		fmt.Printf("error: %v\n", r.Message)
		return
	}
	fmt.Println("插入questionArr成功")
}
