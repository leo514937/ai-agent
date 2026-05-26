package thrift_ai_tab

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/offline"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/juju/ratelimit"
)

type OfflineQuestionWordServiceImpl struct {
	bucket      *ratelimit.Bucket
	wordService word_service.WordMapperService
	riskClient  rpc.RiskCheckRPC
}

func NewOfflineQuestionWordServiceImpl() *OfflineQuestionWordServiceImpl {
	return &OfflineQuestionWordServiceImpl{
		// 创建一个令牌桶，每秒填充一次，桶的容量为200
		bucket:      ratelimit.NewBucket(time.Second, 200),
		wordService: word_service.NewWordMapperService(),
		riskClient:  rpcImpl.NewRiskCheckRPCImpl(),
	}
}

var DefaultOfflineQuestionWordService = NewOfflineQuestionWordServiceImpl()

func (o *OfflineQuestionWordServiceImpl) SaveQuestionPhrase(ctx context.Context, req *offline.SaveQuestionPhraseRequest) (*offline.SaveQuestionPhraseResponse, error) {
	logger := log.WithField(ctx, "func", "pkg/portal/thrift_ai_tab/offline_word_service/SaveQuestionPhrase")
	questions := req.GetQuestions()

	wg := safe_group.NewGroup("DoSaveQuestionPhrase")

	for _, question := range questions {
		questionTmp := question
		wg.Go(func() error {
			// 增加协程限流
			o.bucket.Wait(1)

			// 调用安全审核
			res, rErr := o.riskClient.RiskCheckInterestWord(ctx, questionTmp, "OFFLINE_QUESTION_WORD")
			if rErr != nil {
				logger.Errorf(ctx, "risk check error => %s, error: %v", questionTmp, rErr)
				return rErr
			}
			if res.Res != rpc.RiskCheckResPass {
				logger.Warnf(ctx, "risk check unpass => %v", questionTmp)
				return nil
			}

			_, wErr := o.wordService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
				WordType: int32(proto.QueryType_PREFAB_WORD_QUESTION),
				Word:     questionTmp,
			})
			if wErr != nil {
				logger.Errorf(ctx, "word id gen error => word:%v err:%v", questionTmp, wErr)
				return wErr
			}
			return nil
		})
	}
	err := wg.Wait()
	if err != nil {
		logger.Errorf(ctx, "save question phrase safegroup wait error => %v", err)
	}
	return &offline.SaveQuestionPhraseResponse{Code: 0}, nil
}
