package impl

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
)

var DefaultAispToolsClient rpc.AispToolsClient

func init() {
	DefaultAispToolsClient = NewAispToolsClientImpl()
}

type AispToolsClientImpl struct {
	httpClient *util.HttpClient
}

const (
	aispToolsUrl   string = "https://aisp.in.zhihu.com/api/tools/task"
	fileBasePrefix        = "data:application/pdf;base64,"
)

func NewAispToolsClientImpl() *AispToolsClientImpl {

	return &AispToolsClientImpl{
		httpClient: util.NewHttpClient(http.MethodPost, aispToolsUrl, 60000*time.Millisecond),
	}
}

func (a *AispToolsClientImpl) ParsePdf(ctx context.Context, processorName rpc.ProcessorName, content []byte) ([]*model.AispToolsItem, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"processorName": processorName,
	})

	item := map[string]interface{}{
		"item_type":   "file_base64",
		"name":        "pdf",
		"sub_task_id": "0",
		"file_base64": fileBasePrefix + base64.StdEncoding.EncodeToString(content),
	}

	body := map[string]interface{}{
		"task_id": uuid.New().String(),
		"processer": map[string]string{
			"processer_type": rpc.ProcessorTypePdfParser.String(),
			"processer_name": processorName.String(),
		},
		"items": []interface{}{item},
		"desc":  "aisp-core pdf parse",
	}

	var resp []*model.AispToolsItem
	lines, err := a.httpClient.DoSse(ctx, nil, nil, body)

	if err != nil || len(lines) == 0 {
		log.Errorf(ctx, "parse pdf failed, response is empty. err=%v", err)
		logger.WithError(ctx, err).Error(ctx, "parse pdf failed")
		util.Increment(ctx, macro.CommonStatsPrefix+".aisp_tools.pdf_failed.count")
		return nil, err
	}

	for _, line := range lines {
		lineResp := &model.AispToolsResponse{}
		err = json.Unmarshal([]byte(line), lineResp)
		if err != nil {
			log.Warnf(ctx, "parse pdf result failed. err=%v", err)
			continue
		}
		if lineResp.Data != nil {
			resp = lineResp.Data.Items
		}
	}

	if len(resp) == 0 {
		util.Increment(ctx, macro.CommonStatsPrefix+".aisp_tools.pdf_failed.count")
	}

	return resp, nil
}

func (a *AispToolsClientImpl) ParseHtml(ctx context.Context, processorName rpc.ProcessorName, content []byte, description string, url string) ([]*model.AispToolsItem, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"processorName": processorName,
	})

	item := map[string]interface{}{
		"item_type":   "html",
		"name":        "html",
		"sub_task_id": "0",
		//"text":        string(content),
		"html": map[string]interface{}{
			"url":     url,
			"content": string(content),
		},
	}

	body := map[string]interface{}{
		"task_id": uuid.New().String(),
		"desc":    description,
		"processer": map[string]string{
			"processer_type": rpc.ProcessorTypeHtmlParser.String(),
			"processer_name": processorName.String(),
		},
		"items": []interface{}{item},
	}

	var resp []*model.AispToolsItem
	lines, err := a.httpClient.DoSse(ctx, nil, nil, body)

	if err != nil || len(lines) == 0 {
		log.Errorf(ctx, "parse html failed, response is empty. err=%v", err)
		logger.WithError(ctx, err).Error(ctx, "parse html failed")
		util.Increment(ctx, macro.CommonStatsPrefix+".aisp_tools.html_failed.count")
		return nil, err
	}

	for _, line := range lines {
		lineResp := &model.AispToolsResponse{}
		err = json.Unmarshal([]byte(line), lineResp)
		if err != nil {
			log.Warnf(ctx, "parse html result failed. err=%v", err)
			continue
		}
		if lineResp.Data != nil {
			resp = append(resp, lineResp.Data.Items...)
		}
	}

	if len(resp) == 0 {
		util.Increment(ctx, macro.CommonStatsPrefix+".aisp_tools.html_failed.count")
	}
	return resp, nil
}
