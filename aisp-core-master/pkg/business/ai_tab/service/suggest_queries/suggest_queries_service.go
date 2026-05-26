package suggest_queries

import (
	"context"
	"sync"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	dao "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/pkg/errors"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"golang.org/x/exp/rand"
)

var wordsRandom = [...]string{
	"电脑", "手机", "相机", "平板", "路由器",
	"耳机", "键盘", "鼠标", "显示器", "电源适配器",
	"内存", "硬盘", "显卡", "主板", "处理器",
	"充电宝", "网络摄像头", "手表", "音响", "投影仪",
	"智能家居", "无人机", "游戏机", "智能手环", "数码相框",
	"笔记本电脑", "打印机", "音响", "扫地机器人", "VR头盔",
	"电视机", "冰箱", "洗衣机", "空调", "微波炉",
	"吹风机", "热水器", "空气净化器", "电饭煲", "榨汁机",
	"面包机", "咖啡机", "电动牙刷", "电子书阅读器", "电磁炉",
	"数码相机", "智能门锁", "智能体重秤", "蓝牙耳机", "USB风扇",
	"智能眼镜", "智能垃圾桶", "智能手表", "智能洗手液器", "智能马桶",
}

// SuggestQueriesToProto 转化为 ProtoBuf
func SuggestQueriesToProto(ctx context.Context, req *proto.SuggestQueriesRequest) (p *proto.SuggestQueriesResponse, ex error) {
	defer func() {
		if r := recover(); r != nil {
			ex = errors.Errorf("执行SuggestQueriesToProto发生异常 => %v", r)
		}
	}()

	switch req.Type {
	case proto.SuggestQueriesType_AI_TAB_GUIDE:
		// AI Tab 引导词 需要组合 AI段落词 和 AI兴趣词
		// TODO 生成数字模拟，具体策略需要根据算法来定
		// TODO 生成段落词
		paragraphWords := tmpBuildWords(15, int32(proto.QueryType_PARAGRAPH), "")
		// TODO 生成兴趣词
		interestWords := tmpBuildWords(15, int32(proto.QueryType_INTEREST_EXPANSION), "")
		union := lo.Union[*model.WordMapperCreateDto](paragraphWords, interestWords)
		return wrapperResponse(ctx, union)
	case proto.SuggestQueriesType_SEARCH_TAB_GUIDE:
		// AI Tab 引导词 需要组合 AI段落词 和 AI兴趣词
		// TODO 生成数字模拟，具体策略需要根据算法来定
		// TODO 生成段落词
		//paragraphWords := tmpBuildWords(15, int32(proto.QueryType_PARAGRAPH), "")
		// TODO 生成兴趣词
		//interestWords := tmpBuildWords(15, int32(proto.QueryType_INTEREST_EXPANSION), "")
		// TODO 猜你想搜词
		//guessWords := tmpBuildWords(15, int32(proto.QueryType_GUESS_WORD), "111222")
		// 调用猜你想搜词接口 (1.12 版本全部要用猜你想搜词接口)
		guessWords, err := rpcImpl.DefaultGuessThriftRpcService.GetGuessQueries(ctx, int32(proto.QueryType_GUESS_WORD), req)
		if err != nil {
			return nil, err
		}

		//union := lo.Union[model.WordMapperCreateDto](*paragraphWords, *interestWords, *guessWords)
		return wrapperResponse(ctx, guessWords)
	case proto.SuggestQueriesType_AI_TAB_RELATED:
		// TODO 生成数字模拟，具体策略需要根据算法来定
		// TODO 生成相关词
		searchWords := tmpBuildWords(15, int32(proto.QueryType_RELATE_WORD), "333444")
		return wrapperResponse(ctx, searchWords)
	default:
		return nil, errors.Errorf("请求类型未定义或类型未匹配 => %v", req.Type)
	}
}

// wrapperResponse 包装 Response
func wrapperResponse(ctx context.Context, wordsDto []*model.WordMapperCreateDto) (*proto.SuggestQueriesResponse, error) {

	// 先分组 准备去重
	wordGroups := lo.GroupBy(wordsDto, func(p *model.WordMapperCreateDto) string {
		return p.Word
	})

	length := len(wordGroups)
	wordsSlice := make([]*model.WordMapperCreateDto, length)

	// 如果是 猜你想搜 或者 相关词 则优先
	var index int
	for _, wordsTmp := range wordGroups {
		var wTmp *model.WordMapperCreateDto
		for _, w := range wordsTmp {
			wTmp = w
			if w.WordType == int32(proto.QueryType_GUESS_WORD) ||
				w.WordType == int32(proto.QueryType_RELATE_WORD) {
				break
			}
		}
		wordsSlice[index] = wTmp
		index++
	}

	// 获取词Id 如果本身有SourceId 则直接使用
	var sMap sync.Map
	var wg sync.WaitGroup
	for i := 0; i < length; i++ {
		wordDto := wordsSlice[i]
		if wordDto.SourceId != "" {
			sMap.Store(wordDto.Word, wordDto.SourceId)
			continue
		}

		wg.Add(1)
		safe_group.SafeGo(func() error {
			defer wg.Done()
			wordId, err := dao.DefaultWordMapperDAO.GetWordIdAndCreate(ctx, wordDto)
			if err != nil {
				return err
			}
			sMap.Store(wordDto.Word, cast.ToString(wordId))
			return nil
		}, "suggest_queries")
	}
	wg.Wait()

	var queries []*proto.Query
	// 匹配Map中词Id 如果Id 不存在 则当前词默认不生成
	for _, wordObj := range wordsSlice {
		wordId, ok := sMap.Load(wordObj.Word)
		if ok && wordId != "" {
			queryPoint := &proto.Query{
				Id:        cast.ToString(wordId),
				Query:     cast.ToString(wordObj.Word),
				QueryType: proto.QueryType(wordObj.WordType),
			}
			// 使用 append 将元素追加到切片末尾
			queries = append(queries, queryPoint)
		}
	}

	return &proto.SuggestQueriesResponse{
		Queries: queries,
	}, nil
}

// tmpBuildWords 临时方法模拟生成 推荐词
func tmpBuildWords(count int, wordType int32, sourceId string) []*model.WordMapperCreateDto {
	// 是否根据 sessionId 查询历史内容 构建QueryMerge词
	// 模拟QueryMerge生成
	// requestInfo := req.Info()
	words := make([]*model.WordMapperCreateDto, count)
	for i := 0; i < count; i++ {
		words[i] = &model.WordMapperCreateDto{
			WordType: wordType,
			SourceId: sourceId,
			Word:     wordsRandom[rand.Intn(len(wordsRandom))],
		}
	}
	return words
}
