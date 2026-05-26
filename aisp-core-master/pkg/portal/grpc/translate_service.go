package grpc

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/html_translator"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal"
	"google.golang.org/grpc"
)

var RegisterAispTranslateServiceServer = func(registrar grpc.ServiceRegistrar) {
	proto.RegisterAispTranslateServiceServer(registrar, NewAispTranslateService())
}

type AispTranslateService struct {
	proto.UnimplementedAispTranslateServiceServer

	serviceName       string
	klaraModelService klara_model.KlaraModelService
}

var _ proto.AispTranslateServiceServer = &AispTranslateService{}

func NewAispTranslateService() *AispTranslateService {
	return &AispTranslateService{
		serviceName:       "AispTranslateService",
		klaraModelService: klara_model.NewKlaraModelServiceImpl(),
	}
}

func (s *AispTranslateService) TranslateHTML(ctx context.Context, req *proto.TranslateHTMLRequest) (*proto.TranslateHTMLResponse, error) {
	methodName := "TranslateHTML"
	logger := log.WithFields(ctx, map[string]interface{}{
		"service": s.serviceName,
		"s":       methodName,
		"request": req,
	})
	logger.Info(ctx, "do request")
	haloSpan := halo.NewHalo(ctx, fmt.Sprintf("%s_%s", "AISP", s.serviceName), methodName)
	nowTime := time.Now()
	defer func() {
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		// response 打点
		s.statsResponseWithAb(ctx, methodName, nowTime)
	}()

	// 组装忽略翻译的选择器
	notTranslatedSelections := make([]string, 0)
	notTranslatedSelections = append(notTranslatedSelections, html_translator.DefaultNotTranslatedSelections...)
	if req.GetNotTranslateSelections() != nil && len(req.GetNotTranslateSelections()) > 0 {
		notTranslatedSelections = append(notTranslatedSelections, req.GetNotTranslateSelections()...)
	}

	htmlService, err := html_translator.NewHtmlTranslator(s.klaraModelService,
		req.GetContent(), req.GetSourceLanguage(), req.GetTargetLanguage(), notTranslatedSelections, req.GetExtraInfo())
	if err != nil {
		logger.Errorf(ctx, "TranslateHTML failed. err=%v", err)
		return &proto.TranslateHTMLResponse{
			Status:  macro.SERVICE_TRANSLATE_HTML_INIT_ERR.Code(),
			Message: macro.SERVICE_TRANSLATE_HTML_INIT_ERR.Message(),
		}, nil
	}

	translateResponse, tErr := htmlService.DoTranslate(ctx)
	if tErr != nil {
		log.Errorf(ctx, "TranslateHTML failed. err=%v", tErr)
		return &proto.TranslateHTMLResponse{
			Status:  -1,
			Message: fmt.Sprintf("TranslateHTML failed. err=%s", tErr.Error()),
		}, nil
	}

	if !translateResponse.IsAllTranslated {
		return &proto.TranslateHTMLResponse{
			Status:           macro.SERVICE_TRANSLATE_NOT_FULLY_TRANSLATED.Code(),
			Message:          macro.SERVICE_TRANSLATE_NOT_FULLY_TRANSLATED.Message(),
			TranslateContent: translateResponse.TranslatedContent,
		}, nil
	}
	return &proto.TranslateHTMLResponse{
		TranslateContent: translateResponse.TranslatedContent,
	}, nil
}

func (s *AispTranslateService) statsResponseWithAb(ctx context.Context, api string, nowTime time.Time) {
	ctx = s.contextWithReq(ctx, api)
	// 记录耗时
	util.Timing(ctx, portal.BizResponseStatsByBizFmt, time.Since(nowTime), "api", api, "request_time")
	// 记录请求数
	util.Increment(ctx, portal.BizResponseStatsByBizFmt, "api", api, "count")
}

func (s *AispTranslateService) contextWithReq(ctx context.Context, api string) context.Context {
	ctx = log.ContextWithScene(ctx, fmt.Sprintf("%s.%s", api, "default"))
	return ctx
}
