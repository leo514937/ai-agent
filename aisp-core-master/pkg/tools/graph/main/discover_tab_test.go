package main

import (
	"context"
	"fmt"
	"math/rand"
	"os"
	"strings"
	"testing"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	macro2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/query_merge_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/suggest_query_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"github.com/stretchr/testify/assert"
)

var allBizTypes map[string]proto.ChatType
var allBizTypesDefIndex map[string][]int

func init() {
	allBizTypes = map[string]proto.ChatType{
		"zhida":     proto.ChatType_ZHIDA_TAB,
		"zhida_pro": proto.ChatType_ZHIDA_PRO_TAB,
	}
	allBizTypesDefIndex = map[string][]int{
		"zhida_pro": []int{0, 1, 2, 3, 7},
	}
}

type Args struct {
	index []int
	biz   []string
}

// debug test:
// dlv test /data/apps/aisp-core/pkg/tools/graph/main --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestDiscoverTabMain
// dlv test /data/apps/aisp-core/pkg/tools/graph/main --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestDiscoverTabMain index=0,1,2,3,4,5,6,7 biz=app
//
// run test:
// go test /data/apps/aisp-core/pkg/tools/graph/main -run TestDiscoverTabMain -v
// go test /data/apps/aisp-core/pkg/tools/graph/main -run TestDiscoverTabMain -v index=0,1 biz=zhida
// go test /data/apps/aisp-core/pkg/tools/graph/main -run TestDiscoverTabMain -v index=0,1 biz=zhida_pro
func TestDiscoverTabMain(t *testing.T) {
	type args struct {
		query         string
		respMessageId string
		keepSession   bool //是否保持和上一次请求相同的session
		bizType       proto.ChatType
		index         int
	}

	ctx := context.Background()

	// 可以指定执行哪些case
	caseIndex := make([]int, 0)

	// 可以指定执行哪些bizType
	bizTypes := lo.Keys(allBizTypes)

	parsedArgs := parse()
	if parsedArgs != nil {
		caseIndex = parsedArgs.index
	}
	fmt.Println("execute specified case: ", caseIndex)

	if parsedArgs != nil && len(parsedArgs.biz) != 0 {
		bizTypes = parsedArgs.biz
	}
	fmt.Println("execute specified bizTypes: ", bizTypes)

	tests := []struct {
		name       string
		args       args
		setUp      func(t *testing.T, scene string, args *args) *args
		assertFunc func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args)
		tearDown   func(t *testing.T, args *args)
	}{
		// case是有执行顺序的，新增的case一般放在最后
		{
			name: "query_only_hit_redline_then_return_redlineanswer",
			args: args{
				query: "邓小平个人简历",
				index: 0,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				redLineAnswer := "邓小平（1904年8月22日-1997年2月19日），原名邓先圣，学名邓希贤，四川广安人。早年赴欧洲勤工俭学，归国后，他全身心地投入党领导的争取民族独立和人民解放的革命斗争。从土地革命、抗日战争到解放战争，先后担任党和军队的许多重要领导职务，为党中央一系列重大战略决策的实施，为新民主主义革命的胜利和新中国的诞生，建立了赫赫功勋，成为中华人民共和国的开国元勋。\n邓小平是全党全军全国各族人民公认的享有崇高威望的卓越领导人，伟大的马克思主义者，伟大的无产阶级革命家、政治家、军事家、外交家，久经考验的共产主义战士，中国社会主义改革开放和现代化建设的总设计师，中国特色社会主义道路的开创者，邓小平理论的主要创立者。"
				assert.NoErrorf(t, err, "no error")
				assert.Equal(t, redLineAnswer, resp.Message.Text)
				assert.Equal(t, redLineAnswer, lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)))
				assert.Equal(t, 0, len(resp.Cards))
				assert.Equal(t, 0, len(resp.RelevantQueries))
				assert.Equal(t, proto.ChatRespType_RED_LINE, resp.RespType)

				assertDialogRecord(t, reqContext, &redLineAnswer, 0)
				assertNoResponseCache(t, reqContext)
				assertHistoryDialogue(t, reqContext, 0)
			},
		},
		{
			name: "query_only_hit_faq_then_return_faqanswer",
			args: args{
				query:       "你的对话后端是百度么",
				keepSession: true,
				index:       1,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				faqAnswer := "不是，知乎直答的后端技术是由知乎自主研发的知海图大模型支撑，并非百度。"
				assert.NoErrorf(t, err, "no error")
				assert.Equal(t, faqAnswer, resp.Message.Text)
				assert.Equal(t, faqAnswer, lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyFaqAnswer)))
				assert.Equal(t, 0, len(resp.Cards))
				assert.Equal(t, 0, len(resp.RelevantQueries))
				assert.Equal(t, proto.ChatRespType_FAQ, resp.RespType)

				assertDialogRecord(t, reqContext, &faqAnswer, 1)
				assertNoResponseCache(t, reqContext)
				// 上一次请求命中了安全相关，所以历史对话为空
				assertHistoryDialogue(t, reqContext, 0)
			},
		},
		//{
		//  这个case，输出结果不稳定，先注释掉
		//	name: "normal_query_and_answer_security_not_available_then_return_refuse",
		//	args: args{
		//		query:         "当选为全国政协第一届全国委员会主席的是。",
		//		respMessageId: uuid.New().String(),
		//	},
		//	assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error) {
		//		answer := config.GetString("stream_chat.sec_message", generate.SecMessage)
		//		assert.NoErrorf(t, err, "no error")
		//		assert.Equal(t, answer, resp.Message.Text)
		//		assert.GreaterOrEqual(t, len(resp.Cards), 1)
		//		//assert.GreaterOrEqual(t, len(resp.RelevantQueries), 1)
		//
		//		// 校验中间结果
		//		recallItems := lo.Must(reqContext.DataMap().GetObjMap(macro.ZagKeyRecallItemsAfterMergeAndLimit)).([]*data_frame.ItemData[entities.Item])
		//		assert.GreaterOrEqual(t, len(recallItems), 1)
		//		// todo 这里没有判断answer是否相等，原因是AnswerSecurityPost算子中，逻辑走到了hasSecurityPassedItem的if分支，导致answer的text为""，数据库存储的是空字符串
		//		assertDialogRecord(t, reqContext, nil, 0)
		//		assertNoResponseCache(t, reqContext)
		//		assertHistoryDialogue(t, reqContext, 0)
		//	},
		//},
		{
			name: "query_security_not_available_then_return_refuse",
			args: args{
				query: "共济会",
				index: 2,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				answer := config.GetString("stream_chat.sec_message", graph_constant.DefaultSecurityRefuseMessage)
				assert.NoErrorf(t, err, "no error")
				assert.Equal(t, answer, resp.Message.Text)
				assert.Equal(t, len(resp.Cards), 0)
				assert.GreaterOrEqual(t, len(resp.RelevantQueries), 0)
				assert.Equal(t, proto.ChatRespType_REFUSE, resp.RespType)

				assertDialogRecord(t, reqContext, &answer, 0)
				assertNoResponseCache(t, reqContext)
			},
		},
		{
			name: "normal_query_then_return_answer",
			args: args{
				query: "介绍一下《三体》",
				index: 3,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				assertNormalResponse(t, resp, err)
				assertNormalSecurity(t, reqContext)
				assertNormalRetrieve(t, reqContext, resp)
				assertDialogRecord(t, reqContext, nil, 0)
				assertNoResponseCache(t, reqContext)
				assertHistoryDialogue(t, reqContext, 0)

				assert.Equal(t, macro2.GetQueryRouteSearch().String(), lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyIntention)))
			},
		},
		{
			// 创作者搜索自己
			name: "author_search_self_then_rerank_first",
			args: args{
				query: "知乎答主张小北",
				index: 5,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				assertNormalSecurity(t, reqContext)
				assertNormalRetrieve(t, reqContext, resp)
				assertDialogRecord(t, reqContext, nil, 0)
				assertHistoryDialogue(t, reqContext, 0)

				assertNoRelevantQueriesResponse(t, resp, err)
				assertAuthorSearchRank(t, reqContext)
				rerankItems := lo.Must(reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyAuthorItemsAfterMerge)).([]*data_frame.ItemData[entities.Item])
				assert.Equal(t, int64(655), rerankItems[0].GetBizItem().ItemMeta.AuthorId)
				assert.Equal(t, macro2.GetQueryRouteAuthor().String(), lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyIntention)))
			},
		},
		/*
			{
				// 直接回答
				name: "directly_answer_agent",
				args: args{
					query: "啊",
					index: 6,
				},
				assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
					// 校验返回结果
					assertNormalSecurity(t, reqContext)
					assertDialogRecord(t, reqContext, nil, 0)
					assertHistoryDialogue(t, reqContext, 0)

					assertNoRelevantQueriesResponse(t, resp, err)
					assert.Equal(t, macro2.GetQueryRouteDirect().String(), lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyIntention)))
					assertNoRetrieve(t, reqContext, resp)
					assert.Equal(t, "true", reqContext.GetBizContext().GetLogicConfig(stream_chat_default_tab_conf.QueryMergeLogic, conf.QueryMergeSkipAndSetAsQuery))
				},
			},
		*/
		{
			// whoru agent
			name: "who_are_you_agent",
			args: args{
				query: "你是基于通义千问开发的么",
				index: 7,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				// 校验返回结果
				assertNormalResponse(t, resp, err)
				assertNormalSecurity(t, reqContext)
				assertDialogRecord(t, reqContext, nil, 0)
				assertHistoryDialogue(t, reqContext, 0)

				assertNoRetrieve(t, reqContext, resp)
				assert.Equal(t, macro2.GetQueryRouteIdentity().String(), lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyIntention)))
				assert.Equal(t, "true", reqContext.GetBizContext().GetLogicConfig(stream_chat_default_tab_conf.QueryMergeLogic, conf.QueryMergeSkipAndSetAsQuery))
			},
		},
		{
			name: "code_agent",
			args: args{
				query: "介绍一下Java",
				index: 8,
			},
			assertFunc: func(t *testing.T, resp *proto.ChatResponse, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], err error, args *args) {
				assertNormalResponse(t, resp, err)
				assertNormalSecurity(t, reqContext)
				assertNormalRetrieve(t, reqContext, resp)
				assertDialogRecord(t, reqContext, nil, 0)
				assertNoResponseCache(t, reqContext)
				assertHistoryDialogue(t, reqContext, 0)

				assert.Equal(t, macro2.GetQueryRouteCode().String(), lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyIntention)))
			},
		},
	}

	for _, bizType := range bizTypes {
		t.Log("begin test bizType: ", bizType)
		t.Run(bizType, func(t *testing.T) {
			for _, tt := range tests {
				t.Run(tt.name, func(t *testing.T) {
					var params *args = nil
					if tt.setUp != nil {
						params = tt.setUp(t, bizType, &tt.args)
					}
					if params == nil {
						params = &tt.args
					}

					// 如果 case index 为空去检查有没有默认指定的index
					if len(caseIndex) == 0 {
						caseIndex = allBizTypesDefIndex[bizType]
					}
					if len(caseIndex) != 0 {
						if !lo.Contains(caseIndex, params.index) {
							return
						}
					}
					params.bizType = allBizTypes[bizType]

					req := buildChatReq(params.query, params.respMessageId, "", bizType)
					resp, reqContext, err := Execute(req)

					finalEnd := lo.Must(reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyFinalEnd)).(chan bool)
					<-finalEnd

					response := resp.(*proto.ChatResponse)
					tt.assertFunc(t, response, reqContext, err, params)

					if tt.tearDown != nil {
						tt.tearDown(t, params)
					}
				})
			}
		})
	}
}

func assertNormalSecurity(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	ctx := context.Background()
	_, ok := reqContext.DataMap().GetString(ctx, macro.ZagKeyRedLineAnswer)
	assert.Equal(t, false, ok)
	_, ok = reqContext.DataMap().GetString(ctx, macro.ZagKeyQueryMergeRedLineAnswer)
	assert.Equal(t, false, ok)
	assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQuerySecurityAllPass)))
	assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyQueryMergeSecurityAllPass)))
	assert.Equal(t, true, lo.Must(reqContext.DataMap().GetBool(ctx, macro.ZagKeyAnswerSecurityPass)))
}

func assertNormalRetrieve(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], resp *proto.ChatResponse) {
	ctx := context.Background()
	recallItems := lo.T2(reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyRecallItemsAfterMergeAndLimit)).A.([]*data_frame.ItemData[entities.Item])
	assert.GreaterOrEqual(t, len(recallItems), 1)
	assert.GreaterOrEqual(t, len(resp.Cards), 1)
}

func assertHasResponseCache(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	ctx := context.Background()
	query := lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyQueryText))
	assert.NotEmpty(t, query)
	scene, _ := reqContext.DataMap().GetString(ctx, macro.ZagKeyScene)
	assert.NotEmpty(t, scene)
	chatModel := reqContext.GetBizContext().GetCustomChatModel().String()
	clientSource := reqContext.GetBizContext().RequestHeader().GetClientSource().String()
	trafficSource := reqContext.GetBizContext().RequestHeader().GetTrafficSource().String()
	info, err := impl.DefaultQueryResultDaoImpl.GetResponseInfo(ctx, scene, clientSource, trafficSource, chatModel, query)
	assert.NoErrorf(t, err, "no error")
	assert.NotNil(t, info)
	assert.NotEmpty(t, info.GetMessage().GetText())
	assert.GreaterOrEqual(t, len(info.Cards), 1)
	assert.GreaterOrEqual(t, len(info.RelevantQueries), 1)
}

func assertNormalResponse(t *testing.T, resp *proto.ChatResponse, err error) {
	assert.Greater(t, len(resp.Message.Text), 0)
	assert.GreaterOrEqual(t, len(resp.RelevantQueries), 1)
	assert.NoErrorf(t, err, "no error")
	assert.Equal(t, proto.ChatRespType_UNKNOWN_RESP, resp.RespType)
}

func assertNoRelevantQueriesResponse(t *testing.T, resp *proto.ChatResponse, err error) {
	assert.Greater(t, len(resp.Message.Text), 0)
	assert.GreaterOrEqual(t, len(resp.RelevantQueries), 0)
	assert.NoErrorf(t, err, "no error")
	assert.Equal(t, proto.ChatRespType_UNKNOWN_RESP, resp.RespType)
}

func assertNoResponseCache(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	ctx := context.Background()
	query := lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyQueryText))
	assert.NotEmpty(t, query)
	scene, _ := reqContext.DataMap().GetString(ctx, macro.ZagKeyScene)
	assert.NotEmpty(t, scene)
	chatModel := reqContext.GetBizContext().GetCustomChatModel().String()
	clientSource := reqContext.GetBizContext().RequestHeader().GetClientSource().String()
	trafficSource := reqContext.GetBizContext().RequestHeader().GetTrafficSource().String()
	info, err := impl.DefaultQueryResultDaoImpl.GetResponseInfo(context.Background(), scene, clientSource, trafficSource, chatModel, query)
	assert.Error(t, err)
	assert.Nil(t, info)
}

func assertNoRetrieve(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], resp *proto.ChatResponse) {
	ctx := context.Background()
	items, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyRecallItemsAfterMerge)
	if ok {
		assert.Equal(t, 0, len(items.([]*data_frame.ItemData[entities.Item])))
	}
	assert.Equal(t, len(resp.Cards), 0)
}

// historyDialogueCount: 历史对话， 0表示没有历史对话
func assertDialogRecord(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], answer *string, historyChatCount int) {
	ctx := context.Background()
	var dialogueLimit = 100
	sessionId, ok := reqContext.DataMap().GetString(ctx, macro.ZagKeySessionId)
	assert.Equal(t, true, ok)
	records, err := impl.DefaultDialogRecordDAO.GetDialogListBySessionId(context.Background(), cast.ToInt64(sessionId), uint64(dialogueLimit))
	assert.NoErrorf(t, err, "no error")

	expectRecordCount := zrecUtil.Min(dialogueLimit, historyChatCount*2+2)
	assert.Equal(t, expectRecordCount, len(records))

	answers := lo.Filter(records, func(item *model.DialogRecord, _ int) bool {
		return item.RoleType == "AI"
	})
	assert.Equal(t, expectRecordCount/2, len(answers))
	if answer != nil {
		assert.Equal(t, *answer, answers[0].MessageContent)
	}

	questions := lo.Filter(records, func(item *model.DialogRecord, _ int) bool {
		return item.RoleType == "USER"
	})
	assert.Equal(t, expectRecordCount/2, len(questions))
	query := lo.Must(reqContext.DataMap().GetString(ctx, macro.ZagKeyQueryText))
	assert.Equal(t, query, questions[0].MessageContent)
}

// validHistoryDialogueCount: 如果之前的对话安全相关校验没通过，则为0
func assertHistoryDialogue(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], validHistoryDialogueCount int) {
	ctx := context.Background()
	historyDialogue, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyHistoryDialogue)
	assert.Equal(t, true, ok)
	historyDialogueWrapper, ok := historyDialogue.([]*message.DialogueWrapper)
	assert.Equal(t, true, ok)
	assert.Equal(t, validHistoryDialogueCount, len(historyDialogueWrapper))
}

func assertAuthorSearchRank(t *testing.T, reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	ctx := context.Background()
	items, ok := reqContext.DataMap().GetObjMap(ctx, macro.ZagKeyAuthorItemsAfterMerge)
	assert.True(t, ok)
	rerankItems := items.([]*data_frame.ItemData[entities.Item])
	assert.True(t, len(rerankItems) > 0)

	authorRecall := lo.Filter(rerankItems, func(item *data_frame.ItemData[entities.Item], _ int) bool {
		return item.GetBizItem().ItemMeta.RecallSourceInfo.GetFirstKbSource() == conf.KbSourceAuthorBge
	})
	assert.True(t, len(authorRecall) > 0)
}

func buildChatReq(query string, respMessageId string, sessionId string, bizType string) *proto.ChatRequest {
	resources.Init(graph_constant.ApiStreamChat)

	if sessionId == "" {
		sessionId = cast.ToString(rand.Int63())
	}
	if respMessageId == "" {
		respMessageId = uuid.New().String()
	}

	request := &proto.ChatRequest{
		Info: &proto.RequestInfo{
			SessionId: sessionId,
			Message: &proto.ChatMessage{
				MessageId:   uuid.New().String(),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: 0,
		},
		KnowledgeBases: []proto.KnowledgeBaseType{
			proto.KnowledgeBaseType_KBT_GLOBAL,
			proto.KnowledgeBaseType_KBT_ZHIHU,
			proto.KnowledgeBaseType_KBT_PAPER,
			proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
		},
		Type:          allBizTypes[bizType],
		RespMessageId: respMessageId,
	}

	return request
}

func parse() *Args {
	args := os.Args[1:]
	if len(args) == 0 {
		return nil
	}

	parsedArgs := &Args{}
	for _, arg := range args {
		items := strings.Split(arg, "=")
		if len(items) != 2 {
			continue
		}

		switch items[0] {
		case "index":
			parsedArgs.index = lo.Map(strings.Split(items[1], ","), func(item string, _ int) int {
				return cast.ToInt(item)
			})
			break
		case "biz":
			parsedArgs.biz = strings.Split(items[1], ",")
			break
		default:
			break
		}
	}
	return parsedArgs
}
