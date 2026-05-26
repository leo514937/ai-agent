package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 词ID生成

// WordGenerateIdLogic 相关词
type WordGenerateIdLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
	minWordLength int
	maxWordLength int
	wordService   word_service.WordMapperService
}

func NewWordGenerateIdLogic(name string, config map[string]string) *WordGenerateIdLogic {
	res := &WordGenerateIdLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 词最小长度 小于长度则会被过滤
	res.minWordLength = 4
	// 词最大长度 超过长度则会被过滤
	res.maxWordLength = word_service.PrefabWordMaxLength
	res.wordService = word_service.NewWordMapperService()
	res.MappingFunc = res.generateIdMapping
	return res
}

func (l *WordGenerateIdLogic) generateIdMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordGenerateIdLogic.generateIdMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	if items == nil || len(items) == 0 {
		log.Error(ctx, "guide word recall error => nil")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 过滤字数为 maxWordLength 以内的词
	items = lo.Filter(items, func(word *data_frame.ItemData[entities.Item], index int) bool {
		return word.GetBizItem().QueryType != proto.QueryType_QUERY_UNDEFINED &&
			util.UnicodeLen(word.GetBizItem().Text) >= l.minWordLength && util.UnicodeLen(word.GetBizItem().Text) <= l.maxWordLength
	})

	wordDtos := make([]model.WordMapperCreateDto, 0)
	for _, wordItem := range items {
		wordDtos = append(wordDtos, model.WordMapperCreateDto{
			Word:     wordItem.GetBizItem().Text,
			WordType: int32(wordItem.GetBizItem().QueryType),
		})
	}
	batchGetWordIdAndSaveWord := l.wordService.BatchGetWordIdAndSaveWord(ctx, wordDtos)

	// 返回词
	frameItem := make([]*data_frame.ItemData[entities.Item], 0)
	for wordDto, wordId := range batchGetWordIdAndSaveWord {
		queryItem := l.genQueryItem(wordDto, wordId)
		frameItem = append(frameItem, queryItem.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}

func (l *WordGenerateIdLogic) genQueryItem(wordDto model.WordMapperCreateDto, wordId int64) *entities.Item {
	query := &proto.Query{
		Id:        cast.ToString(wordId),
		Query:     wordDto.Word,
		QueryType: proto.QueryType(wordDto.WordType),
		RiskType:  macro.CensorTypeMap[proto.QueryType(wordDto.WordType)],
	}
	queryItem := entities.ItemFromQuery(query, -1, query.GetRiskType())
	queryItem.GetItemMeta().DocId = cast.ToInt64(query.GetId())
	queryItem.GetItemMeta().DocType = content.DocType_AiPrefabWord
	return queryItem
}
