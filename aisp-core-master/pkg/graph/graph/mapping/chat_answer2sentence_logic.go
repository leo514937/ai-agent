package mapping

import (
	"context"
	"regexp"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 相关问题chat结果转换
type ChatAnswer2SentenceLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
	wordService word_service.WordMapperService
}

func NewChatAnswer2SentenceLogic(name string, config map[string]string) *ChatAnswer2SentenceLogic {
	res := &ChatAnswer2SentenceLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	res.wordService = word_service.NewWordMapperService()
	return res
}

func (s *ChatAnswer2SentenceLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "mapping.ChatAnswer2SentenceLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	logger := log.WithField(ctx, "chatAnswer2SentenceLogic", "")

	var result []*data_frame.ItemData[entities.Item]

	// 用户原始Query
	sourceQuery := requestCtx.GetBizContext().GetCurrentDialogue().Query
	if sourceQuery == nil || sourceQuery.MessageContent == "" {
		logger.Warnf(ctx, "sourceQuery is nil or sourceQuery.MessageContent is empty")
		return result, nil
	}

	isChineseByQueryAndAnswer := requestCtx.GetBizContext().IsChineseByQueryAndAnswer()

	// 转换成相关句子
	var sentences []string

	for _, item := range items {
		sentenceSlice := strings.Split(item.GetBizItem().Text, "\n")
		for _, sentence := range sentenceSlice {
			// 去除首尾空格换行
			sentence = strings.TrimSpace(sentence)
			// 去除开头的数字和点
			re := regexp.MustCompile(`^\d+\.`)
			sentence = re.ReplaceAllString(sentence, "")
			// 去除首尾空格换行
			sentence = strings.TrimSpace(sentence)
			// 不等于原始query
			if sentence == sourceQuery.MessageContent {
				continue
			}

			if isChineseByQueryAndAnswer {
				// 4-35个字符，以问号结尾
				if util.UnicodeLen(sentence) >= 4 && util.UnicodeLen(sentence) <= 35 &&
					strings.HasSuffix(sentence, "？") {
					sentences = append(sentences, sentence)
				}
			} else {
				// 10-70个字符，以问号结尾
				if util.UnicodeLen(sentence) >= 10 && util.UnicodeLen(sentence) <= 70 &&
					(strings.HasSuffix(sentence, "?") || strings.HasSuffix(sentence, "？")) {
					sentences = append(sentences, sentence)
				}
			}
		}
	}

	// 并发读取 wordId，拼接成 item 的格式
	var doneCh = make(chan int)
	var resultChan = make(chan *entities.Item, len(sentences))
	group := safe_group.NewGroupWithTimeout("BatchGetWordIdAndSaveWord", 1000).SetLimit(5)
	for _, sentence := range sentences {
		sentence := sentence
		group.Go(func() error {
			sentenceItem := entities.ItemWithTextAndType(sentence, entities.ChatMappingTypeQuestion)
			sentenceItem.QueryType = proto.QueryType_RELATE_WORD_QUESTION
			wordId, err := s.wordService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
				WordType: int32(sentenceItem.QueryType),
				Word:     sentence,
			})

			if err != nil {
				logger.Warnf(ctx, "word id gen error => word:%v err:%v", sentence, err)
				return err
			}

			sentenceItem.QueryId = cast.ToString(wordId)
			sentenceItem.QueryCensorType = macro.CensorTypeMap[proto.QueryType_RELATE_WORD_QUESTION]
			// 使用select来判断channel是否关闭
			select {
			case <-doneCh:
				logger.Warnf(ctx, "Stop sending, channel is closed => %+v", sentenceItem)
				return nil
			default:
				resultChan <- sentenceItem
			}
			return nil
		})
	}

	// 等待所有 goroutine 完成
	go func() {
		wgErr := group.Wait()
		if wgErr != nil {
			logger.Warnf(ctx, "Get WordId Wait Err => %v", wgErr)
		}
		close(doneCh)
		close(resultChan)
	}()

	// 返回词
	for queryItem := range resultChan {
		result = append(result, queryItem.IntoFrameItem(requestCtx))
	}

	s.saveTracing(logCtx, startTime, items, result, requestCtx)

	return result, nil

}

func (s *ChatAnswer2SentenceLogic) saveTracing(logCtx context.Context, startTime int64, items []*data_frame.ItemData[entities.Item], result []*data_frame.ItemData[entities.Item], requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	var inputText []string
	var outputText []string
	for _, item := range items {
		inputText = append(inputText, item.GetBizItem().Text)
	}
	for _, item := range result {
		outputText = append(outputText, item.GetBizItem().Text)
	}
	logicTracing := &proto.LogicTracing{
		LogicName:   s.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(inputText)},
		LogicOutput: []string{util.GetJSONIgnoreError(outputText)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(s.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(inputText))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(outputText))

}
