package operation_base

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"net/http"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/tealeg/xlsx"
	"golang.org/x/exp/slices"
)

const (
	NoAuthority = iota
	AuthorityRead
	AuthorityEdit
)

// OperationBaseManagementService 知识库、静态库的增删改查
type OperationBaseManagementService interface {
	// GetAuthority 获取权限，包括无权限、只读、可编辑
	GetAuthority(ctx context.Context, userId string) (model.Authority, error)
	// GetScenes 获取场景
	GetScenes(ctx context.Context) (*model.Scene, error)

	ConvertFaqSceneAliasName(ctx context.Context, name string) (string, error)
	// GetSceneToRumTableNameMap 返回结果，key：scene，value：rum_table_name
	GetSceneToRumTableNameMap(ctx context.Context) map[string]string

	// ListKnowledgeBase 获取知识库列表。query: 用户在页面输入的筛选词
	ListKnowledgeBase(ctx context.Context, params *model.FilterParams) ([]*model.KnowledgeBaseV2, int64, error)
	// UpdateKnowledgeBase 更新知识库
	UpdateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBaseV2) (*model.KnowledgeBaseV2, error)
	// AddKnowledgeBase 新增知识库，批量接口
	AddKnowledgeBase(ctx context.Context, knowledgeBases []*model.KnowledgeBaseV2) ([]*model.KnowledgeBaseV2, error)

	// ListStaticBase 获取静态库列表。query: 用户在页面输入的筛选词
	ListStaticBase(ctx context.Context, params *model.FilterParams) ([]*model.StaticBase, int64, error)
	// UpdateStaticBase 更新静态库
	UpdateStaticBase(ctx context.Context, staticBase *model.StaticBase) (*model.StaticBase, error)
	// AddStaticBase 新增静态库，批量接口
	AddStaticBase(ctx context.Context, staticBases []*model.StaticBase) ([]*model.StaticBase, error)

	// ListFaqBase 获取faq库列表。query: 用户在页面输入的筛选词
	ListFaqBase(ctx context.Context, params *model.FilterParams) ([]*model.FaqBase, int64, error)

	ListFaqBaseById(ctx context.Context, id int64) (*model.FaqBase, error)
	// UpdateFaqBase 更新faq库
	UpdateFaqBase(ctx context.Context, faqBase *model.FaqBase) (*model.FaqBase, error)
	// AddFaqBase 新增faq库，批量接口
	AddFaqBase(ctx context.Context, faqBases []*model.FaqBase) ([]*model.FaqBase, error)

	ListLogTracing(ctx context.Context, params *model.FilterParams) ([]*model.LogTracing, int, error)
	GetLogicTracing(ctx context.Context, params *model.FilterParams) ([]*model.LogicTracing, error)
	WriteExcel(ctx context.Context, logTracing *model.LogTracing, logicTracings []*model.LogicTracing) (*xlsx.File, error)
}

type OperationBaseManagementImpl struct {
	tracingLogService tracing_log.TracingLogService

	knowledgeBaseDao dao.KnowledgeBaseV2DAO
	staticBaseDao    dao.StaticBaseDAO
	faqBaseDao       dao.FaqBaseDAO

	rumClient          rpc.RumClient[float32]
	ruceneRpc          rpc.RuceneServiceRPC
	bgeEmbeddingClient rpc.KlaraRpcClient
	qpRpc              rpc.QueryProfileRpc
	httpClient         *http.Client
}

var DefaultOperationBaseManagementService OperationBaseManagementService

func newOperationBaseManagementService() *OperationBaseManagementImpl {
	return &OperationBaseManagementImpl{
		tracingLogService:  tracing_log.DefaultTracingLogService,
		knowledgeBaseDao:   dao.DefaultKnowledgeBaseV2DAO,
		staticBaseDao:      dao.DefaultStaticBaseDAO,
		faqBaseDao:         dao.DefaultFaqBaseDAO,
		rumClient:          impl.DefaultFloat32RumClientImpl,
		ruceneRpc:          rpc.NewRuceneServiceRPC(8000 * time.Millisecond),
		bgeEmbeddingClient: impl.GetBgeEmbeddingClient("ensemble"),
		qpRpc:              impl.DefaultQpImpl,
		httpClient: &http.Client{
			Timeout: 2000 * time.Millisecond,
		},
	}
}

type AuthorityConfig struct {
	// key是场景
	Read map[string][]string `json:"read"`
	Edit map[string][]string `json:"edit"`
}

func (k OperationBaseManagementImpl) GetAuthority(ctx context.Context, userId string) (model.Authority, error) {
	authorityReadStr := config.GetString("operation_base.authority.read", "")
	authorityEditStr := config.GetString("operation_base.authority.edit", "")
	authorityStr := config.GetString("operation_base.authority", "")

	var readUserIds []string
	if authorityReadStr != "" {
		err := util.JSONUnmarshal([]byte(authorityReadStr), &readUserIds)
		if err != nil {
			log.WithField(ctx, "userId", userId).WithError(ctx, err).Errorf(ctx, "unmarshal authorityReadStr error")
		}
	}

	var editUserIds []string
	if authorityEditStr != "" {
		err := util.JSONUnmarshal([]byte(authorityEditStr), &editUserIds)
		if err != nil {
			log.WithField(ctx, "userId", userId).WithError(ctx, err).Errorf(ctx, "unmarshal authorityEditStr error")
		}
	}
	var authorityConfig AuthorityConfig
	if authorityStr != "" {
		err := util.JSONUnmarshal([]byte(authorityStr), &authorityConfig)
		if err != nil {
			log.WithField(ctx, "userId", userId).WithError(ctx, err).Errorf(ctx, "unmarshal authorityStr error")
		}
	}

	authority := model.Authority{
		Authorities: map[string]int{},
	}
	if lo.Contains(editUserIds, userId) {
		authority.Authority = AuthorityEdit
	} else if lo.Contains(readUserIds, userId) {
		authority.Authority = AuthorityRead
	} else {
		authority.Authority = NoAuthority
	}

	for scene, userIds := range authorityConfig.Edit {
		if lo.Contains(userIds, userId) {
			authority.Authorities[scene] = AuthorityEdit
		}
	}

	return authority, nil
}

var tracingSceneMap = map[string]string{
	proto.ChatType_PC_DISCOVER_TAB.String(): "PC发现tab",
	proto.ChatType_DISCOVER_TAB.String():    "发现tab",
	proto.ChatType_ZHIDA_TAB.String():       "直答",
	proto.ChatType_ZHIDA_V2.String():        "直答V2",
	proto.ChatType_ZHIDA_AGENT.String():     "直答Agent",
	proto.ChatType_ZHIDA_PRO_TAB.String():   "直答专业版",
	proto.ChatType_DIGITAL_AUTHOR.String():  "数字分身",
	proto.ChatType_ZPLUS_BRAND.String():     "知+品牌",
}

var SceneToPbNameMap map[string]string

func (k OperationBaseManagementImpl) GetScenes(ctx context.Context) (*model.Scene, error) {
	staticBaseScenesStr := config.GetString("operation_base.static_base_scenes", "")
	var staticBaseScenes []string
	if staticBaseScenesStr != "" {
		err := util.JSONUnmarshal([]byte(staticBaseScenesStr), &staticBaseScenes)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "unmarshal staticBaseScenesStr error. staticBaseScenesStr=%s", staticBaseScenesStr)
		}
	}

	faqBaseScenesStr := config.GetString("operation_base.faq_base_scenes", "")
	var faqBaseSceneConfigs []model.SceneConfig
	if faqBaseScenesStr != "" {
		err := util.JSONUnmarshal([]byte(faqBaseScenesStr), &faqBaseSceneConfigs)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "unmarshal faqBaseScenesStr error. faqBaseScenesStr=%s", faqBaseScenesStr)
		}
	}

	faqBaseScenes := lo.Map(faqBaseSceneConfigs, func(item model.SceneConfig, _ int) string {
		return item.Name
	})

	var tracingScenes []string
	for _, sceneDescription := range tracingSceneMap {
		tracingScenes = append(tracingScenes, sceneDescription)
	}

	return &model.Scene{
		StaticBaseScenes:   staticBaseScenes,
		FaqBaseScenes:      faqBaseScenes,
		FaqBaseSceneConfig: faqBaseSceneConfigs,
		TracingScenes:      tracingScenes,
	}, nil
}

func (k OperationBaseManagementImpl) ConvertFaqSceneAliasName(ctx context.Context, name string) (string, error) {
	scenes, err := k.GetScenes(ctx)
	if err != nil {
		return "", err
	}

	configs := lo.Filter(scenes.FaqBaseSceneConfig, func(config model.SceneConfig, _ int) bool {
		return slices.Contains(config.AliasNames, name)
	})

	if len(configs) <= 0 {
		return "", errors.New("ConvertFaqSceneAliasName error. name=" + name)
	}

	return configs[0].Name, nil
}

func (k OperationBaseManagementImpl) ListKnowledgeBase(ctx context.Context, params *model.FilterParams) ([]*model.KnowledgeBaseV2, int64, error) {
	knowledgeBases, err := k.knowledgeBaseDao.ListByParams(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	totalCount, err := k.knowledgeBaseDao.GetTotalCount(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	return knowledgeBases, totalCount, nil
}

func (k OperationBaseManagementImpl) getTraceIdRuceneCondition(scene string, graphName string, traceIds []string) *model.MultiCondition {
	var finalCondition *model.MultiCondition
	var sceneCondition model.MultiCondition
	var graphCondition model.MultiCondition
	var traceIdCondition model.MultiCondition

	// 场景筛选项
	if scene != "" && SceneToPbNameMap[scene] != "" {
		sceneCondition = model.MultiCondition{Condition: &model.Condition{
			FieldName:   macro.TracingFieldScene,
			FieldValue:  SceneToPbNameMap[scene],
			OperateType: model.OperateTypeEq,
		}}
	}

	// graph名称筛选
	if graphName != "" {
		graphCondition = model.MultiCondition{Condition: &model.Condition{
			FieldName:   macro.TracingFieldGraphName,
			FieldValue:  graphName,
			OperateType: model.OperateTypeEq,
		}}
	}

	// traceId 筛选条件
	var traceIdConditions []model.MultiCondition
	for _, traceId := range traceIds {
		traceIdConditions = append(traceIdConditions,
			model.MultiCondition{
				Condition: &model.Condition{
					FieldName:   macro.TracingFieldTraceId,
					FieldValue:  traceId,
					OperateType: model.OperateTypeEq,
				},
			})
	}
	if len(traceIdConditions) > 0 {
		traceIdCondition = model.MultiCondition{
			Shoulds: traceIdConditions,
		}
	}

	finalCondition = &model.MultiCondition{
		Musts: []model.MultiCondition{
			sceneCondition,
			graphCondition,
			traceIdCondition,
		},
	}

	return finalCondition
}

func (k OperationBaseManagementImpl) getLogTracingRuceneCondition(ctx context.Context, params *model.FilterParams) *model.MultiCondition {
	logRucene := &model.LogRucene{
		Query:         params.Query,
		Security:      params.Security,
		Response:      []string{params.ChatResponse},
		Scene:         SceneToPbNameMap[params.Scene],
		MemberId:      params.MemberId,
		MessageId:     params.MessageId,
		RespMessageId: params.RespMessageId,
		TraceId:       params.TraceId,
	}

	if params.CreatedAtBegin != nil {
		logRucene.RequestStartTimeMs = params.CreatedAtBegin.UnixMilli()
	}
	if params.CreatedAtEnd != nil {
		logRucene.RequestEndTimeMs = params.CreatedAtEnd.UnixMilli()
	}

	return k.tracingLogService.GetLogTracingRuceneCondition(ctx, logRucene)
}

// 获取 tracing 日志列表
// 注意 rucene 不支持分页，因此为了实现全局排序功能，需要先检索全表，排序截断后再检索一次获取 doc 信息
func (k OperationBaseManagementImpl) ListLogTracing(ctx context.Context, params *model.FilterParams) ([]*model.LogTracing, int, error) {
	var result = make([]*model.LogTracing, 0)

	// 查询所有符合条件的 doc 的 traceId，不分页
	allRuceneDocTraceIds := k.cacheGetAllRuceneDocId(ctx, params)
	if len(allRuceneDocTraceIds) == 0 {
		return result, 0, nil
	}

	// 对结果进行分页截取
	start := util2.Min(params.PageSize*params.Page, len(allRuceneDocTraceIds)-1)
	end := util2.Min(start+params.PageSize, len(allRuceneDocTraceIds))
	traceId := allRuceneDocTraceIds[start:end]

	// 根据本页 traceId，再去查 rucene 拿到完整 doc 字段
	resp, err := k.searchRuceneByTraceId(ctx, params.Scene, "", traceId)
	if err != nil || resp == nil {
		return result, 0, err
	}

	for _, item := range resp.Hits {
		scene := strings.Split(item.StoreFields.GetString(macro.TracingFieldScene), ".")
		sceneStr := scene[len(scene)-1]
		sceneDesc := tracingSceneMap[sceneStr]

		requestTime := item.StoreFields.GetInt64(macro.TracingFieldRequestTimeMs)
		if util.IsMillisecond(requestTime) {
			requestTime = requestTime / 1000
		}
		result = append(result, &model.LogTracing{
			MemberId:          item.StoreFields.GetInt64(macro.TracingFieldMemberId),
			ChatScene:         sceneDesc,
			RequestMessageId:  item.StoreFields.GetString(macro.TracingFieldMessageId),
			RequestQuery:      item.StoreFields.GetString(macro.TracingFieldQuery),
			ResponseMessageId: item.StoreFields.GetString(macro.TracingFieldRespMessageId),
			ResponseAnswer:    item.StoreFields.GetString(macro.TracingFieldResponse),
			SecurityTag:       strings.Join(item.StoreFields.GetStringSlice(macro.TracingFieldSecurity), "\n"),
			RequestTime:       util.TimeStamp2DateTime(requestTime),
			RequestTimeSecond: requestTime,
			TraceId:           item.StoreFields.GetString(macro.TracingFieldTraceId),
			GraphName:         item.StoreFields.GetString(macro.TracingFieldGraphName),
			RequestInfo:       item.StoreFields.GetString(macro.TracingFieldRequestInfo),
			ResponseInfo:      item.StoreFields.GetString(macro.TracingFieldResponseInfo),
			AppName:           item.StoreFields.GetString(macro.TracingFieldAppName),
			UnitName:          item.StoreFields.GetString(macro.TracingFieldServiceName),
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].RequestTimeSecond > result[j].RequestTimeSecond
	})

	return result, len(allRuceneDocTraceIds), nil
}

// scene+traceId or graphName+traceId 可唯一确定一条日志
func (k OperationBaseManagementImpl) searchRuceneByTraceId(ctx context.Context, scene string, graphName string, traceIds []string) (*client.Response, error) {
	traceIdCondition := k.getTraceIdRuceneCondition(scene, graphName, traceIds)
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, traceIdCondition, model.Path, model.Index, macro.LogTracingStoreFields)
	orderField := macro.TracingFieldRequestTimeMs // 二级排序字段，相同匹配分数情况下，按照时间倒序
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               len(traceIds),
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        ruceneQueryRequest.QueryFields,
		TransportTimeoutMs: 8000,
		Score2Field:        &orderField,
		EarlyTerminate:     1000000,
	}

	return k.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.Path, model.Index, queryRequest)
}

func (k OperationBaseManagementImpl) cacheGetAllRuceneDocId(ctx context.Context, params *model.FilterParams) []string {
	res := make(map[string][]string, 1)

	// 深拷贝一下，去除 page 信息
	cacheParam := &model.FilterParams{}
	err := util.DeepCopyByJSON(cacheParam, params)
	if err != nil {
		return []string{}
	}
	cacheParam.Page = 0
	cacheParam.PageSize = 0
	paramStrS := util.GetJSONIgnoreError(cacheParam)

	resource.RedisLocalCache.BatchGet(ctx, []string{paramStrS}, util.StringKeyGeneratorFunc,
		func(params interface{}) interface{} {
			paramStr := params.([]string)[0]
			param := &model.FilterParams{}
			err := json.Unmarshal([]byte(paramStr), &param)
			if err != nil {
				return map[string][]model.LogTracing{}
			}
			result, _ := k.getAllRuceneDocId(ctx, param)
			return map[string][]string{
				paramStr: result,
			}
		}, &res, util.TracingLogIdsKeyOption)

	return res[paramStrS]
}

func (k OperationBaseManagementImpl) getAllRuceneDocId(ctx context.Context, params *model.FilterParams) ([]string, error) {
	condition := k.getLogTracingRuceneCondition(ctx, params)
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, model.Path, model.Index, macro.LogTracingStoreFields)
	logTracing, err := k.searchAllRuceneDocIdWithTimeDesc(ctx, ruceneQueryRequest)

	var traceIds []string
	for _, tracing := range logTracing {
		traceIds = append(traceIds, tracing.TraceId)
	}

	return traceIds, err
}

func (k OperationBaseManagementImpl) searchAllRuceneDocIdWithTimeDesc(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest) ([]model.LogTracing, error) {
	var result = make([]model.LogTracing, 0)
	orderField := macro.TracingFieldRequestTimeMs // 二级排序字段，相同匹配分数情况下，按照时间倒序
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               1000,
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        []string{macro.TracingFieldTraceId, macro.TracingFieldRequestTimeMs},
		TransportTimeoutMs: 8000,
		EarlyTerminate:     1000000,
		Score2Field:        &orderField,
	}

	resp, err := k.ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.Path, model.Index, queryRequest)
	if err != nil || resp == nil {
		return result, err
	}

	for _, item := range resp.Hits {
		requestTime := item.StoreFields.GetInt64(macro.TracingFieldRequestTimeMs)
		if util.IsMillisecond(requestTime) {
			requestTime = requestTime / 1000
		}
		result = append(result, model.LogTracing{
			TraceId:           item.StoreFields.GetString(macro.TracingFieldTraceId),
			RequestTimeSecond: requestTime,
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].RequestTimeSecond > result[j].RequestTimeSecond
	})

	return result, nil
}

func (k OperationBaseManagementImpl) GetLogicTracing(ctx context.Context, params *model.FilterParams) ([]*model.LogicTracing, error) {
	var result = make([]*model.LogicTracing, 0)
	// 根据 traceId 拿到日志完整信息
	logResp, err := k.searchRuceneByTraceId(ctx, "", params.GraphName, []string{params.TraceId})
	if err != nil || logResp == nil || len(logResp.Hits) != 1 {
		return result, err
	}

	requestTimeMs := logResp.Hits[0].StoreFields.GetInt64(macro.TracingFieldRequestTimeMs)
	if !util.IsMillisecond(requestTimeMs) {
		requestTimeMs = requestTimeMs * 1000
	}

	// 调用 zag 服务获取图运行时信息
	host := "https://zag.pek01.in.zhihu.com/info/getGraphRuntimeInfo"
	url := fmt.Sprintf("%s?appName=%s&unitName=%s&graphName=%s&requestId=%s&writeTime=%d", host, params.AppName, params.UnitName, params.GraphName, params.TraceId, requestTimeMs)

	request, err := http.NewRequest(http.MethodGet, url, http.NoBody)
	if err != nil {
		return result, err
	}

	resp, err := k.httpClient.Do(request)
	if err != nil {
		return result, nil
	}

	graphLog := &model.GraphLogInfoVo{}
	bodyBytes, err := ioutil.ReadAll(resp.Body)
	if err = json.Unmarshal(bodyBytes, &graphLog); err != nil {
		return nil, err
	}

	nodeDataIn := map[string]string{}
	nodeDataOut := map[string]string{}
	nodeProcess := map[string]string{}

	for _, node := range graphLog.LogMap[string(constant.InputDataType)] {
		nodeDataIn[node.NodeName] = getLogBody(node.NodeName, node.LogStr)
	}
	for _, node := range graphLog.LogMap[string(constant.OutputDataType)] {
		nodeDataOut[node.NodeName] = getLogBody(node.NodeName, node.LogStr)
	}
	for _, node := range graphLog.LogMap[string(macro.ProcessLogType)] {
		nodeProcess[node.NodeName] = getLogBody(node.NodeName, node.LogStr)
	}

	nodeUniqueMap := map[string]bool{}
	for _, info := range graphLog.TimingInfo {
		if len(info) != 3 {
			continue
		}
		nodeName := info[1]
		startTime := util.SafeString2Int64(info[0], -1)
		costMs := util.SafeString2Int64(info[2], -1)

		if nodeName == "Name" {
			continue
		}
		if strings.HasPrefix(nodeName, "#%40&") {
			nodeName = strings.Split(nodeName, "#%40&")[1]
		}
		if nodeUniqueMap[nodeName] {
			continue
		}
		nodeUniqueMap[nodeName] = true

		result = append(result, &model.LogicTracing{
			LogicName:      nodeName,
			Description:    "暂无描述",
			Input:          nodeDataIn[nodeName],
			Output:         nodeDataOut[nodeName],
			Process:        nodeProcess[nodeName],
			StartTime:      startTime,
			EndTime:        startTime + costMs,
			CostMilSeconds: costMs,
		})
	}

	// index 正序排序
	sort.Slice(result, func(i, j int) bool {
		return result[i].StartTime < result[j].StartTime
	})

	return result, nil
}

func getLogBody(nodeName string, logStr string) string {
	logs := strings.Split(logStr, "]|[")
	if len(logs) >= 4 {
		logStr = logs[3]
	} else {
		logStr = logs[len(logs)-1]
	}

	nodeNameSplit := fmt.Sprintf("%s] ", nodeName)
	logSplit := strings.Split(logStr, nodeNameSplit)
	return logSplit[len(logSplit)-1]

}

func (k OperationBaseManagementImpl) WriteExcel(ctx context.Context, logTracing *model.LogTracing, logicTracings []*model.LogicTracing) (*xlsx.File, error) {
	outputFile := xlsx.NewFile()
	sheet1, err := outputFile.AddSheet("请求数据")
	if err != nil {
		return nil, err
	}

	row := sheet1.AddRow()
	row.AddCell().SetValue("memberId")
	row.AddCell().SetValue("场景")
	row.AddCell().SetValue("请求messageId")
	row.AddCell().SetValue("用户输入")
	row.AddCell().SetValue("返回messageId")
	row.AddCell().SetValue("模型回答")
	row.AddCell().SetValue("安全标签")
	row.AddCell().SetValue("请求时间")
	row.AddCell().SetValue("traceId")
	row.AddCell().SetValue("graphName")
	row.AddCell().SetValue("请求完整结构体")
	row.AddCell().SetValue("返回完整结构体")

	row = sheet1.AddRow()
	row.AddCell().SetValue(logTracing.MemberId)
	row.AddCell().SetValue(logTracing.ChatScene)
	row.AddCell().SetValue(logTracing.RequestMessageId)
	row.AddCell().SetValue(logTracing.RequestQuery)
	row.AddCell().SetValue(logTracing.ResponseMessageId)
	row.AddCell().SetValue(logTracing.ResponseAnswer)
	row.AddCell().SetValue(logTracing.SecurityTag)
	row.AddCell().SetValue(logTracing.RequestTime)
	row.AddCell().SetValue(logTracing.TraceId)
	row.AddCell().SetValue(logTracing.GraphName)
	row.AddCell().SetValue(logTracing.RequestInfo)
	row.AddCell().SetValue(logTracing.ResponseInfo)

	sheet2, err := outputFile.AddSheet("算子追踪")
	if err != nil {
		return nil, err
	}
	row = sheet2.AddRow()
	row.AddCell().SetValue("算子名称")
	row.AddCell().SetValue("算子描述")
	row.AddCell().SetValue("算子输入")
	row.AddCell().SetValue("算子输出")
	row.AddCell().SetValue("过程日志")
	row.AddCell().SetValue("开始时间ms")
	row.AddCell().SetValue("结束数据ms")
	row.AddCell().SetValue("耗时ms")

	for _, logic := range logicTracings {
		row = sheet2.AddRow()
		row.AddCell().SetValue(logic.LogicName)
		row.AddCell().SetValue(logic.Description)
		row.AddCell().SetValue(logic.Input)
		row.AddCell().SetValue(logic.Output)
		row.AddCell().SetValue(logic.Process)
		row.AddCell().SetValue(logic.StartTime)
		row.AddCell().SetValue(logic.EndTime)
		row.AddCell().SetValue(logic.CostMilSeconds)
	}

	return outputFile, nil
}

func (k OperationBaseManagementImpl) UpdateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBaseV2) (*model.KnowledgeBaseV2, error) {
	err := k.knowledgeBaseDao.Update(ctx, knowledgeBase)
	if err != nil {
		return knowledgeBase, err
	}

	knowledgeBase, err = k.knowledgeBaseDao.GetById(ctx, knowledgeBase.Id)
	return knowledgeBase, err
}

func (k OperationBaseManagementImpl) AddKnowledgeBase(ctx context.Context, knowledgeBases []*model.KnowledgeBaseV2) ([]*model.KnowledgeBaseV2, error) {
	for _, knowledgeBase := range knowledgeBases {
		knowledgeBase.StatusCode = model.OperationBaseStatusOffline
	}

	insertResult, nil := k.knowledgeBaseDao.Insert(ctx, knowledgeBases)

	var ids = make([]int64, 0, len(knowledgeBases))
	firstInsertId := insertResult.LastInsertedID - insertResult.AffectedRows + 1
	for i, knowledgeBase := range knowledgeBases {
		knowledgeBase.Id = firstInsertId + int64(i)
		ids = append(ids, knowledgeBase.Id)
	}

	// createAt和updateAt是只读的，所以需要再查一次
	knowledgeBases, err := k.knowledgeBaseDao.GetByIds(ctx, ids)
	if err != nil {
		return knowledgeBases, err
	}

	return knowledgeBases, nil
}

func (k OperationBaseManagementImpl) ListStaticBase(ctx context.Context, params *model.FilterParams) ([]*model.StaticBase, int64, error) {
	staticBases, err := k.staticBaseDao.ListByParams(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	totalCount, err := k.staticBaseDao.GetTotalCount(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	return staticBases, totalCount, nil
}

func (k OperationBaseManagementImpl) UpdateStaticBase(ctx context.Context, staticBase *model.StaticBase) (*model.StaticBase, error) {
	if staticBase.Question != "" {
		staticBase.NoSymbolQuestionHash = util.ConvertToRemovedSymbolHash(staticBase.Question)
	}

	err := k.staticBaseDao.Update(ctx, staticBase)
	if err != nil {
		return staticBase, err
	}

	staticBase, err = k.staticBaseDao.GetById(ctx, staticBase.Id)

	service.ClearZhidaCache(ctx, staticBase.Question)

	return staticBase, err
}

// 这里大于1的话，可能会导致拿到的insertId不对
const insertMaxSize = 1

func (k OperationBaseManagementImpl) AddStaticBase(ctx context.Context, staticBases []*model.StaticBase) ([]*model.StaticBase, error) {
	for _, staticBase := range staticBases {
		if staticBase.StatusCode == model.OperationBaseStatusInit {
			staticBase.StatusCode = model.OperationBaseStatusOffline
		}
		staticBase.NoSymbolQuestionHash = util.ConvertToRemovedSymbolHash(staticBase.Question)
	}

	var ids = make([]int64, 0, len(staticBases))

	staticBasesArray := lo.Chunk(staticBases, insertMaxSize)
	for index, staticBasesChunk := range staticBasesArray {
		insertResult, err := k.staticBaseDao.Insert(ctx, staticBasesChunk)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "insert static base error. index=%d", index)
			break
		}
		firstInsertId := insertResult.LastInsertedID - insertResult.AffectedRows + 1
		for i, staticBase := range staticBasesChunk {
			staticBase.Id = firstInsertId + int64(i)
			ids = append(ids, staticBase.Id)
		}
	}

	// createAt和updateAt是只读的，所以需要查一次
	staticBases, err := k.staticBaseDao.GetByIds(ctx, ids)
	if err != nil {
		return staticBases, err
	}

	for _, staticBase := range staticBases {
		service.ClearZhidaCache(ctx, staticBase.Question)
	}

	return staticBases, nil
}

func (k OperationBaseManagementImpl) ListFaqBase(ctx context.Context, params *model.FilterParams) ([]*model.FaqBase, int64, error) {
	faqBases, err := k.faqBaseDao.ListByParams(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	totalCount, err := k.faqBaseDao.GetTotalCount(ctx, params)
	if err != nil {
		return nil, 0, err
	}

	return faqBases, totalCount, nil
}

func (k OperationBaseManagementImpl) ListFaqBaseById(ctx context.Context, id int64) (*model.FaqBase, error) {
	faqBase, err := k.faqBaseDao.GetById(ctx, id)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "ListFaqBaseById error. id=%d", id)
		return nil, err
	}

	return faqBase, nil
}

func (k OperationBaseManagementImpl) UpdateFaqBase(ctx context.Context, faqBase *model.FaqBase) (*model.FaqBase, error) {
	err := k.faqBaseDao.Update(ctx, faqBase)
	if err != nil {
		return faqBase, err
	}

	shouldUpsertRum := false
	shouldDeleteRum := false
	if faqBase.StatusCode == model.OperationBaseStatusOffline ||
		faqBase.StatusCode == model.OperationBaseStatusDeleted ||
		(faqBase.MatchType != 0 && !slices.Contains(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType), conf.FaqMatchTypeEmbeddingSimilarity)) {
		shouldDeleteRum = true
	} else if faqBase.Question != "" ||
		faqBase.StatusCode == model.OperationBaseStatusOnline ||
		slices.Contains(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType), conf.FaqMatchTypeEmbeddingSimilarity) {
		shouldUpsertRum = true
	}

	faqBase, err = k.faqBaseDao.GetById(ctx, faqBase.Id)

	rumTableName := k.GetSceneToRumTableNameMap(ctx)[faqBase.Scene]
	if shouldUpsertRum {
		// 用户选择修改问题、上线、匹配方式增加向量匹配时，可能需要更新。拿到全部faqBase数据后，再判断下是否在线以及有向量匹配方式
		if faqBase.StatusCode == model.OperationBaseStatusOnline ||
			slices.Contains(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType), conf.FaqMatchTypeEmbeddingSimilarity) {
			embeddings := k.bgeEmbeddingClient.BatchInferEmbedding(ctx, []string{faqBase.Question})
			embedding := embeddings[0]
			ok := k.rumClient.RumUpsert(ctx, rumTableName, faqBase.Id, embedding, "", nil)
			if !ok {
				log.Errorf(ctx, "RumUpsert error. rumTable=%s, id=%d", rumTableName, faqBase.Id)
				return nil, errors.New("rum upsert failed")
			}
		}
	} else if shouldDeleteRum {
		//执行rum删除
		ok := k.rumClient.RumDelete(ctx, rumTableName, faqBase.Id, "")
		if !ok {
			log.Errorf(ctx, "RumDelete error. rumTable=%s, id=%d", rumTableName, faqBase.Id)
			return nil, errors.New("rum delete failed")
		}
	}

	if faqBase.Scene == string(conf.SearchTabFAQ) {
		service.ClearZhidaCache(ctx, faqBase.Question)
	}

	return faqBase, err
}

func (k OperationBaseManagementImpl) AddFaqBase(ctx context.Context, faqBases []*model.FaqBase) ([]*model.FaqBase, error) {
	for _, faqBase := range faqBases {
		if faqBase.StatusCode == model.OperationBaseStatusInit {
			faqBase.StatusCode = model.OperationBaseStatusOffline
		}
	}

	var ids = make([]int64, 0, len(faqBases))

	faqBasesArray := lo.Chunk(faqBases, insertMaxSize)
	// 分批写一下，太多会导致数据库抛异常
	for index, faqBasesChunk := range faqBasesArray {
		insertResult, err := k.faqBaseDao.Insert(ctx, faqBasesChunk)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "insert faq base error. index=%d", index)
			break
		}
		firstInsertId := insertResult.LastInsertedID - insertResult.AffectedRows + 1
		for i, staticBase := range faqBasesChunk {
			staticBase.Id = firstInsertId + int64(i)
			ids = append(ids, staticBase.Id)
		}
	}

	// createAt和updateAt是只读的，所以需要查一次
	faqBases, err := k.faqBaseDao.GetByIds(ctx, ids)
	if err != nil {
		return faqBases, err
	}

	createRumFaqBases := lo.Filter(faqBases, func(faqBase *model.FaqBase, _ int) bool {
		return slices.Contains(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType), conf.FaqMatchTypeEmbeddingSimilarity) &&
			faqBase.StatusCode == model.OperationBaseStatusOnline
	})
	questions := lo.Map(createRumFaqBases, func(faqBase *model.FaqBase, _ int) string {
		return faqBase.Question
	})

	// 生成embedding
	embeddings := k.bgeEmbeddingClient.BatchInferEmbedding(ctx, questions)

	sceneToRumTable := k.GetSceneToRumTableNameMap(ctx)
	for i, faqBase := range createRumFaqBases {
		rumTableName := sceneToRumTable[faqBase.Scene]
		ok := k.rumClient.RumUpsert(ctx, rumTableName, faqBase.Id, embeddings[i], "", nil)
		if !ok {
			log.Errorf(ctx, "RumUpsert error. rumTable=%s, id=%d", rumTableName, faqBase.Id)
			return nil, errors.New("rum upsert failed")
		}
	}

	for _, faqBase := range faqBases {
		if faqBase.Scene == string(conf.SearchTabFAQ) {
			service.ClearZhidaCache(ctx, faqBase.Question)
		}
	}

	return faqBases, nil
}

func (k OperationBaseManagementImpl) GetSceneToRumTableNameMap(ctx context.Context) map[string]string {
	scenes, _ := k.GetScenes(ctx)
	sceneToRumTable := map[string]string{}
	for _, sceneConfig := range scenes.FaqBaseSceneConfig {
		sceneToRumTable[sceneConfig.Name] = sceneConfig.RumTableName
	}

	return sceneToRumTable
}

func init() {
	DefaultOperationBaseManagementService = newOperationBaseManagementService()
	SceneToPbNameMap = make(map[string]string)
	for key, value := range tracingSceneMap {
		SceneToPbNameMap[value] = key
	}
}
