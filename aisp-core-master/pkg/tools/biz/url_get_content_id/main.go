package main

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/tealeg/xlsx"
)

func main() {
	// 打开批量跑 case 的 Excel 文件。Excel 有两列，第一列为 memberId，第二列为输入 query
	file, err := xlsx.OpenFile("zhihu.com-Performance-on-Search-2025-02-25.xlsx")
	if err != nil {
		fmt.Println(err)
		return
	}

	// 获取第2个工作表
	sheet := file.Sheets[1]

	contents := make([]model.Content, 0)

	// 遍历所有行
	for i, row := range sheet.Rows {
		if i == 0 {
			row.AddCell().SetValue("ContentId")
			row.AddCell().SetValue("ContentType")
			continue
		}

		linkType, subType, token := util.ParseLinkInfo(row.Cells[0].String())
		if linkType != util.LinkTypeZhihu || subType == "UNKNOWN" {
			continue
		}
		contents = append(contents, model.NewContentWithToken(token, subType))
	}

	contentCoreRpc := impl.DefaultContentCoreRPCImpl
	// 查询内容 url token
	contentResultMap := contentCoreRpc.BatchGetContent(context.TODO(), contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)

	// 遍历所有行
	for i, row := range sheet.Rows {
		if i == 0 {
			continue
		}

		linkType, subType, token := util.ParseLinkInfo(row.Cells[0].String())
		if linkType != util.LinkTypeZhihu || subType == "UNKNOWN" {
			continue
		}
		contentInfo := contentResultMap[model.NewContentWithToken(token, subType)]
		if contentInfo == nil {
			continue
		}

		fmt.Printf("ContentId: %s, ContentType: %s\n", contentInfo.GetOutID(), subType)
		row.AddCell().SetValue(contentInfo.GetOutID())
		row.AddCell().SetValue(subType)
	}

	// 保存文件
	err = file.Save(fmt.Sprintf("zhihu.com-Performance-on-Search-%s.xlsx", util.FormatTime2yyyyMMddHHmmss(time.Now())))
	if err != nil {
		fmt.Println(err)
		return
	}
}
