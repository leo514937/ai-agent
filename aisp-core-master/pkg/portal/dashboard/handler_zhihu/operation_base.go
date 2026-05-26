package handler_zhihu

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	md "git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard/middleware"
	util2 "git.in.zhihu.com/zrec/zrec-utils/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"github.com/xuri/excelize/v2"
)

// 接口文档：https://zhihu.kdocs.cn/l/cph0aHPGebxP
// 运营库，包括知识库 & 静态库

var operationBaseService operation_base.OperationBaseManagementService
var chatEventChainLinkTraceDao dao.ChatEventChainLinkTraceDao

func init() {
	operationBaseService = operation_base.DefaultOperationBaseManagementService
	chatEventChainLinkTraceDao = daoImpl.NewChatEventChainLinkTraceDao()
}

type OperationBaseAuthorityHandler struct {
	rest.BaseHandler
}

func NewOperationBaseAuthorityHandler() rest.Handler {
	return &OperationBaseAuthorityHandler{}
}

func (k *OperationBaseAuthorityHandler) Get(ctx *rest.Context) (rest.Response, error) {
	var userId = md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请先登录")
	}

	authority, err := operationBaseService.GetAuthority(ctx, userId)
	if err != nil {
		log.Error(ctx, fmt.Sprintf("GetAuthority error. userId=%s", userId))
		return nil, err
	}
	return ResponseSuccess(authority)
}

type OperationBaseScenesHandler struct {
	rest.BaseHandler
}

func NewOperationBaseScenesHandler() rest.Handler {
	return &OperationBaseScenesHandler{}
}

func (k *OperationBaseScenesHandler) Get(ctx *rest.Context) (rest.Response, error) {
	var userId = md.GetUserId(ctx)
	if userId == "" {
		return nil, errors.New("请先登录")
	}

	scenes, err := operationBaseService.GetScenes(ctx)
	if err != nil {
		log.Error(ctx, fmt.Sprintf("GetScenes error. userId=%s", userId))
		return nil, err
	}
	return ResponseSuccess(scenes)
}

func checkAuthority(ctx *rest.Context, leastAuthority int) error {
	var userId = md.GetUserId(ctx)
	if userId == "" {
		return errors.New("请先登录")
	}

	authority, err := operationBaseService.GetAuthority(ctx, userId)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("GetAuthority error. userId=%s", userId))
		return err
	}

	if authority.Authority < leastAuthority {
		return errors.New("没有权限")
	} else {
		return nil
	}
}

// ---------知识库（aka 知识增强）相关begin ------------

type KnowledgeBaseListHandler struct {
	rest.BaseHandler
}

func NewKnowledgeBaseListHandler() rest.Handler {
	return &KnowledgeBaseListHandler{}
}

const (
	filterTimeLayout = "20060102"
)

// parseFilterTime 入参格式：yyyyMMdd-yyyyMMdd，或yyyyMMddHHmmss-yyyyMMddHHmmss。返回两个时间
func parseFilterTime(timeStr string) (*time.Time, *time.Time, error) {
	if timeStr != "" {
		timePair := strings.Split(timeStr, "-")
		if len(timePair) != 2 {
			return nil, nil, errors.New("时间格式错误")
		}
		if len(timePair[0]) == 8 {
			beginTime, err := util2.ToTimeInFormatLocal(timePair[0], filterTimeLayout)
			if err != nil {
				return nil, nil, err
			}
			endTime, err := util2.ToTimeInFormatLocal(timePair[1], filterTimeLayout)
			if err != nil {
				return nil, nil, err
			}
			endTime = endTime.Add(time.Hour * 24)
			return &beginTime, &endTime, nil
		}
		if len(timePair[0]) == 14 {
			beginTime, err := util2.ToTimeInFormatLocal(timePair[0], util.DateTimeFormat)
			if err != nil {
				return nil, nil, err
			}
			endTime, err := util2.ToTimeInFormatLocal(timePair[1], util.DateTimeFormat)
			if err != nil {
				return nil, nil, err
			}
			return &beginTime, &endTime, nil
		}

	}

	return nil, nil, nil
}

func buildCommonFilterParams(ctx *rest.Context) (*model.FilterParams, error) {
	page := ctx.IntQueryArgument("page", 1)
	// 前端page从1开始
	page -= 1
	pageSize := ctx.IntQueryArgument("pageSize", 10)
	query := ctx.QueryArgumentWithFallback("query", "")
	status := ctx.IntQueryArgument("status", 0)
	createdAt := ctx.QueryArgumentWithFallback("created_at", "")
	updatedAt := ctx.QueryArgumentWithFallback("updated_at", "")
	createUserId := ctx.QueryArgumentWithFallback("create_user_id", "")
	updateUserId := ctx.QueryArgumentWithFallback("update_user_id", "")
	createdAtBegin, createdAtEnd, err := parseFilterTime(createdAt)
	if err != nil {
		return nil, err
	}
	updatedAtBegin, updatedAtEnd, err := parseFilterTime(updatedAt)
	if err != nil {
		return nil, err
	}

	return &model.FilterParams{
		Page:           page,
		PageSize:       pageSize,
		Query:          query,
		Status:         status,
		CreatedAtBegin: createdAtBegin,
		CreatedAtEnd:   createdAtEnd,
		CreateUserId:   createUserId,
		UpdatedAtBegin: updatedAtBegin,
		UpdatedAtEnd:   updatedAtEnd,
		UpdateUserId:   updateUserId,
	}, nil
}

func (k *KnowledgeBaseListHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	knowledgeBases, totalCount, err := operationBaseService.ListKnowledgeBase(ctx, filterParams)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("ListKnowledgeBase error. filterParams=%s", lo.Must(json.Marshal(filterParams))))
		return nil, err
	}

	return ResponsePagingSuccess(knowledgeBases, "", totalCount)
}

type KnowledgeBaseUploadHandler struct {
	rest.BaseHandler
}

func NewKnowledgeBaseUploadHandler() rest.Handler {
	return &KnowledgeBaseUploadHandler{}
}

func parseKnowledgeBaseExcel(file *excelize.File, userId string) ([]*model.KnowledgeBaseV2, error) {
	rows, err := file.GetRows("Sheet1")
	if err != nil {
		return nil, err
	}

	var knowledgeBases []*model.KnowledgeBaseV2
	for i, row := range rows {
		// 第0行是excel header
		if i == 0 {
			if !strings.Contains(row[0], "关键词") || row[1] != "知识内容" {
				return nil, errors.New("文件格式不对，请使用「知识库」模板")
			}
			continue
		}

		if len(row[0]) == 0 || len(rows[1]) == 0 {
			continue
		}

		knowledgeBase := model.KnowledgeBaseV2{
			KeyWords:         strings.TrimSpace(row[0]),
			KnowledgeContent: strings.TrimSpace(row[1]),
			CreateUserId:     userId,
		}
		knowledgeBases = append(knowledgeBases, &knowledgeBase)
	}
	return knowledgeBases, nil
}

func (k *KnowledgeBaseUploadHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	var userId = md.GetUserId(ctx)

	err = ctx.Request.ParseMultipartForm(32 << 20)
	if err != nil {
		return nil, err
	}

	files := lo.Flatten(lo.Values(ctx.Request.MultipartForm.File))

	if len(files) == 0 {
		return nil, errors.New("文件不存在")
	}

	file, err := files[0].Open()
	excelFile, err := excelize.OpenReader(file)
	if err != nil {
		// 处理错误
		return nil, err
	}

	knowledgeBases, err := parseKnowledgeBaseExcel(excelFile, userId)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("parseKnowledgeBaseExcel error. userId=%s", userId))
		return nil, err
	}

	if len(knowledgeBases) == 0 {
		return BaseResponse{
			Success: false,
			Msg:     "文件为空",
			Data:    nil,
		}, nil
	}

	knowledgeBasesResult, err := operationBaseService.AddKnowledgeBase(ctx, knowledgeBases)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(knowledgeBasesResult)
}

type KnowledgeBaseAddOrUpdateHandler struct {
	rest.BaseHandler
}

func NewKnowledgeBaseAddOrUpdateHandler() rest.Handler {
	return &KnowledgeBaseAddOrUpdateHandler{}
}

type KnowledgeBaseV2DTO struct {
	Keywords string `json:"keywords"`
	Content  string `json:"content"`
	Status   byte   `json:"status"`
}

func (k *KnowledgeBaseAddOrUpdateHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	var userId = md.GetUserId(ctx)

	var knowledgeBaseDTO *KnowledgeBaseV2DTO
	err = ctx.JSONArgs(&knowledgeBaseDTO)
	if err != nil {
		return nil, err
	}

	knowledgeBase := model.KnowledgeBaseV2{
		KeyWords:         knowledgeBaseDTO.Keywords,
		KnowledgeContent: knowledgeBaseDTO.Content,
		StatusCode:       knowledgeBaseDTO.Status,
	}

	if strings.Contains(ctx.Request.RequestURI, "update") {
		idStr := ctx.URLParam("id")
		if idStr == "" {
			return nil, errors.New("url错误, 没有id")
		}
		id, err := strconv.Atoi(idStr)
		if err != nil {
			return nil, err
		}
		knowledgeBase.Id = int64(id)
		knowledgeBase.UpdateUserId = userId

		knowledgeBaseResult, err := operationBaseService.UpdateKnowledgeBase(ctx, &knowledgeBase)
		if err != nil {
			return nil, err
		}
		return ResponseSuccess(knowledgeBaseResult)
	} else {
		knowledgeBase.CreateUserId = userId

		var knowledgeBases = make([]*model.KnowledgeBaseV2, 0, 1)
		knowledgeBases = append(knowledgeBases, &knowledgeBase)

		knowledgeBasesResult, err := operationBaseService.AddKnowledgeBase(ctx, knowledgeBases)
		if err != nil {
			return nil, err
		}
		return ResponseSuccess(knowledgeBasesResult)
	}
}

// ---------知识库（aka 知识增强）相关end ------------

// ---------静态库（aka 红线必答）相关begin ------------

type StaticBaseListHandler struct {
	rest.BaseHandler
}

func NewStaticBaseListHandler() rest.Handler {
	return &StaticBaseListHandler{}
}

func (k *StaticBaseListHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}
	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	scene := ctx.QueryArgumentWithFallback("scene", "")
	if scene != "" {
		filterParams.Scene = scene
	}
	staticBases, totalCount, err := operationBaseService.ListStaticBase(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	return ResponsePagingSuccess(staticBases, "", totalCount)
}

type StaticBaseAddOrUpdateHandler struct {
	rest.BaseHandler
}

func NewStaticBaseAddOrUpdateHandler() rest.Handler {
	return &StaticBaseAddOrUpdateHandler{}
}

type ReqBaseDTO struct {
	Question   string `json:"question"`
	Answer     string `json:"answer"`
	Status     byte   `json:"status"`
	Scene      string `json:"scene"`
	MatchTypes string `json:"match_types"` // 多个用逗号分割
}

func (k *StaticBaseAddOrUpdateHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	userId := md.GetUserId(ctx)

	var reqBaseDTO *ReqBaseDTO
	err = ctx.JSONArgs(&reqBaseDTO)

	scenes, _ := operationBaseService.GetScenes(ctx)
	if reqBaseDTO.Scene != "" && !lo.Contains(scenes.StaticBaseScenes, reqBaseDTO.Scene) {
		return nil, errors.New("不存在的场景")
	}

	staticBase := model.StaticBase{
		Question:   reqBaseDTO.Question,
		Answer:     reqBaseDTO.Answer,
		StatusCode: reqBaseDTO.Status,
		Scene:      reqBaseDTO.Scene,
	}

	if strings.Contains(ctx.Request.RequestURI, "update") {
		idStr := ctx.URLParam("id")
		if idStr == "" {
			return nil, errors.New("url错误, 没有id")
		}
		id, err := strconv.Atoi(idStr)
		if err != nil {
			return nil, err
		}
		staticBase.Id = int64(id)
		staticBase.UpdateUserId = userId

		staticBaseResult, err := operationBaseService.UpdateStaticBase(ctx, &staticBase)
		if err != nil {
			return nil, err
		}
		return ResponseSuccess(staticBaseResult)
	} else {
		staticBase.CreateUserId = userId

		var staticBases = make([]*model.StaticBase, 0, 1)
		staticBases = append(staticBases, &staticBase)

		staticBases, err = operationBaseService.AddStaticBase(ctx, staticBases)
		if err != nil {
			return nil, err
		}
		return ResponseSuccess(staticBases)
	}
}

type StaticBaseUploadHandler struct {
	rest.BaseHandler
}

func NewStaticBaseUploadHandler() rest.Handler {
	return &StaticBaseUploadHandler{}
}

func parseStaticBaseExcel(file *excelize.File, userId string) ([]*model.StaticBase, error) {
	rows, err := file.GetRows("Sheet1")
	if err != nil {
		return nil, err
	}

	var staticBases []*model.StaticBase
	scenes, _ := operationBaseService.GetScenes(context.Background())
	staticBaseScenes := scenes.StaticBaseScenes

	for i, row := range rows {
		if len(row) < 3 {
			return nil, errors.New("文件格式不对，请使用「静态库」模板")
		}
		// 第0行是excel header
		if i == 0 {
			if strings.TrimSpace(row[0]) != "场景" || strings.TrimSpace(row[1]) != "问题" || strings.TrimSpace(row[2]) != "回答" {
				return nil, errors.New("文件格式不对，请使用「静态库」模板")
			}
			continue
		}
		if len(row[0]) == 0 || len(rows[1]) == 0 || len(rows[2]) == 0 {
			continue
		}

		scene := strings.TrimSpace(row[0])
		if !lo.Contains(staticBaseScenes, scene) {
			return nil, errors.New("不存在的场景")
		}
		staticBase := model.StaticBase{
			Question:     strings.TrimSpace(row[1]),
			Answer:       strings.TrimSpace(row[2]),
			Scene:        scene,
			CreateUserId: userId,
			StatusCode:   model.OperationBaseStatusOnline,
		}

		staticBases = append(staticBases, &staticBase)
	}
	return staticBases, nil
}

func (k *StaticBaseUploadHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	var userId = md.GetUserId(ctx)

	err = ctx.Request.ParseMultipartForm(32 << 20)
	if err != nil {
		return nil, err
	}

	files := lo.Flatten(lo.Values(ctx.Request.MultipartForm.File))

	if len(files) == 0 {
		return nil, errors.New("文件不存在")
	}

	file, err := files[0].Open()
	excelFile, err := excelize.OpenReader(file)
	if err != nil {
		// 处理错误
		return nil, err
	}

	staticBases, err := parseStaticBaseExcel(excelFile, userId)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("parseStaticBaseExcel error. userId=%s", userId))
		return nil, err
	}

	if len(staticBases) == 0 {
		return BaseResponse{
			Success: false,
			Msg:     "文件为空",
			Data:    nil,
		}, nil
	}

	knowledgeBasesResult, err := operationBaseService.AddStaticBase(ctx, staticBases)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(knowledgeBasesResult)
}

// ---------faq相关begin ------------

type FaqBaseListHandler struct {
	rest.BaseHandler
}

func NewFaqBaseListHandler() rest.Handler {
	return &FaqBaseListHandler{}
}

func convertMatchTypeStrToArray(matchTypeStr string) []conf.FaqMatchType {
	var matchTypes []conf.FaqMatchType
	if matchTypeStr == "" {
		return matchTypes
	}
	if matchTypeStr == "all" {
		matchTypes = conf.FaqMatchTypeValues()
		return matchTypes
	}

	matchTypeStrs := strings.Split(matchTypeStr, ",")
	matchTypes = lo.Filter(lo.Map(matchTypeStrs, func(matchType string, _ int) conf.FaqMatchType {
		value, err := cast.ToIntE(matchType)
		if err == nil {
			return conf.FaqMatchType(value)
		}
		faqMatchType, ok := conf.StringToFaqMatchType(matchType)
		if ok {
			return faqMatchType
		} else {
			log.Errorf(context.Background(), "parse match type error, value=%s", matchType)
			return conf.FaqMatchTypeEmbeddingUnknown
		}
	}), func(item conf.FaqMatchType, _ int) bool {
		return item != conf.FaqMatchTypeEmbeddingUnknown
	})

	return matchTypes
}

func (k *FaqBaseListHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}
	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	scene := ctx.QueryArgumentWithFallback("scene", "")
	if scene != "" {
		filterParams.Scene = scene
	}

	matchTypeStr := ctx.QueryArgumentWithFallback("match_types", "")
	if matchTypeStr != "" {
		matchTypes := convertMatchTypeStrToArray(matchTypeStr)
		filterParams.MatchType = matchTypes
	}
	faqBases, totalCount, err := operationBaseService.ListFaqBase(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	for _, each := range faqBases {
		each.MatchTypes = conf.ConvertMatchTypesToStr(conf.ConvertIntToFaqMatchTypeArray(each.MatchType))
	}
	return ResponsePagingSuccess(faqBases, "", totalCount)
}

func checkFaqAuthority(ctx context.Context, userId string, scene string, leastAuthority int) error {
	if userId == "" {
		return errors.New("请先登录")
	}

	authority, err := operationBaseService.GetAuthority(ctx, userId)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("GetAuthority error. userId=%s", userId))
		return err
	}

	if authority.Authorities[scene] < leastAuthority {
		log.Errorf(ctx, "Authority error. userId=%s no authority %d. scene=%s", userId, leastAuthority, scene)
		return errors.New("没有权限")
	} else {
		return nil
	}
}

type FaqBaseAddOrUpdateHandler struct {
	rest.BaseHandler
}

func NewFaqBaseAddOrUpdateHandler() rest.Handler {
	return &FaqBaseAddOrUpdateHandler{}
}

func (k *FaqBaseAddOrUpdateHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	userId := md.GetUserId(ctx)

	var reqBaseDTO *ReqBaseDTO
	err = ctx.JSONArgs(&reqBaseDTO)

	scenes, _ := operationBaseService.GetScenes(ctx)
	if reqBaseDTO.Scene != "" && !lo.Contains(scenes.FaqBaseScenes, reqBaseDTO.Scene) {
		return nil, errors.New("不存在的场景")
	}

	err = checkFaqAuthority(ctx, userId, reqBaseDTO.Scene, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	faqBase := model.FaqBase{
		Question:   reqBaseDTO.Question,
		Answer:     reqBaseDTO.Answer,
		StatusCode: reqBaseDTO.Status,
		Scene:      reqBaseDTO.Scene,
		MatchType:  conf.ConvertFaqMatchTypeArrayToInt(convertMatchTypeStrToArray(reqBaseDTO.MatchTypes)),
	}

	if strings.Contains(ctx.Request.RequestURI, "update") {
		idStr := ctx.URLParam("id")
		if idStr == "" {
			return nil, errors.New("url错误, 没有id")
		}
		id, err := strconv.Atoi(idStr)
		if err != nil {
			return nil, err
		}
		faqBase.Id = int64(id)
		faqBase.UpdateUserId = userId

		updateFaqBase, err := operationBaseService.UpdateFaqBase(ctx, &faqBase)
		if err != nil {
			return nil, err
		}

		updateFaqBase.MatchTypes = conf.ConvertMatchTypesToStr(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType))
		return ResponseSuccess(updateFaqBase)
	} else {
		faqBase.CreateUserId = userId

		var faqBases = make([]*model.FaqBase, 0, 1)
		faqBases = append(faqBases, &faqBase)

		faqBases, err = operationBaseService.AddFaqBase(ctx, faqBases)
		if err != nil {
			return nil, err
		}

		for _, each := range faqBases {
			each.MatchTypes = conf.ConvertMatchTypesToStr(conf.ConvertIntToFaqMatchTypeArray(each.MatchType))
		}
		return ResponseSuccess(faqBases)
	}
}

type FaqBaseUploadHandler struct {
	rest.BaseHandler
}

func NewFaqBaseUploadHandler() rest.Handler {
	return &FaqBaseUploadHandler{}
}

func (k *FaqBaseUploadHandler) parseFaqBaseExcel(ctx context.Context, file *excelize.File, userId string) ([]*model.FaqBase, error) {
	rows, err := file.GetRows("Sheet1")
	if err != nil {
		return nil, err
	}

	var faqBases []*model.FaqBase
	scenes, _ := operationBaseService.GetScenes(ctx)
	faqBaseScenes := scenes.FaqBaseScenes

	for i, row := range rows {
		if len(row) < 3 {
			return nil, errors.New("文件格式不对，请使用「FAQ库」模板")
		}
		// 第0行是excel header
		if i == 0 {
			if strings.TrimSpace(row[0]) != "场景" || !strings.Contains(strings.TrimSpace(row[1]), "问题") ||
				!strings.Contains(strings.TrimSpace(row[2]), "匹配方式") || !strings.Contains(strings.TrimSpace(row[3]), "回答") {
				return nil, errors.New("文件格式不对，请使用「FAQ库」模板")
			}
			continue
		}
		if len(row[0]) == 0 || len(rows[1]) == 0 || len(rows[2]) == 0 {
			continue
		}

		scene := strings.TrimSpace(row[0])
		scene, err = operationBaseService.ConvertFaqSceneAliasName(ctx, scene)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "ConvertFaqSceneAliasName error. scene=%s", scene)
			return nil, err
		}
		if !lo.Contains(faqBaseScenes, scene) {
			return nil, errors.New("不存在的场景")
		}

		err = checkFaqAuthority(ctx, userId, scene, operation_base.AuthorityEdit)
		if err != nil {
			return nil, err
		}
		matchTypes := convertMatchTypeStrToArray(strings.TrimSpace(row[2]))
		if len(matchTypes) == 0 {
			return nil, errors.New("「匹配方式」列格式不对，请使用「FAQ库」模板")
		}
		faqBase := model.FaqBase{
			Question:     strings.TrimSpace(row[1]),
			Answer:       strings.TrimSpace(row[3]),
			Scene:        scene,
			MatchType:    conf.ConvertFaqMatchTypeArrayToInt(matchTypes),
			CreateUserId: userId,
			StatusCode:   model.OperationBaseStatusOnline,
		}

		faqBases = append(faqBases, &faqBase)
	}
	return faqBases, nil
}

func (k *FaqBaseUploadHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}
	var userId = md.GetUserId(ctx)

	err = ctx.Request.ParseMultipartForm(32 << 20)
	if err != nil {
		return nil, err
	}

	files := lo.Flatten(lo.Values(ctx.Request.MultipartForm.File))

	if len(files) == 0 {
		return nil, errors.New("文件不存在")
	}

	file, err := files[0].Open()
	excelFile, err := excelize.OpenReader(file)
	if err != nil {
		// 处理错误
		return nil, err
	}

	faqBases, err := k.parseFaqBaseExcel(ctx, excelFile, userId)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, fmt.Sprintf("parseFaqBaseExcel error. userId=%s", userId))
		return nil, err
	}

	if len(faqBases) == 0 {
		return BaseResponse{
			Success: false,
			Msg:     "文件为空",
			Data:    nil,
		}, nil
	}

	addedFaqBases, err := operationBaseService.AddFaqBase(ctx, faqBases)
	if err != nil {
		return nil, err
	}

	for _, each := range addedFaqBases {
		each.MatchTypes = conf.ConvertMatchTypesToStr(conf.ConvertIntToFaqMatchTypeArray(each.MatchType))
	}
	return ResponseSuccess(addedFaqBases)
}

type TracingListHandler struct {
	rest.BaseHandler
}

func NewTracingListHandler() rest.Handler {
	return &TracingListHandler{}
}

func (k *TracingListHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	filterParams.Scene = ctx.QueryArgumentWithFallback("scene", "")
	filterParams.MemberId = ctx.Int64QueryArgument("member_id", 0)
	filterParams.MessageId = ctx.QueryArgumentWithFallback("message_id", "")
	filterParams.RespMessageId = ctx.QueryArgumentWithFallback("resp_message_id", "")
	security := ctx.QueryArgumentWithFallback("security_tag", "")
	if security != "" {
		filterParams.Security = strings.Split(security, ",")
	}
	filterParams.ChatResponse = ctx.QueryArgumentWithFallback("chat_response", "")

	result, totalCount, err := operationBaseService.ListLogTracing(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	return ResponsePagingSuccess(result, "", int64(totalCount))
}

type TracingDetailHandler struct {
	rest.BaseHandler
}

func NewTracingDetailHandler() rest.Handler {
	return &TracingDetailHandler{}
}

func (k *TracingDetailHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	filterParams.TraceId = ctx.QueryArgumentWithFallback("trace_id", "")
	filterParams.AppName = ctx.QueryArgumentWithFallback("app_name", "")
	filterParams.UnitName = ctx.QueryArgumentWithFallback("unit_name", "")
	filterParams.GraphName = ctx.QueryArgumentWithFallback("graph_name", "")

	result, err := operationBaseService.GetLogicTracing(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(result)
}

type TracingEventHandler struct {
	rest.BaseHandler
}

func NewTracingEventHandler() rest.Handler {
	return &TracingEventHandler{}
}

func (k *TracingEventHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	filterParams.TraceId = ctx.QueryArgumentWithFallback("trace_id", "")
	filterParams.AppName = ctx.QueryArgumentWithFallback("app_name", "")
	filterParams.UnitName = ctx.QueryArgumentWithFallback("unit_name", "")
	filterParams.GraphName = ctx.QueryArgumentWithFallback("graph_name", "")

	result, err := chatEventChainLinkTraceDao.GetTrace(ctx, filterParams.TraceId)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(result.ChainLinkTraceJson)
}

type TracingDownloadHandler struct {
	rest.BaseHandler
}

func NewTracingDownloadHandler() rest.Handler {
	return &TracingDownloadHandler{}
}

func (k *TracingDownloadHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	filterParams.TraceId = ctx.QueryArgumentWithFallback("trace_id", "")

	logTracings, _, ltErr := operationBaseService.ListLogTracing(ctx, filterParams)
	if ltErr != nil || len(logTracings) == 0 {
		return nil, ltErr
	}

	logTracing := logTracings[0]

	filterParams.AppName = logTracing.AppName
	filterParams.UnitName = logTracing.UnitName
	filterParams.GraphName = logTracing.GraphName

	logicTracings, logicErr := operationBaseService.GetLogicTracing(ctx, filterParams)
	if logicErr != nil {
		return nil, logicErr
	}

	excelFile, excelErr := operationBaseService.WriteExcel(ctx, logTracing, logicTracings)
	if excelErr != nil {
		return nil, excelErr
	}

	// 将Excel文件保存到内存中
	buffer := new(bytes.Buffer)
	if err := excelFile.Write(buffer); err != nil {
		return nil, err
	}

	// 设置下载相关的header
	ctx.Writer.Header().Set("Content-Disposition", "attachment; filename=download.xlsx")
	ctx.Writer.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

	// 将Excel文件内容写入HTTP响应
	_, err = ctx.Writer.Write(buffer.Bytes())
	if err != nil {
		return nil, err
	}

	return EmptyResult, nil
}
