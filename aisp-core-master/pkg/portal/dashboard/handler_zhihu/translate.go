package handler_zhihu

import (
	"context"
	"errors"
	"fmt"
	"text/template"

	"git.in.zhihu.com/go/cafe/rest"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/html_translator"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type TranslateHandler struct {
	rest.BaseHandler
	contentProRpc     rpc.ContentProdRPC
	klaraModelService *klara_model.KlaraModelServiceImpl
}

func NewTranslateHandler() rest.Handler {
	return &TranslateHandler{
		contentProRpc:     impl.NewContentProdRPCImpl(),
		klaraModelService: klara_model.NewKlaraModelServiceImpl(),
	}
}

func (t *TranslateHandler) Get(ctx *rest.Context) (rest.Response, error) {

	url := ctx.QueryArgument("url")
	modelName := ctx.QueryArgument("model_name")

	var htmlContent = ""
	var htmlTitle = ""
	contentProRes := t.contentProRpc.BatchCurlContentByUrl(ctx, []string{url})
	for _, res := range contentProRes {
		htmlContent = res.GetContent()
		htmlTitle = res.GetTitle()
	}

	var translatedContent = ""
	safe_group.SafeGoWait("content_translate", func() error {
		translator, err := html_translator.NewHtmlTranslator(t.klaraModelService,
			htmlContent, proto.Language_zh, proto.Language_en, html_translator.DefaultNotTranslatedSelections, nil)
		if err != nil {
			log.Error(ctx, fmt.Sprintf("create html translator error. %v", err))
			return errors.New(fmt.Sprintf("create html translator error. %v", err))
		}

		var newCtx context.Context = ctx
		if modelName != "" {
			newCtx = context.WithValue(ctx, "model_name", modelName)
		}

		resp, err := translator.DoTranslate(newCtx)
		if err != nil {
			log.Error(ctx, fmt.Sprintf("translate content error. "))
			return errors.New(fmt.Sprintf("translate content error. %s", resp.TranslatedContent))
		}
		translatedContent = resp.TranslatedContent
		return nil
	})

	var translatedTitle = ""
	safe_group.SafeGoWait("title_translate", func() error {
		translator, err := html_translator.NewHtmlTranslator(t.klaraModelService,
			htmlTitle, proto.Language_zh, proto.Language_en, html_translator.DefaultNotTranslatedSelections, nil)
		if err != nil {
			log.Error(ctx, fmt.Sprintf("create html translator error. %v", err))
			return errors.New(fmt.Sprintf("create html translator error. %v", err))
		}

		var newCtx context.Context = ctx
		if modelName != "" {
			newCtx = context.WithValue(ctx, "model_name", modelName)
		}
		resp, err := translator.DoTranslate(newCtx)
		if err != nil {
			log.Error(ctx, fmt.Sprintf("translate title error. "))
			return errors.New(fmt.Sprintf("translate title error. %s", resp.TranslatedContent))
		}
		translatedTitle = resp.TranslatedContent
		return nil
	})

	var tmpl = template.Must(template.New("translate").Parse(`<html><head>{{.Title}}</head><body>{{.Body}}</body></html>`))
	return t.MakeHTMLResponse(ctx, tmpl, &translateResponse{
		Title: translatedTitle,
		Body:  translatedContent,
	})
}

type translateResponse struct {
	Title string
	Body  string
}
