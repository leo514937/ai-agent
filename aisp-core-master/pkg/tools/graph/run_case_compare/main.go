package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	discover_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/tealeg/xlsx"
)

// go run pkg/tools/graph/run_case_compare/main.go
func main() {
	bizType := flag.Int64("b", 11, "bizType")
	modelType := flag.Int64("m", 1, "modelType")

	casesFileName := flag.String("case", "demo", "输入 case 文件名")
	confFileName := flag.String("conf", "demo", "输入 case 文件名")
	flag.Parse()

	chatType := proto.ChatType(*bizType)
	chatModel := proto.ChatModel(*modelType)

	nowTime := util.FormatTime2yyyyMMddHHmmss(time.Now())

	// 打开批量跑 case 的 Excel 文件。Excel 有两列，第一列为 memberId，第二列为输入 query
	file, err := xlsx.OpenFile(fmt.Sprintf("pkg/tools/graph/run_case_compare/cases/%s.xlsx", *casesFileName))
	if err != nil {
		fmt.Println(err)
		return
	}
	// 读取跑 case 的配置文件，用于表达跟线上对比的 exp 组的差异点
	caseConfig := readConfig(*confFileName)

	// 获取第一个工作表
	sheet := file.Sheets[0]

	resources.Init(graph_constant.ApiStreamChat)
	var outPutLog, _ = os.Create(fmt.Sprintf("process_log_%s.txt", nowTime))
	defer outPutLog.Close()
	if err != nil {
		fmt.Println(err)
		return
	}

	if err != nil {
		fmt.Println(err)
		return
	}
	txn, ctx := log.StartTransaction("tools_graph")
	defer txn.End(ctx)

	// 遍历所有行
	for i, row := range sheet.Rows {
		// 第一行是列名
		if i == 0 {
			row.AddCell().SetValue(fmt.Sprintf("[%s]answer", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]card", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]relateQuery", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]queryMerge", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]intention", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]originRecall", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]finalRecall", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]systemPrompt", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]userPrompt", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]security", "base"))
			row.AddCell().SetValue(fmt.Sprintf("[%s]tracing", "base"))
			for _, config := range caseConfig {
				row.AddCell().SetValue(fmt.Sprintf("[%s]answer", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]card", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]relateQuery", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]queryMerge", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]intention", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]originRecall", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]finalRecall", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]systemPrompt", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]userPrompt", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]security", config.ExpName))
				row.AddCell().SetValue(fmt.Sprintf("[%s]tracing", config.ExpName))
			}
			continue
		}

		// 获取 A 列单元格
		memberId := util.SafeString2Int64(row.Cells[0].String(), 0)
		query := row.Cells[1].String()
		if len(query) == 0 {
			continue
		}
		outPutLog.WriteString(fmt.Sprintf("\n\n===============>[%d]query:%s\n", i, query))

		// base执行
		requestContext := genBaseRequestContext(chatType, chatModel, memberId, query)
		// requestContext.AddAbParamValue("ai_rec_domain", "ac_search_entity", "1")
		// requestContext.SetAbGivenValue("ai_rec_domain", map[string]string{"ac_search_entity": "1"})
		baseResult := getAnswer(requestContext)
		row.AddCell().SetValue(baseResult.Answer)
		row.AddCell().SetValue(baseResult.Card)
		row.AddCell().SetValue(baseResult.RelateQuery)
		row.AddCell().SetValue(baseResult.QueryMerge)
		row.AddCell().SetValue(baseResult.Intention)
		row.AddCell().SetValue(baseResult.OriginRecall)
		row.AddCell().SetValue(baseResult.FinalRecall)
		row.AddCell().SetValue(baseResult.SystemPrompt)
		row.AddCell().SetValue(baseResult.UserPrompt)
		row.AddCell().SetValue(baseResult.Security)
		row.AddCell().SetValue(util.GetJSONIgnoreError(requestContext.GetMiddleProcess().GetSummary()))

		fmt.Printf("[%d] base question:%s,answer:%s", i, query, baseResult.Answer)
		outPutLog.WriteString(fmt.Sprintf("[%d] base answer:%s\n", i, baseResult.Answer))
		outPutLog.WriteString(fmt.Sprintf("[%d] base queryMerge:%s\n", i, baseResult.QueryMerge))
		outPutLog.WriteString(fmt.Sprintf("[%d] base systemPrompt:%s\n", i, baseResult.SystemPrompt))
		outPutLog.WriteString(fmt.Sprintf("[%d] base userPrompt:%s\n", i, baseResult.UserPrompt))

		for _, config := range caseConfig {
			// 根据配置部分重置 requestConfig
			expRequestContext := genExpRequestContext(requestContext, chatType, chatModel, memberId, query, config)
			// 计算结果写入
			expResult := getAnswer(expRequestContext)
			row.AddCell().SetValue(expResult.Answer)
			row.AddCell().SetValue(expResult.Card)
			row.AddCell().SetValue(expResult.RelateQuery)
			row.AddCell().SetValue(expResult.QueryMerge)
			row.AddCell().SetValue(expResult.Intention)
			row.AddCell().SetValue(expResult.OriginRecall)
			row.AddCell().SetValue(expResult.FinalRecall)
			row.AddCell().SetValue(expResult.SystemPrompt)
			row.AddCell().SetValue(expResult.UserPrompt)
			row.AddCell().SetValue(expResult.Security)
			row.AddCell().SetValue(util.GetJSONIgnoreError(expRequestContext.GetMiddleProcess().GetSummary()))

			fmt.Printf("[%d] %s question:%s,answer:%s", i, config.ExpName, query, expResult.Answer)
			outPutLog.WriteString(fmt.Sprintf("[%d] %s answer:%s\n", i, config.ExpName, expResult.Answer))
			outPutLog.WriteString(fmt.Sprintf("[%d] %s queryMerge:%s\n", i, config.ExpName, expResult.QueryMerge))
			outPutLog.WriteString(fmt.Sprintf("[%d] %s systemPrompt:%s\n", i, config.ExpName, expResult.SystemPrompt))
			outPutLog.WriteString(fmt.Sprintf("[%d] %s userPrompt:%s\n", i, config.ExpName, expResult.UserPrompt))
		}
	}

	// 保存文件
	err = file.Save(fmt.Sprintf("case_output_%s_%s.xlsx", chatType.String(), nowTime))
	if err != nil {
		fmt.Println(err)
		return
	}

}

func readConfig(confFileName string) []entities.CaseConf {
	var runCaseConfig []entities.CaseConf
	err := util.FileUnmarshal(fmt.Sprintf("pkg/tools/graph/run_case_compare/conf/%s.json", confFileName), &runCaseConfig)
	if err != nil {
		panic(fmt.Sprintf("read config error:%v", err))
	}
	return runCaseConfig
}

type caseResult struct {
	Answer       string
	Card         string
	RelateQuery  string
	QueryMerge   string
	Intention    string
	OriginRecall string
	FinalRecall  string
	SystemPrompt string
	UserPrompt   string
	Security     string
}

func getAnswer(requestContext *entities.RequestContext) caseResult {
	log.SetLevel(baselog.DebugLevel)

	txn, ctx := log.StartTransaction("tools_graph")
	defer txn.End(ctx)

	itemList, _, _, err := graph.RunGraph(ctx, requestContext, nil)

	if err != nil && len(itemList) == 0 {
		err = errors.New("empty response")
	}

	if len(itemList) == 0 {
		return caseResult{}
	}

	var systemPrompt, userPrompt string
	for _, prompt := range requestContext.Tracing().ProcessTracing.GetPrompt() {
		if prompt.Stage == proto.BusinessStage_GENERATION {
			if prompt.Description == "user prompt" {
				userPrompt = prompt.PromptContent
			}
			if prompt.Description == "system prompt" {
				systemPrompt = prompt.PromptContent
			}
		}
	}

	var intention string
	for _, tracing := range requestContext.Tracing().LogicTracing {
		if tracing.GetLogicName() == stream_chat_default_tab_conf.QueryRouterLogic {
			intention = tracing.GetLogicOutput()[0]
		}
	}

	lastResponse := requestContext.GetChatEventResponseHandler().TransitionSource(requestContext.GetChatEvent().GetAllEventData(), true, &chat_event.TransitionContext{
		IsHitCache: requestContext.IsHitCache(),
	})

	queryStrs := lo.Map(lastResponse.GetRelevantQueries(), func(item *proto.Query, index int) string {
		return item.GetQuery()
	})

	result := caseResult{
		Answer:       itemList[0].Text,
		Card:         util.GetJSONIgnoreError(lastResponse.GetCards()),
		RelateQuery:  util.GetJSONIgnoreError(queryStrs),
		QueryMerge:   requestContext.Tracing().ProcessTracing.GetQueryMerge(),
		Intention:    intention,
		OriginRecall: getOriginRecall(requestContext.GetRecallItems()),
		FinalRecall:  getRecallItem(requestContext.Tracing().ProcessTracing.GetFinalIndex()),
		SystemPrompt: systemPrompt,
		UserPrompt:   userPrompt,
		Security:     util.GetJSONIgnoreError(genSecurityText(requestContext.Tracing().ProcessTracing.GetSecurityTracing())),
	}

	return result
}

func getOriginRecall(items []*entities.Item) string {
	var result []string
	for _, item := range items {
		title := item.GetItemMeta().Title
		if title == "" && item.GetItemMeta().ParentContentInfo != nil {
			title = item.GetItemMeta().ParentContentInfo.GetTitle()
		}
		docId := item.ItemMeta.DocId
		if item.ItemMeta.DocType == content.DocType_Member {
			docId = item.ItemMeta.AuthorId
		}
		if title != "" {
			result = append(result, fmt.Sprintf("docId:%d,docType:%s,url:%s,title:%s,source:%s\n", docId, item.ItemMeta.DocType.String(),
				item.ItemMeta.Url, title, util.GetJSONIgnoreError(item.ItemMeta.RecallSourceInfo.KbSources)))
		} else {
			result = append(result, fmt.Sprintf("docId:%d,docType:%s,url:%s,text:%s,source:%s", docId, item.ItemMeta.DocType.String(),
				item.ItemMeta.Url, util.UnicodeSubstr(item.ItemMeta.Content, 0, 20), util.GetJSONIgnoreError(item.ItemMeta.RecallSourceInfo.KbSources)))
		}
	}
	return strings.Join(result, "\n")
}

func getRecallItem(recallItems []*proto.IndexTracing) string {
	var result []string
	for _, item := range recallItems {
		recallSourceInfo := &model.RecallSourceInfo{}
		recallSourceStr := item.GetRecallInfo()[0].GetRecallSource()
		json.Unmarshal([]byte(recallSourceStr), recallSourceInfo)
		if !item.GetRecallInfo()[0].IsUsed {
			continue
		}
		if item.GetTitle() != "" {
			result = append(result, fmt.Sprintf("docId:%d,docType:%d,url:%s,text:%s,source:%s\n%s", item.GetDocId(), item.GetDocType(),
				item.GetUrl(), util.UnicodeSubstr(item.GetText(), 0, 20), util.GetJSONIgnoreError(recallSourceInfo.KbSources), item.GetTitle()))
		} else {
			result = append(result, fmt.Sprintf("docId:%d,docType:%d,url:%s,text:%s,source:%s", item.GetDocId(), item.GetDocType(),
				item.GetUrl(), util.UnicodeSubstr(item.GetText(), 0, 20), util.GetJSONIgnoreError(recallSourceInfo.KbSources)))
		}
	}

	return strings.Join(result, "\n")
}

func genSecurityText(securityTracing []*proto.SecurityTracing) []string {
	var securityText = make([]string, 0)
	for _, each := range securityTracing {
		if each.GetDoSecurityReview() && !each.GetIsPass() {
			securityText = append(securityText, "安审失败")
		}
		if each.GetRedLine() != "" {
			securityText = append(securityText, "红线必答")
		}
		if each.GetFaq() != "" {
			securityText = append(securityText, "faq")
		}
	}

	return securityText
}

func genBaseRequestContext(chatType proto.ChatType, chatModel proto.ChatModel, memberId int64, query string) *entities.RequestContext {
	requestContext := genRequestContext(chatType, chatModel, memberId, query)
	requestContext.SetRunCaseConfig(entities.RunCaseConfig{
		IsOpen: true,
		IsBase: true,
	})
	return requestContext
}

func genRequestContext(chatType proto.ChatType, chatModel proto.ChatModel, memberId int64, query string) *entities.RequestContext {
	resources.Init(graph_constant.ApiStreamChat)
	request := &proto.ChatRequest{
		Type: chatType,
		Info: &proto.RequestInfo{
			SessionId: util.Int64String(int64(uuid.New().ID())),
			Message: &proto.ChatMessage{
				MessageId:   util.Int64String(int64(uuid.New().ID())),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: memberId,
		},
		RespMessageId: util.Int64String(int64(uuid.New().ID())),
		ChatStyle:     proto.ChatStyle_SIMPLE,
		Header: &proto.RequestHeader{
			ClientSource:  proto.ClientSource_ZHIHU_APP,
			TrafficSource: proto.TrafficSource_ai_search_general, //TrafficSource_ai_search_card_preview, // TrafficSource_zhida, // TrafficSource: proto.TrafficSource_zhida_pro,
			Version:       graph_constant.ZhiDaV2Version,
		},
		ChatModel:      chatModel,
		KnowledgeBases: []proto.KnowledgeBaseType{proto.KnowledgeBaseType_KBT_GLOBAL, proto.KnowledgeBaseType_KBT_ZHIHU, proto.KnowledgeBaseType_KBT_PAPER, proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE},
	}

	// 初始化 productContext
	productContext := discover_model.NewDiscoverTabContext(request)

	configMap, stageConfig, abParamMap := getConfigMap(chatType)
	var requestContext *entities.RequestContext
	if stageConfig != nil {
		requestContext = entities.NewRequestContextFromChatRequestAndStageConf(request, stageConfig)
	} else {
		requestContext = entities.NewRequestContextFromChatRequest(request, configMap)
	}
	requestContext.SetProductContext(productContext)
	requestContext.SetAbParamMap(abParamMap)

	return requestContext
}

func genExpRequestContext(baseRequestContext *entities.RequestContext, chatType proto.ChatType, chatModel proto.ChatModel, memberId int64, query string, config entities.CaseConf) *entities.RequestContext {
	requestContext := genRequestContext(chatType, chatModel, memberId, query)
	addAbGivenValue(requestContext, config.AbParamValue)
	requestContext.SetRunCaseConfig(entities.RunCaseConfig{
		IsOpen:      true,
		IsBase:      false,
		ExpName:     config.ExpName,
		LogicConfig: config.ConfigMap,
	})
	requestContext.SetProductContext(baseRequestContext.ProductContext())
	requestContext.SetIntention(requestContext.GetIntention())
	requestContext.SetHistoryDialogue(requestContext.GetHistoryDialogue())

	return requestContext
}

func addAbGivenValue(requestContext *entities.RequestContext, abParamValue map[string]map[string]string) {
	for k, v := range abParamValue {
		requestContext.SetAbGivenValue(k, v)
	}
}

func getConfigMap(chatType proto.ChatType) (map[string]map[string]string, stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item], map[zlab.SceneId][]zlab.ZlabValue) {
	//  优先匹配新版 获取当前图配置
	graphStageLogicConfig, isExistStageConfig := stage_handler.GetGraphStageConfig(stage_handler.BuildGraphLogicConfigName(graph_constant.ApiStreamChat, chatType.String()))
	if !isExistStageConfig {
		// 获取当前图配置
		graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, chatType.String()))
		if !isExist {
			return map[string]map[string]string{}, nil, map[zlab.SceneId][]zlab.ZlabValue{}
		}
		return graphLogicConfig.GetBizConfigMap(), nil, graphLogicConfig.GetAbParamMap()
	}
	return graphStageLogicConfig.GetDefaultBizConfigMap(), graphStageLogicConfig, graphStageLogicConfig.GetAbParamMap()
}
