package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

var _ rpc.ContentProdRPC = (*ContentProdRpcImpl)(nil)

type ContentProdRpcImpl struct {
	contentProdServiceClient *content.ContentServiceClient
	// 最大限制为 30个url 为一个批次
	batchSize int
	bizCode   string
	sceneCode string
}

func NewContentProdRPCImpl() rpc.ContentProdRPC {
	return &ContentProdRpcImpl{
		batchSize: 30,
		contentProdServiceClient: content.NewContentServiceClient(
			tzone.NewClient(
				"ContentService",
				tzone.Timeout(300*time.Millisecond),
				tzone.TargetName("content-prod-rpc"),
			)),
		bizCode:   "AISP_CORE",
		sceneCode: "AISP_CORE",
	}
}

func (c *ContentProdRpcImpl) BatchCurlContentByUrl(ctx context.Context, sourceUrls []string) map[string]*rpc.CurlRespInfo {
	uniqUrls := lo.Uniq(sourceUrls)
	res := make(map[string]*rpc.CurlRespInfo)
	safe_group.BatchGet(c.batchSize, uniqUrls, func(urls interface{}) interface{} {
		return c.batchCurlContentByUrl(ctx, urls.([]string))
	}, &res)
	return res
}

func (c *ContentProdRpcImpl) batchCurlContentByUrl(ctx context.Context, urls []string) map[string]*rpc.CurlRespInfo {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "batchGetContent",
	})

	if urls == nil || len(urls) == 0 {
		return map[string]*rpc.CurlRespInfo{}
	}

	var resp *content.BatchCurlContentByUrlResp
	runFunc := func(ctx context.Context) error {
		respTmp, err := c.contentProdServiceClient.BatchCurlContentByURL(ctx, &content.BatchCurlContentByUrlParam{
			Urls: urls,
		})
		if err != nil {
			logger.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		resp = respTmp
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	if resp == nil || resp.GetInfos() == nil || len(resp.GetInfos()) == 0 {
		return map[string]*rpc.CurlRespInfo{}
	}

	resMap := make(map[string]*rpc.CurlRespInfo, len(resp.GetInfos()))
	for _, v := range resp.GetInfos() {
		resMap[v.GetURL()] = v
	}
	return resMap
}

func (c *ContentProdRpcImpl) BatchGetContent(ctx context.Context, items []model.Content, withFields *content.WithFieds) map[model.Content]*content.Content {
	result := make(map[model.Content]*content.Content)
	if items == nil || len(items) == 0 {
		return result
	}

	safe_group.BatchGet(c.batchSize, items, func(ids interface{}) interface{} {
		return c.batchGetContent(ctx, ids.([]model.Content), withFields)
	}, &result)
	return result
}

func (c *ContentProdRpcImpl) batchGetContent(ctx context.Context, items []model.Content, withFields *content.WithFieds) map[model.Content]*content.Content {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "batchGetContent",
	})

	result := make(map[model.Content]*content.Content)
	if items == nil || len(items) == 0 {
		return result
	}

	runFunc := func(ctx context.Context) error {
		prodOutPairs := make([]*content.OutIDTypePair, 0, len(items))
		for _, item := range items {
			prodOutPairs = append(prodOutPairs, &content.OutIDTypePair{
				Type:  model.GetContentType(item.ContentType),
				OutID: util.Int64String(item.ContentID),
			})
		}

		param := &content.BatchGetContentWithFieldParam{
			BizCode:     c.bizCode,
			SceneCode:   c.sceneCode,
			ObjectInfos: prodOutPairs,
			WithFields:  withFields,
		}
		response, err := c.contentProdServiceClient.BatchGetContentWithField(ctx, param)
		if err != nil {
			logger.Errorf(ctx, "rpc call failed, err: %v", err)
			return err
		}
		if response == nil {
			logger.Errorf(ctx, "response nil")
			return nil
		}

		for _, wrapper := range response.GetContents() {
			resContent := wrapper.GetContent()
			if resContent == nil || resContent.GetContentInfo() == nil {
				continue
			}
			itemId, transErr := util.String2Int64(resContent.GetContentInfo().GetOutID())
			if transErr != nil {
				logger.Errorf(ctx, "transErr:%v", transErr)
				continue
			}
			result[model.NewContentWithContentType(itemId, resContent.ContentInfo.GetContentType())] = resContent
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}
