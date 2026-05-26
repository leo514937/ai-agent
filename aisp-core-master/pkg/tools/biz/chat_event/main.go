package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"github.com/spf13/cast"
)

func main() {

	ctx := context.TODO()

	// 消费流式数据
	event := chat_event.NewChatEvent(ctx, readResponseData)

	// 异步执行 producer
	go func() {
		//// retrieval
		retrievalEventProducer := event.GetRetrievalEventProducer()
		for i := 0; i < 5; i++ {
			retrievalProducer := retrievalEventProducer.GetOrCreateRoundRetrievalProducer()
			retrievalProducer.GetTopicProducer().Send(&chat_event.TopicContent{
				Topic:         fmt.Sprintf("这是第%d个Topic", i+1),
				RetrievalType: chat_event.RtBrowse,
			}).Done()
			retrievalProducer.GetKeywordsProducer().Send([]string{fmt.Sprintf("这是第%d个词-1", i+1), fmt.Sprintf("这是第%d个词-2", i+1)}).Done()
			retrievalProducer.GetReferenceProducer().Send([]*proto.ChatCard{
				{
					CardContent: &proto.ChatCard_ZhidaRelevantSource{
						ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
							DocId:    "https://mp.weixin.qq.com/s/YHFan5cHoYLDCsFDnweRbA?version=4.1.32.91024&platform=mac",
							DocType:  proto.DocType_EXTERNAL_WEBPAGE,
							DocTitle: "AI Agent 发展趋势与架构演进",
						},
					},
				},
				{
					CardContent: &proto.ChatCard_ZhidaRelevantSource{
						ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
							DocId:   cast.ToString(403828055),
							DocType: proto.DocType_ANSWER,
						},
					},
				},
			}).Done()
			retrievalProducer.GetAnswerProducer().Send(&chat_event.AnswerContent{
				Content: fmt.Sprintf("这是%d个Topic的Summary", i+1),
			}).Done()
			retrievalProducer.ProducerDone()
		}
		retrievalEventProducer.Done()

		// ********************
		// keywords 如果开启 retrieval 阶段 这两块则默认失效，由retrieval自动控制输出 Keywords 和 refs
		keywordProducer := event.GetKeywordsProducer()
		keywordProducer.Send([]string{"张三", "李四"})
		keywordProducer.Send([]string{"王五", "赵六"})
		keywordProducer.Done()

		// ********************
		// reference 如果开启 retrieval 阶段 这两块则默认失效，由retrieval自动控制输出 Keywords 和 refs
		referenceProducer := event.GetReferenceProducer()
		referenceProducer.Send([]*proto.ChatCard{
			{
				CardContent: &proto.ChatCard_ZhidaRelevantSource{
					ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
						DocId:    "https://www.baidu.com",
						DocType:  proto.DocType_EXTERNAL_WEBPAGE,
						DocTitle: "百度一下，你就知道",
					},
				},
			},
			{
				CardContent: &proto.ChatCard_ZhidaRelevantSource{
					ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
						DocId:    "https://www.taobao.com",
						DocType:  proto.DocType_ANSWER,
						DocTitle: "淘宝 - 享受购物生活",
					},
				},
			},
		}).Done()

		// think
		thinkEventProducer := event.GetThinkProducer()
		think := "用户在问你好！模型需要给出相当有礼貌的回答，并表明自己的身份为知乎直答"
		thinkRune := []rune(think)
		thinkArr := make([]string, 0)
		for _, token := range thinkRune {
			thinkArr = append(thinkArr, string(token))
			thinkEventProducer.Send(strings.Join(thinkArr, ""))
			time.Sleep(50 * time.Millisecond)
		}
		thinkEventProducer.Done()

		// answer
		answerEventProducer := event.GetAnswerProducer()
		answer := "你好！我是知乎直答，很高兴帮助你，请问你有什么问题呢？"
		answerRune := []rune(answer)
		answerArr := make([]string, 0)
		for _, token := range answerRune {
			answerArr = append(answerArr, string(token))
			answerEventProducer.Send(&chat_event.AnswerContent{
				Content: strings.Join(answerArr, ""),
				Cites: []*chat_event.CiteSnippetDto{
					{
						DocIndex:    1,
						DocAbstract: "你好",
					},
				},
			})
			time.Sleep(50 * time.Millisecond)
		}
		answerEventProducer.Done()

		queriesEventProducer := event.GetRelateQueriesProducer()
		queriesEventProducer.Send([]*chat_event.RelateQueries{
			{
				QueryID:   "123",
				QueryText: "这是什么问题1",
			},
		})
		queriesEventProducer.Send([]*chat_event.RelateQueries{
			{
				QueryID:   "456",
				QueryText: "这是什么问题2",
			},
			{
				QueryID:   "789",
				QueryText: "这是什么问题3",
			},
		})
		queriesEventProducer.Done()

		time.Sleep(5 * time.Second)
		event.ProducerDone()
	}()

	event.AWait()

	fmt.Println()
	fmt.Println()
	fmt.Println()
	fmt.Println(formatJson(rr))
}

var rr *Response

func readResponseData(msg *chat_event.EventInfo) {
	r := &Response{
		CurrEventType:      msg.GetCurrEventType().String(),
		CurrEventTypeState: msg.GetCurrEventState().String(),
	}
	for _, eventType := range msg.GetHistoryEventType() {
		switch eventType {
		case chat_event.RetrievalEventType:
			retrievalResponses := make([]*RetrievalResponse, 0)
			for _, retrievalEventInfo := range msg.GetRetrieval() {
				r1 := &RetrievalResponse{
					CurrEventType:      retrievalEventInfo.GetCurrEventType().String(),
					CurrEventTypeState: retrievalEventInfo.GetCurrEventState().String(),
				}
				for _, et := range retrievalEventInfo.GetHistoryEventType() {
					switch et {
					case chat_event.TopicEventType:
						topicContent := retrievalEventInfo.GetTopic()
						r1.Topic = topicContent.Topic
						r1.RetrievalType = topicContent.RetrievalType.String()
					case chat_event.KeywordsEventType:
						r1.Keywords = retrievalEventInfo.GetKeywords()
					case chat_event.ReferenceEventType:
						refs := make([]string, 0)
						references := retrievalEventInfo.GetReferences()
						for _, card := range references {
							// 检查 oneof 字段类型
							switch x := card.GetCardContent().(type) {
							case *proto.ChatCard_ZhihuRelevantSource:
								refs = append(refs, util.GetJSONIgnoreError(x.ZhihuRelevantSource))
							case *proto.ChatCard_OtherRelevantSource:
								refs = append(refs, util.GetJSONIgnoreError(x.OtherRelevantSource))
							case *proto.ChatCard_ZhidaRelevantSource:
								refs = append(refs, util.GetJSONIgnoreError(x.ZhidaRelevantSource))
							default:
							}
						}
						r1.Refs = refs
					case chat_event.ThinkEventType:
						r1.Think = retrievalEventInfo.GetThinkContent()
					case chat_event.AnswerEventType:
						answerContent := ""
						if retrievalEventInfo.GetAnswerContent() != nil {
							answerContent = retrievalEventInfo.GetAnswerContent().Content
						}
						r1.Answer = answerContent
					}
				}
				retrievalResponses = append(retrievalResponses, r1)
			}
			r.Retrievals = retrievalResponses
		case chat_event.KeywordsEventType:
			r.Keywords = msg.GetKeywords()
		case chat_event.ReferenceEventType:
			refs := make([]string, 0)
			references := msg.GetReferences()
			for _, card := range references {
				// 检查 oneof 字段类型
				switch x := card.GetCardContent().(type) {
				case *proto.ChatCard_ZhihuRelevantSource:
					refs = append(refs, util.GetJSONIgnoreError(x.ZhihuRelevantSource))
				case *proto.ChatCard_OtherRelevantSource:
					refs = append(refs, util.GetJSONIgnoreError(x.OtherRelevantSource))
				case *proto.ChatCard_ZhidaRelevantSource:
					refs = append(refs, util.GetJSONIgnoreError(x.ZhidaRelevantSource))
				default:
				}
			}
			r.Refs = refs
		case chat_event.ThinkEventType:
			r.Think = msg.GetThinkContent()
		case chat_event.AnswerEventType:
			answerContent := ""
			if msg.GetAnswerContent() != nil {
				answerContent = msg.GetAnswerContent().Content
			}
			r.Answer = answerContent
		case chat_event.RelateQueriesEventType:
			queries := make([]string, 0)
			for _, q := range msg.GetRelateQueries() {
				queries = append(queries, q.QueryText)
			}
			r.RelateQueries = queries
		}
	}
	rr = r
	fmt.Printf("Processing =>  %+v \n", util.GetJSONIgnoreError(r))
}

func formatJson(obj any) string {
	// 格式化输出JSON（带缩进）
	jsonData, _ := json.MarshalIndent(obj, "", "  ")
	return string(jsonData)
}

type Response struct {
	CurrEventType      string
	CurrEventTypeState string
	Retrievals         []*RetrievalResponse
	Keywords           []string
	Refs               []string
	Think              string
	Answer             string
	RelateQueries      []string
}

type RetrievalResponse struct {
	CurrEventType      string
	CurrEventTypeState string
	RetrievalType      string
	Topic              string
	Keywords           []string
	Refs               []string
	Think              string
	Answer             string
}
