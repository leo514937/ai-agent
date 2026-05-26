package retrieval

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/spf13/cast"
)

// ExternalSiteableRetrievalLogic 站外召回，支持「query site:xxx」的召回
// @logicAuthor: quanrui
type ExternalSiteableRetrievalLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	bingClient rpc.BingClientRPC
}

func NewExternalSiteableRetrievalLogic(name string, config map[string]string) *ExternalSiteableRetrievalLogic {
	res := &ExternalSiteableRetrievalLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.bingClient = impl.DefaultBingClient
	res.RealDoFunc = res.retrieve
	return res
}

func (s *ExternalSiteableRetrievalLogic) retrieve(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	logger := log.WithFields(ctx, map[string]any{
		"func": "ExternalSiteableRetrievalLogic.realMapping",
	})
	queryPostfix := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.ConfigRetrieveQuerySite)
	recallSize := cast.ToInt32(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.ConfigRetrieveSize))

	query, _ := requestCtx.DataMap().GetString(ctx, s.GetInputName(0))
	if query == "" {
		return nil
	}

	logger.Infof(ctx, "print searchRecallSize: %d", recallSize)
	if recallSize <= 0 {
		return nil
	}
	// 召回 站外摘要文章
	contentResult := s.contentRecall(ctx, query, recallSize, queryPostfix)

	requestCtx.DataMap().SetObjMap(ctx, s.GetOutputName(0), contentResult)
	return nil
}

// Recall 内容召回
func (s *ExternalSiteableRetrievalLogic) contentRecall(ctx context.Context,
	query string, recallSize int32, queryPostfix string) []*rpc.OutSiteSearchRecallAnswerResult {
	recallQuery := s.genRecallQuery(query, queryPostfix)

	// 站外搜索召回文章
	searchRecall, err := s.bingClient.BingSearch(ctx, recallQuery, recallSize, nil)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "bing search error")
		return nil
	}
	return searchRecall[:zrecUtil.Min(int(recallSize), len(searchRecall))]
}

func (s *ExternalSiteableRetrievalLogic) genRecallQuery(query string, queryPostfix string) string {
	recallQuery := query
	if queryPostfix != "" {
		recallQuery = fmt.Sprintf("%s site:%s", query, queryPostfix)
	}
	return recallQuery
}
