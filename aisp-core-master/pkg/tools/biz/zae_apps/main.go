package main

import (
	"context"
	"fmt"
	"log"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/xuri/excelize/v2"
	// 根据你的项目结构调整导入路径
	// "your-project/dao"
	// "your-project/model"
)

func main() {
	ctx := context.Background()

	// 调用 ListAllApps 方法
	apps, err := dao.DefaultAppDAO.ListAllApps(ctx)
	if err != nil {
		log.Fatalf("获取应用列表失败: %v", err)
	}

	fmt.Printf("获取到 %d 条应用数据\n", len(apps))

	// 导出为 Excel
	if err := exportToExcel(apps); err != nil {
		log.Fatalf("导出 Excel 失败: %v", err)
	}

	fmt.Println("导出 Excel 成功！")
}

func exportToExcel(apps []*model.App) error {
	// 创建新的 Excel 文件
	f := excelize.NewFile()
	defer func() {
		if err := f.Close(); err != nil {
			fmt.Printf("关闭 Excel 文件失败: %v\n", err)
		}
	}()

	// 设置工作表名称
	sheetName := "Sheet1"

	// 设置表头（原始数据库字段名）
	f.SetCellValue(sheetName, "A1", "app_name")
	f.SetCellValue(sheetName, "B1", "owner_pinyin")
	f.SetCellValue(sheetName, "C1", "owner_department_name")

	// 填充数据
	for i, app := range apps {
		row := i + 2 // 从第2行开始（第1行是表头）
		f.SetCellValue(sheetName, fmt.Sprintf("A%d", row), app.Name)
		f.SetCellValue(sheetName, fmt.Sprintf("B%d", row), app.OwnerEmail)
		f.SetCellValue(sheetName, fmt.Sprintf("C%d", row), app.OwnerBizLineName)
	}

	// 生成文件名（带时间戳）
	filename := fmt.Sprintf("app_list_%s.xlsx", time.Now().Format("20060102_150405"))

	// 保存文件
	if err := f.SaveAs(filename); err != nil {
		return fmt.Errorf("保存文件失败: %w", err)
	}

	fmt.Printf("文件已保存为: %s\n", filename)
	return nil
}
