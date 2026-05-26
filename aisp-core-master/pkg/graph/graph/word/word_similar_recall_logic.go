package word

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 相似词召回

type WordSimilarRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK          int
	tagRecallTopK int32
	client        rpc.SimilarGRPC
}

func NewWordSimilarRecallLogic(name string, config map[string]string) *WordSimilarRecallLogic {
	res := &WordSimilarRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认最多召回100个
	res.topK = 100
	res.tagRecallTopK = 20
	res.client = rpcImpl.DefaultSimilarGrpcImpl
	res.RecallFunc = res.similarRecall
	return res
}

func (l *WordSimilarRecallLogic) similarRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordSimilarRecallLogic.similarRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithField(ctx, "similarRecall", "")

	// 获取用户tags
	var tags = user.GetBizUser().UserMeta().GetTags()
	log.Infof(ctx, "similarRecall print mmember tag => %v", tags)
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "similarRecall"), 3000)

	// 定义一个 channel 用来传输 Item 结构体
	doneCh := make(chan int)
	itemChan := make(chan *entities.Item, l.topK)

	// 后续根据实际情况调整, 提升每次返回个数 or 补充默认标签个数
	//topKnew := l.topK / (len(tags) * 2)
	// 查询 段落词
	for _, tag := range tags {
		tagTmp := tag
		wg.Go(func() error {
			// similar 召回词
			l.similarRecallWord(ctx, logger, doneCh, itemChan, tagTmp, l.tagRecallTopK,
				rpc.SimilarSourceCodeParagraphKeyword, proto.QueryType_PARAGRAPH)
			return nil
		})
	}
	// 查询 兴趣词
	for _, tag := range tags {
		tagTmp := tag
		wg.Go(func() error {
			// similar 召回词
			l.similarRecallWord(ctx, logger, doneCh, itemChan, tagTmp, l.tagRecallTopK,
				rpc.SimilarSourceCodeInterestKeyword, proto.QueryType_INTEREST_EXPANSION)
			return nil
		})
	}

	// 等待所有 goroutine 完成
	go func() {
		err := wg.Wait()
		if err != nil {
			logger.Warnf(ctx, "similarRecallWord Wait Err => %v", err)
		}
		close(doneCh)
		close(itemChan)
	}()

	// 方案2 使用召回Id
	var queries []*entities.Item
	for item := range itemChan {
		queries = append(queries, item)
	}

	groupQueries := lo.GroupBy(queries, func(item *entities.Item) string {
		return item.QueryType.String()
	})

	// 分组随机 保障每个类型的得到的个数一致
	var results []*entities.Item
	for _, v := range groupQueries {
		randomArr := util.RandomPick(v, l.topK/len(groupQueries))
		results = append(results, randomArr...)
	}

	// Score 倒序排序
	//sort.Slice(results, func(i, j int) bool {
	//	return results[i].QueryScore > results[j].QueryScore
	//})

	// 返回词
	var frameItem []*data_frame.ItemData[entities.Item]
	for _, item := range results {
		frameItem = append(frameItem, item.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}

// similarRecallWord 召回词
func (l *WordSimilarRecallLogic) similarRecallWord(
	ctx context.Context,
	logger *log.ZhihuLogger,
	doneCh chan int,
	itemChan chan *entities.Item,
	tag string, topK int32, sourceCode rpc.SourceCode, queryType proto.QueryType) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordSimilarRecallLogic.similarRecallWord")
	defer span.Finish()

	// 请求接口
	res := l.client.GetSearchV2(ctx, tag, sourceCode, topK)
	if len(res) == 0 {
		return
	}
	for _, tupleRes := range res {
		query := entities.ItemFromQuery(&proto.Query{
			Id:        cast.ToString(tupleRes.A.DocId),
			Query:     tupleRes.A.Content,
			QueryType: queryType,
		}, tupleRes.B, macro.CensorTypeMap[queryType])
		// 使用select来判断channel是否关闭
		select {
		case <-doneCh:
			logger.Warnf(ctx, "Stop sending, channel is closed => %+v", query)
			break
		default:
			itemChan <- query
		}
	}
}
