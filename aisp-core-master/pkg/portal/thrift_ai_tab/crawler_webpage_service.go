package thrift_ai_tab

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal"
	"github.com/apache/thrift/lib/go/thrift"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type AispCrawlerWebpageService struct {
	serviceName       string
	crawlerWebpageDao dao.CrawlerWebpageDao
}

func NewAispCrawlerWebpageService() *AispCrawlerWebpageService {
	return &AispCrawlerWebpageService{
		serviceName:       "AispCrawlerWebpageService",
		crawlerWebpageDao: impl.DefaultCrawlerWebpageDao,
	}
}

func (s *AispCrawlerWebpageService) BatchGetContentWithFieldsByIdsAngleless(ctx context.Context, param *content.BatchGetContentWithFieldsByIdsAnglelessParam) (r *content.BatchGetContentWithFieldsResp, err error) {
	methodName := "BatchGetContentWithFieldsByIdsAngleless"
	logger := log.WithFields(ctx, map[string]interface{}{
		"service": s.serviceName,
		"s":       methodName,
		"request": param,
	})
	logger.Info(ctx, "do request")
	haloSpan := halo.NewHalo(ctx, fmt.Sprintf("%s_%s", "AISP", s.serviceName), methodName)
	nowTime := time.Now()
	defer func() {
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		// response 打点
		s.statsResponse(ctx, methodName, nowTime)
	}()

	keys := make([]*model.CrawlerWebPageKey, 0)
	for _, objectInfo := range param.ObjectInfos {
		keys = append(keys, &model.CrawlerWebPageKey{
			DocId:   cast.ToInt64(objectInfo.GetOutID()),
			DocType: model.GetDocType(objectInfo.GetType()).String(),
		})
	}

	response := &content.BatchGetContentWithFieldsResp{}
	webpages, err := s.crawlerWebpageDao.BatchGet(ctx, keys)
	if err != nil {
		logger.Errorf(ctx, "BatchGetContentWithFieldsByIdsAngleless err. err=%v", err)
		return response, err
	}

	webpageProtos := make([]*base.ContentInfoWrapper, 0)
	for _, webpage := range webpages {
		webpageProtos = append(webpageProtos, &base.ContentInfoWrapper{
			Content: &base.ContentInfo{
				OutID:       util.Int64String(webpage.DocId),
				ContentType: content_core_thrift.ContentTypeCrawlerWebpage,
				Title:       thrift.StringPtr(webpage.Title),
				ContentBody: &base.ContentBody{
					Body: webpage.Content,
				},
				ExtInfo: &base.ContentExtInfo{
					URL: thrift.StringPtr(webpage.MetaUrl),
				},
				Published: webpage.PublishTime,
				BizExt: thrift.StringPtr(string(lo.Must(json.Marshal(map[string]interface{}{
					"is_crawler_allowed": lo.Ternary(webpage.IsCrawlerAllowed == 1, true, false),
					"domain":             webpage.Domain,
					"source":             webpage.Source,
					"source_level":       webpage.SourceLevel,
				})))),
			},
		})
	}

	response.Contents = webpageProtos
	return response, nil
}

func (s *AispCrawlerWebpageService) statsResponse(ctx context.Context, api string, nowTime time.Time) {
	ctx = s.contextWithReq(ctx, api)
	// 记录耗时
	util.Timing(ctx, portal.BizResponseStatsByBizFmt, time.Since(nowTime), "api", api, "request_time")
	// 记录请求数
	util.Increment(ctx, portal.BizResponseStatsByBizFmt, "api", api, "count")
}

func (s *AispCrawlerWebpageService) contextWithReq(ctx context.Context, api string) context.Context {
	ctx = log.ContextWithScene(ctx, fmt.Sprintf("%s.%s", api, "default"))
	return ctx
}

func (s *AispCrawlerWebpageService) GetContentWithFieldsByIdAngled(ctx context.Context, param *content.GetContentWithFieldsByIdAngledParam) (r *content.GetContentWithFieldsResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetContentWithFieldsByIdsAngled(ctx context.Context, param *content.BatchGetContentWithFieldsByIdsAngledParam) (r *content.BatchGetContentWithFieldsResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) GetContentWithFieldsByIdAngleless(ctx context.Context, param *content.GetContentWithFieldsByIdAnglelessParam) (r *content.GetContentWithFieldsResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetContentWithFieldsByAuthorAngled(ctx context.Context, param *content.BatchGetContentWithFieldsByAuthorAngledParam) (r *content.BatchGetContentWithFieldsByAuthorAngledResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetContentWithFieldsByContentRelation(ctx context.Context, param *content.BatchGetContentWithFieldsByContentRelationParam) (r *content.BatchGetContentWithFieldsByContentRelationResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetStructuredSegmentsByIds(ctx context.Context, param *content.BatchGetStructuredSegmentsByIdsParam) (r *content.BatchGetStructuredSegmentsByIdsResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) GetStructuredSegmentsByID(ctx context.Context, param *content.GetStructuredSegmentsByIdParam) (r *content.GetStructuredSegmentsByIdResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) GetSegmentLikeMarks(ctx context.Context, param *content.GetSegmentLikeMarksParam) (r *content.GetSegmentLikeMarksResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) VipContentDataSync(ctx context.Context, param *content.VipContentDataSyncParam) (r *content.VipContentDataSyncResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) UpdateContentState(ctx context.Context, param *content.SetContentStateParam) (r *content.SetContentStateResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) CreateContent(ctx context.Context, param *content.CreateContentParam) (r *content.CreateContentResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) UpdateContent(ctx context.Context, param *content.UpdateContentParam) (r *content.UpdateContentResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) RemoveContent(ctx context.Context, param *content.RemoveContentParam) (r *content.RemoveContentResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BindContentTopics(ctx context.Context, param *content.BindContentTopicsParam) (r *content.BindContentTopicsResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) UpdateContentCommentPermission(ctx context.Context, param *content.UpdateContentCommentPermissionParam) (r *content.UpdateContentCommentPermissionResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) ContentsRenderByNative(ctx context.Context, param *content.ContentsRenderByNativeParam) (r *content.ContentsRenderByNativeResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetContentBodyAngled(ctx context.Context, param *content.BatchGetContentBodyAngledParam) (r *content.BatchGetContentBodyAngledResp, err error) {
	return nil, errors.New("not implemented")
}

func (s *AispCrawlerWebpageService) BatchGetFullContentBody(ctx context.Context, param *content.BatchGetFullContentBodyParam) (r *content.BatchGetFullContentBodyResp, err error) {
	return nil, errors.New("not implemented")
}
