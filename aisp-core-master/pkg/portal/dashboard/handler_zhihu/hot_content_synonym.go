package handler_zhihu

import (
	"errors"
	"strconv"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	md "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	"github.com/samber/lo"
	"github.com/xuri/excelize/v2"
)

// HotContentProductSynonymHandler 好物100同义词
type HotContentProductSynonymHandler struct {
	rest.BaseHandler
	hotContentProductSynonymDAO dao.HotContentSynonymDAO
}

func NewHotContentSynonymHandler() rest.Handler {
	return &HotContentProductSynonymHandler{
		hotContentProductSynonymDAO: dao.DefaultHotContentSynonymDAO,
	}
}

// Get 好物100同义词列表
// @Param bayes_first_category_name 榜单类目
// @Param create_user_id 创建人
// @Param keyword 关键词
// @Return 200 {data: []HotContentProductSynonym}
func (h *HotContentProductSynonymHandler) Get(ctx *rest.Context) (rest.Response, error) {
	page := ctx.IntQueryArgument("page", 1)
	page--

	filterParams := &model.HotContentSynonymFilterParams{
		BayesFirstCategoryName: ctx.QueryArgument("bayes_first_category_name"),
		CreateUserId:           ctx.QueryArgument("create_user_id"),
		Keyword:                ctx.QueryArgument("keyword"),
		Page:                   page,
		PageSize:               ctx.IntQueryArgument("page_size", 10),
	}

	synonyms, err := h.hotContentProductSynonymDAO.ListSynonyms(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	count, err := h.hotContentProductSynonymDAO.GetTotalCount(ctx, filterParams)

	return ResponseSuccess(map[string]interface{}{
		"synonyms": synonyms,
		"total":    count,
	})
}

// Post 新增好物100同义词
// @Param bayes_first_category_name 榜单类目
// @Param take_effect_field 生效字段
// @Param keyword 关键词
// @Param synonyms 同义词
func (h *HotContentProductSynonymHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var req model.HotContentProductSynonym
	if err := ctx.JSONArgs(&req); err != nil {
		return nil, err
	}

	req.CreateUserId = md.GetUserId(ctx)
	req.StatusCode = int(model.StatusCodeOnline)

	if err := h.hotContentProductSynonymDAO.AddSynonyms(ctx, []*model.HotContentProductSynonym{&req}); err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}

type HotContentProductSingleSynonymHandler struct {
	rest.BaseHandler
	hotContentProductSynonymDAO dao.HotContentSynonymDAO
}

func NewHotContentSingleSynonymHandler() rest.Handler {
	return &HotContentProductSingleSynonymHandler{
		hotContentProductSynonymDAO: dao.DefaultHotContentSynonymDAO,
	}
}

// Patch updates a HotContentProductSynonym
// @Param bayes_first_category_name 榜单类目
// @Param take_effect_field 生效字段
// @Param keyword 关键词
// @Param synonyms 同义词
func (h *HotContentProductSingleSynonymHandler) Patch(ctx *rest.Context) (rest.Response, error) {
	var req model.HotContentProductSynonym
	if err := ctx.JSONArgs(&req); err != nil {
		return nil, err
	}

	req.Id, _ = strconv.ParseUint(ctx.URLParam("id"), 10, 64)

	if req.Id == 0 {
		return nil, errors.New("invalid ID")
	}

	req.UpdateUserId = md.GetUserId(ctx)

	if err := h.hotContentProductSynonymDAO.UpdateSynonym(ctx, &req); err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}

// HotContentProductSynonymUploadHandler handles the upload of HotContentProductSynonym via Excel file
type HotContentProductSynonymUploadHandler struct {
	rest.BaseHandler
	hotContentProductSynonymDAO dao.HotContentSynonymDAO
}

func NewHotContentSynonymUploadHandler() rest.Handler {
	return &HotContentProductSynonymUploadHandler{
		hotContentProductSynonymDAO: dao.DefaultHotContentSynonymDAO,
	}
}

// Post handles the upload of an Excel file and adds the data to the database
func (h *HotContentProductSynonymUploadHandler) Post(ctx *rest.Context) (rest.Response, error) {
	userId := md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请登录")
	}

	err := ctx.Request.ParseMultipartForm(32 << 20)
	if err != nil {
		return nil, err
	}

	files := lo.Flatten(lo.Values(ctx.Request.MultipartForm.File))

	if len(files) == 0 {
		return nil, errors.New("文件不存在")
	}

	file, err := files[0].Open()

	f, err := excelize.OpenReader(file)
	if err != nil {
		return nil, err
	}

	rows, err := f.GetRows("Sheet1")
	if err != nil {
		return nil, err
	}

	var synonyms []*model.HotContentProductSynonym
	for _, row := range rows[1:] { // Skip header row
		if len(row) < 4 {
			return nil, errors.New("列数不足")
		}
		synonym := &model.HotContentProductSynonym{
			BayesFirstCategoryName: row[0],
			TakeEffectField:        row[1],
			Keyword:                row[2],
			Synonyms:               row[3],
			CreateUserId:           userId,
			StatusCode:             int(model.StatusCodeOnline),
		}
		synonyms = append(synonyms, synonym)
	}

	if err := h.hotContentProductSynonymDAO.AddSynonyms(ctx, synonyms); err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}
