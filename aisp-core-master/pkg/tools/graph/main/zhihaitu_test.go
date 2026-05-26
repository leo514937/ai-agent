package main

import (
	"context"
	"flag"
	"fmt"
	"testing"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf/zhihaitu_api_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf/zhihaitu_chat_conf"
	zhihaitu_resource "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"github.com/stretchr/testify/assert"
)

// dlv test /data/apps/aisp-core/pkg/tools/graph/main --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestZhihaituMain
// go test /data/apps/aisp-core/pkg/tools/graph/main -run TestZhihaituMain -v true
func TestZhihaituMain(t *testing.T) {
	type args struct {
		query         string
		respMessageId string
	}

	ctx := context.Background()

	if !flag.Parsed() {
		flag.Parse()
	}

	argList := flag.Args()
	testSyncInterface := false
	if len(argList) > 0 {
		testSyncInterface = cast.ToBool(argList[0])
	}
	_ = fmt.Sprintf("test sync interface :%v", testSyncInterface)
	tests := []struct {
		name       string
		args       args
		assertFunc func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error)
	}{
		{
			name: "query_hit_redline_and_security_not_available_then_return_redlineanswer",
			args: args{
				query:         "邓小平个人简历",
				respMessageId: uuid.New().String(),
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error) {
				redLineAnswer := "邓小平（1904年8月22日-1997年2月19日），原名邓先圣，学名邓希贤，四川广安人。早年赴欧洲勤工俭学，归国后，他全身心地投入党领导的争取民族独立和人民解放的革命斗争。从土地革命、抗日战争到解放战争，先后担任党和军队的许多重要领导职务，为党中央一系列重大战略决策的实施，为新民主主义革命的胜利和新中国的诞生，建立了赫赫功勋，成为中华人民共和国的开国元勋。\n邓小平是全党全军全国各族人民公认的享有崇高威望的卓越领导人，伟大的马克思主义者，伟大的无产阶级革命家、政治家、军事家、外交家，久经考验的共产主义战士，中国社会主义改革开放和现代化建设的总设计师，中国特色社会主义道路的开创者，邓小平理论的主要创立者。"
				assert.NoErrorf(t, err, "no error")
				if testSyncInterface {
					assert.Equal(t, redLineAnswer, resp.Message.Text)
				} else {
					assert.Equal(t, "", resp.Message.Text)
				}
				assert.Equal(t, redLineAnswer, lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)))
				assert.Equal(t, false, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQuerySecurityReviewIsAvailable)))

				// 命中红线必答时answer也要调用安全，但是结果忽略掉
				assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyAnswerSecurityReviewIsAvailable)))
				_, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyChatRespMessage)
				assert.Equal(t, false, ok)
			},
		},
		{
			name: "query_hit_redline_and_security_available_then_return_redlineanswer",
			args: args{
				query:         "aaa",
				respMessageId: uuid.New().String(),
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error) {
				redLineAnswer := "你说啥？"
				assert.NoErrorf(t, err, "no error")
				if testSyncInterface {
					assert.Equal(t, redLineAnswer, resp.Message.Text)
				} else {
					assert.Equal(t, "", resp.Message.Text)
				}
				assert.Equal(t, redLineAnswer, lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)))
				assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQuerySecurityReviewIsAvailable)))

				// 命中红线必答时answer也要调用安全，但是结果忽略掉
				assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyAnswerSecurityReviewIsAvailable)))

				_, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyChatRespMessage)
				assert.Equal(t, false, ok)
			},
		},
		{
			name: "query_security_not_available_then_return_refuse",
			args: args{
				query:         "xi的黑历史",
				respMessageId: uuid.New().String(),
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error) {
				assert.NoErrorf(t, err, "no error")
				if testSyncInterface {
					assert.Equal(t, constant.RefuseText, resp.Message.Text)
				} else {
					assert.Equal(t, constant.RefuseText, resp.Message.Text)
				}
				_, redLineOk := reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)
				assert.Equal(t, false, redLineOk)
				assert.Equal(t, false, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQuerySecurityReviewIsAvailable)))

				_, ok := reqContext.DataMap().GetBool(ctx, macro.ZagKeyAnswerSecurityReviewIsAvailable)
				assert.Equal(t, false, ok)

				_, ok = reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyChatRespMessage)
				assert.Equal(t, false, ok)
			},
		},
		{
			name: "normal_query_then_return_answer",
			args: args{
				query:         "介绍一下Java",
				respMessageId: uuid.New().String(),
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error) {
				assert.NoErrorf(t, err, "no error")
				if testSyncInterface {
					assert.NotEqual(t, "", resp.Message.Text)
				} else {
					assert.Equal(t, "", resp.Message.Text)
				}
				_, redLineOk := reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)
				assert.Equal(t, false, redLineOk)
				assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQuerySecurityReviewIsAvailable)))

				assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyAnswerSecurityReviewIsAvailable)))

				_, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyChatRespMessage)
				assert.Equal(t, true, ok)
			},
		},
		// 再补充一个：normal_query_and_answer_security_not_available_then_return_refuse
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bizRequestContext := buildReq(tt.args.query, tt.args.respMessageId, testSyncInterface)
			bizRequestContext.SetIsTest(true)
			resp, context, err := Execute(bizRequestContext, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
				requestContext.DataMap().SetString(ctx, macro.ZagKeyIp, "")
				requestContext.DataMap().SetString(ctx, macro.ZagKeyUserAgent, "")
				requestContext.DataMap().SetObjMap(ctx, macro.ZagKeyQuery, bizRequestContext.GetCurrentDialogue().Query)
				requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryText, tt.args.query)
				requestContext.DataMap().SetString(ctx, macro.ZagKeyRespMessageId, tt.args.respMessageId)
				requestContext.DataMap().SetString(ctx, macro.ZagKeySessionId, bizRequestContext.RequestInfo().SessionId)
				requestContext.DataMap().SetInt64(ctx, macro.ZagKeyMemberId, bizRequestContext.MemberId())
				requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryMessageId, bizRequestContext.RequestInfo().Message.MessageId)
				requestContext.DataMap().SetString(ctx, macro.ZagKeyQueryParentMessageId, "")

				return nil
			})

			if !testSyncInterface {
				finalEnd := lo.Must(context.DataMap().GetObjMap(ctx, macro.ZagKeyFinalEnd)).(chan bool)
				<-finalEnd
			}
			response := resp.(*proto.ChatResponse)
			tt.assertFunc(t, response, context, err)
		})
	}
}

func buildReq(query string, respMessageId string, testSyncInterface bool) *entities.RequestContext {
	bizTypePostfix := ""
	logicConfig := zhihaitu_chat_conf.LogicBizConfigMap
	if testSyncInterface {
		bizTypePostfix = "Api"
		logicConfig = zhihaitu_api_conf.LogicBizConfigMap
	}
	zhihaitu_resource.Init(graph_constant.ApiZhihaituChat)
	return entities.NewRequestContextForZhihaitu(&proto.ChatRequest{
		Info: &proto.RequestInfo{
			SessionId: "1234",
			Message: &proto.ChatMessage{
				MessageId:   uuid.New().String(),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: 0,
		},
		RespMessageId: respMessageId,
	}, "", nil, graph_constant.ApiZhihaituChat, bizTypePostfix, logicConfig)
}
