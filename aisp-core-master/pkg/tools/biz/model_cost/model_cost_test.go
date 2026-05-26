package main

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/xuri/excelize/v2"
)

// 导出每月模型成本。把cost接口返回的json转成excel
//
// 解析cost.json，转换成excel，一共三列，格式如下
// app_name	date	cost
// soar	2025/1/1	0
// soar	2025/1/2	0
// soar	2025/1/3	0

type CostData struct {
	Success bool   `json:"success"`
	Msg     string `json:"msg"`
	Data    []struct {
		Name   string `json:"name"`
		Points []struct {
			Timestamp int64 `json:"timestamp"`
			Value     struct {
				CentCount int `json:"cent_count"`
			} `json:"value"`
		} `json:"points"`
	} `json:"data"`
}

func TestModelCost(t *testing.T) {
	jsonFile, err := os.Open("cost.json")
	if err != nil {
		fmt.Println("Error opening file:", err)
		return
	}
	defer jsonFile.Close()

	var costData CostData
	if err := json.NewDecoder(jsonFile).Decode(&costData); err != nil {
		fmt.Println("Error decoding JSON:", err)
		return
	}

	// Create a new Excel file
	f := excelize.NewFile()
	defer f.Close()

	// Set headers
	headers := []string{"app_name", "date", "cost"}
	for i, header := range headers {
		cell := fmt.Sprintf("%c1", 'A'+i)
		f.SetCellValue("Sheet1", cell, header)
	}

	// Write data
	row := 2
	for _, app := range costData.Data {
		for _, point := range app.Points {
			// Convert timestamp to date string
			date := time.Unix(point.Timestamp, 0).Format("2006/1/2")

			// Write row data
			f.SetCellValue("Sheet1", fmt.Sprintf("A%d", row), app.Name)
			f.SetCellValue("Sheet1", fmt.Sprintf("B%d", row), date)
			f.SetCellValue("Sheet1", fmt.Sprintf("C%d", row), point.Value.CentCount)
			row++
		}
	}

	// Save the Excel file
	if err := f.SaveAs("cost.xlsx"); err != nil {
		fmt.Println("Error saving Excel file:", err)
		return
	}

	fmt.Println("Successfully converted cost.json to cost.xlsx")
}
