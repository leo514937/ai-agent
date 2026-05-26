package main

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/tealeg/xlsx"
)

// hive 表列数
const recordLen = 11

/**
脚本用于分析 tracing 日志
输入 csv 文件：inputCsvFileName
输出 excel 文件：outputExcelFileName
上述文件都放在根目录，例如 aisp-core/zue_query_6853467.csv
*/

const inputCsvFileName = "zue_query_6853467.csv"
const outputExcelFileName = "output_case01.xlsx"
const refuseStr = "拒答"

func main() {
	// 读取文件
	file, err := os.Open(inputCsvFileName)
	if err != nil {
		panic(err)
	}
	defer file.Close()
	// 创建 csv.Reader 对象
	reader := csv.NewReader(file)

	// 设置分隔符
	reader.Comma = ','

	normRecordCnt := 0
	abnormalRecordCnt := 0

	outputFile := xlsx.NewFile()
	sheet, err := outputFile.AddSheet("原始数据")
	if err != nil {
		fmt.Println(err)
		return
	}
	row := sheet.AddRow()
	row.AddCell().SetValue("memberId")
	row.AddCell().SetValue("messageId")
	row.AddCell().SetValue("用户输入")
	row.AddCell().SetValue("对话回答")
	row.AddCell().SetValue("相关问题")
	row.AddCell().SetValue("queryMerge")
	row.AddCell().SetValue("原始 doc 检索数量")
	row.AddCell().SetValue("最终 chunk 检索数量")
	row.AddCell().SetValue("faq")
	row.AddCell().SetValue("redLine")
	row.AddCell().SetValue("knowledgeEnhance")
	row.AddCell().SetValue("query安全")
	row.AddCell().SetValue("queryMerge安全")
	row.AddCell().SetValue("answer安全")
	row.AddCell().SetValue("相关问题安全")
	row.AddCell().SetValue("costMs")
	row.AddCell().SetValue("请求时间")

	// 读输入 csv 文件内容
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			fmt.Println("Error:", err)
			continue
		}
		// 校验 hive 表列数，与 logs.aisp_common_tracing 一一对应
		if len(record) != recordLen {
			abnormalRecordCnt++
			continue
		}
		normRecordCnt++

		memberId := record[0]
		messageId := record[1]
		requestInfoStr := record[4]
		responseInfoStr := record[5]
		processTracingStr := record[6]
		logicTracingStr := record[7]
		query := record[9]

		requestInfo := &proto.ChatRequest{}
		json.Unmarshal([]byte(requestInfoStr), requestInfo)
		responseInfo := &proto.ChatResponse{}
		json.Unmarshal([]byte(responseInfoStr), responseInfo)
		processTracing := &proto.ProcessTracing{}
		json.Unmarshal([]byte(processTracingStr), processTracing)
		logicTracing := &[]proto.LogicTracing{}
		json.Unmarshal([]byte(logicTracingStr), logicTracing)

		answer := responseInfo.GetMessage().GetText()
		var relevantQuery []string
		for _, i := range responseInfo.GetRelevantQueries() {
			relevantQuery = append(relevantQuery, i.GetQuery())
		}

		faq := ""
		knowledgeEnhance := ""
		isQueryPass := ""
		isQueryMergePass := ""
		isAnswerPass := ""
		isRelevantPass := ""
		redLine := ""
		isFinalPass := true
		for _, sec := range processTracing.GetSecurityTracing() {
			if sec.GetFaq() != "" {
				faq = sec.GetFaq()
			} else if sec.GetKnowledgeEnhance() != "" {
				knowledgeEnhance = sec.GetKnowledgeEnhance()
			} else if sec.RedLine != "" {
				redLine = sec.RedLine
			} else if sec.IsPass == false {
				isFinalPass = false
			}
		}

		for _, logic := range *logicTracing {
			if logic.GetLogicName() == "securityReview" {
				isQueryPass = getPassResult(logic.GetLogicOutput()[0])
			}
			if logic.GetLogicName() == "securityReviewM" {
				isQueryMergePass = getPassResult(logic.GetLogicOutput()[0])
			}
			if logic.GetLogicName() == "securityReviewOut" {
				isAnswerPass = getPassResult(logic.GetLogicOutput()[0])
			}
		}

		if isQueryPass != refuseStr && isQueryMergePass != refuseStr && isAnswerPass != refuseStr && isFinalPass == false {
			isRelevantPass = refuseStr
		}

		queryMerge := processTracing.GetQueryMerge()
		originRecallSize := len(processTracing.GetOriginalRecallItem())
		recallSize := len(processTracing.GetFinalIndex())

		reqMs := requestInfo.Info.GetMessage().GetTimestampMs() * 1000
		respMs := responseInfo.GetMessage().GetTimestampMs()
		costMs := respMs - reqMs

		tm := time.Unix(requestInfo.Info.GetMessage().GetTimestampMs(), 0)
		requestTime := tm.Format("2006-01-02 15:04:05")

		row = sheet.AddRow()
		row.AddCell().SetValue(memberId)
		row.AddCell().SetValue(messageId)
		row.AddCell().SetValue(query)
		row.AddCell().SetValue(answer)
		row.AddCell().SetValue(util.GetJSONIgnoreError(relevantQuery))
		row.AddCell().SetValue(queryMerge)
		row.AddCell().SetValue(originRecallSize)
		row.AddCell().SetValue(recallSize)
		row.AddCell().SetValue(faq)
		row.AddCell().SetValue(redLine)
		row.AddCell().SetValue(knowledgeEnhance)
		row.AddCell().SetValue(isQueryPass)
		row.AddCell().SetValue(isQueryMergePass)
		row.AddCell().SetValue(isAnswerPass)
		row.AddCell().SetValue(isRelevantPass)
		row.AddCell().SetValue(costMs)
		row.AddCell().SetValue(requestTime)

	}

	// 保存文件
	err = outputFile.Save(outputExcelFileName)
	if err != nil {
		fmt.Println(err)
		return
	}

	fmt.Printf("normRecordCnt: %d, abnormalRecordCnt: %d\n", normRecordCnt, abnormalRecordCnt)
}

func getPassResult(securityOutput string) string {
	available := strings.Split(securityOutput, ",")[0]
	st := strings.Split(available, ":")[1]
	if st == "true" {
		return "通过"
	}
	if st == "false" {
		return refuseStr
	}
	return ""
}
