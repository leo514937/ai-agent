package handler_zhihu

import (
	"bytes"
	"errors"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	md "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	"github.com/xuri/excelize/v2"
)

// HotContentProductHandler 好物100榜单
type HotContentProductHandler struct {
	rest.BaseHandler
	hotContentProductDAO dao.HotContentProductDAO
}

func NewHotContentProductHandler() rest.Handler {
	return &HotContentProductHandler{
		hotContentProductDAO: impl.DefaultHotContentProductDAO,
	}
}

func buildFilterParams(ctx *rest.Context) *model.HotContentFilterParams {
	page := ctx.IntQueryArgument("page", 1)
	// 前端page从1开始
	page -= 1
	pageSize := ctx.IntQueryArgument("page_size", 10)
	bayesFirstCategoryName := strings.TrimSpace(ctx.QueryArgument("bayes_first_category_name"))
	firstLevelTop := strings.TrimSpace(ctx.QueryArgument("first_level_top"))
	secondLevelTop := strings.TrimSpace(ctx.QueryArgument("second_level_top"))
	entityName := strings.TrimSpace(ctx.QueryArgument("entity_name"))
	entityScoreLowerBound := ctx.Int64QueryArgument("entity_score_lower_bound", 0)
	entityScoreUpperBound := ctx.Int64QueryArgument("entity_score_upper_bound", 0)
	dateStart := strings.TrimSpace(ctx.QueryArgument("date_start"))
	dateEnd := strings.TrimSpace(ctx.QueryArgument("date_end"))

	return &model.HotContentFilterParams{
		Page:                   page,
		PageSize:               pageSize,
		BayesFirstCategoryName: bayesFirstCategoryName,
		FirstLevelTop:          firstLevelTop,
		SecondLevelTop:         secondLevelTop,
		EntityName:             entityName,
		EntityScoreLowerBound:  entityScoreLowerBound,
		EntityScoreUpperBound:  entityScoreUpperBound,
		PDateStart:             dateStart,
		PDateEnd:               dateEnd,
	}
}

func (h *HotContentProductHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	params := buildFilterParams(ctx)
	products, cnt, pdate, err := h.hotContentProductDAO.FindByFilterParams(ctx, params)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(map[string]interface{}{
		"products": products,
		"total":    cnt,
		"pdate":    pdate,
	})
}

// HotContentProductTrendHandler 好物100趋势
type HotContentProductTrendHandler struct {
	rest.BaseHandler
	hotContentProductDAO dao.HotContentProductDAO
}

func NewHotContentProductTrendHandler() rest.Handler {
	return &HotContentProductTrendHandler{
		hotContentProductDAO: impl.DefaultHotContentProductDAO,
	}
}

func (h *HotContentProductTrendHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	params := buildFilterParams(ctx)

	if params.PDateStart == "" || params.PDateEnd == "" {
		return nil, errors.New("日期范围不能为空")
	}

	products, err := h.hotContentProductDAO.FindTrendByFilterParams(ctx, params)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(products)
}

// HotContentProductDownloadHandler 好物100详情导出
type HotContentProductDownloadHandler struct {
	rest.BaseHandler
	hotContentProductDAO dao.HotContentProductDAO
}

func NewHotContentProductDownloadHandler() rest.Handler {
	return &HotContentProductDownloadHandler{
		hotContentProductDAO: impl.DefaultHotContentProductDAO,
	}
}

func (h *HotContentProductDownloadHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	pageSize := 999
	page := 0
	allProducts := make([]*model.HotContentProducts, 0)
	var params *model.HotContentFilterParams
	var dataDate string
	for {
		params = buildFilterParams(ctx)
		params.PageSize = pageSize
		params.Page = page
		products, _, pdate, err := h.hotContentProductDAO.FindByFilterParams(ctx, params)

		if err != nil {
			return nil, err
		}

		if dataDate == "" {
			dataDate = pdate
		}

		if len(products) == 0 {
			break
		}
		allProducts = append(allProducts, products...)
		page++
	}

	f := excelize.NewFile()
	// 创建一个工作簿
	index, err := f.NewSheet("Sheet1")
	if err != nil {
		return nil, err
	}

	// 设置单元格的值
	util.WriteCell(f, 1, "A", "类目")
	util.WriteCell(f, 1, "B", "一级")
	util.WriteCell(f, 1, "C", "二级")
	util.WriteCell(f, 1, "D", "实体名称")
	util.WriteCell(f, 1, "E", "热度分值")
	util.WriteCell(f, 1, "F", "热议评论")

	for i, product := range allProducts {
		util.WriteCell(f, i+2, "A", product.BayesFirstCategoryName)
		util.WriteCell(f, i+2, "B", product.FirstLevelTop)
		util.WriteCell(f, i+2, "C", product.SecondLevelTop)
		util.WriteCell(f, i+2, "D", product.EntityName)
		util.WriteCell(f, i+2, "E", product.EntityScore)
		util.WriteCell(f, i+2, "F", product.EvaluationListJson)
	}

	// 设置默认打开的工作簿
	f.SetActiveSheet(index)

	// 设置文件名
	fileName := fmt.Sprintf("%s热度榜_%s", params.BayesFirstCategoryName, dataDate)
	if params.FirstLevelTop != "" {
		fileName += fmt.Sprintf("/%s", params.FirstLevelTop)
	}
	if params.SecondLevelTop != "" {
		fileName += fmt.Sprintf("/%s", params.SecondLevelTop)
	}
	if params.EntityName != "" {
		fileName += fmt.Sprintf("/%s", params.EntityName)
	}
	fileName += ".xlsx"

	// 设置响应头
	ctx.Writer.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	ctx.Writer.Header().Set("Content-Disposition", "attachment; filename="+fileName)

	// 将Excel文件保存到内存中
	buffer := new(bytes.Buffer)
	if err := f.Write(buffer); err != nil {
		return nil, err
	}

	// 将Excel文件内容写入HTTP响应
	_, err = ctx.Writer.Write(buffer.Bytes())
	if err != nil {
		return nil, err
	}

	return EmptyResult, nil
}
