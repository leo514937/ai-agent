package request

import (
	"context"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
)

type AbsQuest struct {
	host   string
	ctx    context.Context
	client proto.AispTranslateServiceClient
}

type TranslateHTMLRequest struct {
	sourceLanguage proto.Language
	targetLanguage proto.Language
	AbsQuest
}

// DoTranslateHTML 真正模拟客户端 发起 DoTranslateHTML 请求
func (rMsg *TranslateHTMLRequest) DoTranslateHTML(ctx context.Context, content string, sourceLanguage proto.Language, targetLanguage proto.Language) {
	request := &proto.TranslateHTMLRequest{
		Content:        content,
		SourceLanguage: sourceLanguage,
		TargetLanguage: targetLanguage,
	}

	resp, err := rMsg.client.TranslateHTML(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}

	if resp.GetStatus() != 0 {
		fmt.Printf("ERROR => [%s] 输出 TranslateHTMLRequest Response => \n %v \n", resp.GetMessage(), resp.GetTranslateContent())
	} else {
		fmt.Printf("输出 TranslateHTMLRequest Response => \n %v \n", resp.GetTranslateContent())
	}
}

// DoTranslateHTMLResp 真正模拟客户端 发起 DoTranslateHTML 请求
func (rMsg *TranslateHTMLRequest) DoTranslateHTMLResp(ctx context.Context, content string, sourceLanguage proto.Language, targetLanguage proto.Language) *proto.TranslateHTMLResponse {
	request := &proto.TranslateHTMLRequest{
		Content:        content,
		SourceLanguage: sourceLanguage,
		TargetLanguage: targetLanguage,
	}

	resp, err := rMsg.client.TranslateHTML(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}
	if resp.GetStatus() != 0 {
		fmt.Printf("ERROR => [%s] 输出 TranslateHTMLRequest Response => \n %v \n", resp.GetMessage(), resp.GetTranslateContent())
		return nil
	} else {
		return resp
	}
}
