package handler_zhihu

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	"github.com/samber/lo"
)

type ModelBillsHandler struct {
	rest.BaseHandler

	dorisInternal mysql.Connection
	modelDAO      dao.ModelDAO
	appDAO        dao.AppDAO
}

func NewModelBillsHandler() rest.Handler {
	return &ModelBillsHandler{
		dorisInternal: resource.DorisAISPInternal,
		modelDAO:      dao.DefaultModelDAO,
		appDAO:        dao.DefaultAppDAO,
	}
}

func (h *ModelBillsHandler) Get(ctx *rest.Context) (rest.Response, error) {
	appName := strings.TrimSpace(ctx.QueryArgumentWithFallback("app_name", ""))
	skuName := strings.TrimSpace(ctx.QueryArgumentWithFallback("sku_name", ""))
	bizLineName := strings.TrimSpace(ctx.QueryArgumentWithFallback("biz_line_name", ""))
	beginAts := ctx.Int64QueryArgument("begin_time", 0)
	endAts := ctx.Int64QueryArgument("end_time", 0)

	logger := log.WithFields(ctx, map[string]any{
		"func":          "handler.ModelCostHandler.Get",
		"app_name":      appName,
		"sku_name":      skuName,
		"biz_line_name": bizLineName,
	})

	var appNames []string
	if appName == "" && bizLineName != "" {
		apps, err := h.appDAO.ListApp(ctx, "", bizLineName)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to list apps")
			return nil, err
		}
		appNames = lo.Map(apps, func(item *model.App, _ int) string {
			return item.Name
		})
	} else if appName != "" {
		appNames = util.List(appName)
	}

	beginAtFormatted := time.Unix(beginAts, 0).Format("2006-01-02 15:04:05")
	endAtFormatted := time.Unix(endAts, 0).Format("2006-01-02 15:04:05")

	rows, err := h.dorisInternal.Query(ctx, fmt.Sprintf(`WITH
  total AS (
    SELECT
      sku_name,
      sum(input_token_count) AS input_token_count,
      sum(output_token_count) AS output_token_count,
	  sum(image_count) AS image_count
    FROM
      model_usage_agg
    WHERE
      begin_time BETWEEN '%s' AND '%s'
      AND end_time BETWEEN '%s' AND '%s'
      AND ('%s' = '' OR '%s' = sku_name)
    GROUP BY
      sku_name
  ),
  detail AS (
    SELECT
      caller_app,
	  sku_name,
      sum(input_token_count) AS input_token_count,
      sum(output_token_count) AS output_token_count,
	  sum(image_count) AS image_count,
      date_format (begin_time, '%%Y-%%m-%%d') AS begin_date
    FROM
      model_usage_agg
    WHERE
      begin_time BETWEEN '%s' AND '%s'
      AND end_time BETWEEN '%s' AND '%s'
      AND (%d = 0 OR caller_app IN ('%s'))
    GROUP BY
      date_format (begin_time, '%%Y-%%m-%%d'),
      caller_app,
      sku_name
  )
SELECT
  detail.caller_app,
  detail.sku_name,
  unix_timestamp(detail.begin_date),
  detail.input_token_count AS input_token_count,
  detail.output_token_count AS output_token_count,
  detail.image_count AS image_count,
  total.input_token_count AS total_input_token_count,
  total.output_token_count AS total_output_token_count,
  total.image_count AS total_image_count
FROM
  detail
  JOIN total ON detail.sku_name = total.sku_name
ORDER BY
  detail.caller_app,
  detail.begin_date,
  detail.sku_name
`, beginAtFormatted, endAtFormatted, beginAtFormatted, endAtFormatted, skuName, skuName, beginAtFormatted, endAtFormatted, beginAtFormatted, endAtFormatted, len(appNames), strings.Join(appNames, "','")))
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query model usage")
		return nil, err
	}
	defer rows.Close()

	records := make([]*record, 0, 5)
	for rows.Next() {
		var r record
		err := rows.Scan(&r.CallerApp, &r.SkuName, &r.Timestamp, &r.InputTokenCount, &r.OutputTokenCount, &r.ImageCount, &r.TotalInputTokenCount, &r.TotalOutputTokenCount, &r.TotalImageCount)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan model usage")
			return nil, err
		}
		records = append(records, &r)
	}

	skus, err := h.modelDAO.ListSkus(ctx)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to list skus")
		return nil, err
	}
	skuMap := lo.FromEntries(lo.Map(skus, func(item *model.Sku, _ int) lo.Entry[string, *model.Sku] {
		return lo.Entry[string, *model.Sku]{
			Key:   item.Name,
			Value: item,
		}
	}))

	bills := lo.Values(lo.MapValues(lo.GroupBy(records, func(record *record) int64 {
		return record.Timestamp
	}), func(records []*record, timestamp int64) *BillDTO {
		// records 代表同一个账期下的所有记录
		details := lo.Map(lo.Entries(lo.GroupBy(records, func(record *record) string {
			return record.SkuName
		})), func(item lo.Entry[string, []*record], _ int) *BillDetailItemDTO {
			// item 代表同一个账期下的同一个 sku 的所有记录
			detailItem := &BillDetailItemDTO{
				Name: GetSkuDisplayNameByName(ctx, item.Key),
			}
			skuModel := skuMap[item.Key]
			for _, record := range item.Value {
				var prices []*model.PriceItem
				if skuModel != nil {
					prices = skuModel.Prices
				}
				price := lo.Filter(prices, func(price *model.PriceItem, _ int) bool {
					return price.BeginAtMs < record.Timestamp*1000 && record.Timestamp*1000 < price.EndAtMs
				})
				var cost int64
				if len(price) == 0 {
					cost = 0
				} else {
					cost = price[0].ByInputTokenCount*record.InputTokenCount/1000000 +
						price[0].ByOutputTokenCount*record.OutputTokenCount/1000000 +
						price[0].ByImageCount*record.ImageCount/100 +
						price[0].ByTotalTokenQuota*(record.InputTokenCount+record.OutputTokenCount)*1000000/(record.TotalInputTokenCount+record.TotalOutputTokenCount+1)/1000000/1000000 +
						price[0].ByTotalImageQuota*record.ImageCount*1000000/(record.TotalImageCount+1)/1000000/1000000
				}
				detailItem.InputTokenCount += record.InputTokenCount
				detailItem.OutputTokenCount += record.OutputTokenCount
				detailItem.ImageCount += record.ImageCount
				detailItem.CentCount += cost
			}
			return detailItem
		})

		return &BillDTO{
			Date: time.Unix(timestamp, 0).Format("2006-01-02"),
			TotalCost: lo.SumBy(details, func(item *BillDetailItemDTO) int64 {
				return item.CentCount
			}),
			Detail: details,
		}
	}))

	sort.Slice(bills, func(i, j int) bool {
		return bills[i].Date > bills[j].Date
	})
	return ResponseSuccess(bills)
}

type ModelCostHandler struct {
	rest.BaseHandler

	dorisInternal mysql.Connection
	modelDAO      dao.ModelDAO
	appDAO        dao.AppDAO
}

func NewModelCostHandler() rest.Handler {
	return &ModelCostHandler{
		dorisInternal: resource.DorisAISPInternal,
		modelDAO:      dao.DefaultModelDAO,
		appDAO:        dao.DefaultAppDAO,
	}
}

func (h *ModelCostHandler) Get(ctx *rest.Context) (rest.Response, error) {
	appName := strings.TrimSpace(ctx.QueryArgumentWithFallback("app_name", ""))
	modelName := strings.TrimSpace(ctx.QueryArgumentWithFallback("sku_name", ""))
	bizLineName := strings.TrimSpace(ctx.QueryArgumentWithFallback("biz_line_name", ""))
	beginAts := ctx.Int64QueryArgument("begin_time", 0)
	endAts := ctx.Int64QueryArgument("end_time", 0)

	logger := log.WithFields(ctx, map[string]any{
		"func":          "handler.ModelCostHandler.Get",
		"app_name":      appName,
		"model_name":    modelName,
		"biz_line_name": bizLineName,
	})

	var appNames []string
	if appName == "" && bizLineName != "" {
		apps, err := h.appDAO.ListApp(ctx, "", bizLineName)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to list apps")
			return nil, err
		}
		appNames = lo.Map(apps, func(item *model.App, _ int) string {
			return item.Name
		})
	} else if appName != "" {
		appNames = util.List(appName)
	}

	beginAtFormatted := time.Unix(beginAts, 0).Format("2006-01-02 15:04:05")
	endAtFormatted := time.Unix(endAts, 0).Format("2006-01-02 15:04:05")

	rows, err := h.dorisInternal.Query(ctx, fmt.Sprintf(`WITH
  total AS (
    SELECT
      sku_name,
      sum(input_token_count) AS input_token_count,
      sum(output_token_count) AS output_token_count,
	  sum(image_count) AS image_count
    FROM
      model_usage_agg
    WHERE
      begin_time BETWEEN '%s' AND '%s'
      AND end_time BETWEEN '%s' AND '%s'
      AND ('%s' = '' OR '%s' = sku_name)
    GROUP BY
      sku_name
  ),
  detail AS (
    SELECT
      caller_app,
	  sku_name,
      sum(input_token_count) AS input_token_count,
      sum(output_token_count) AS output_token_count,
	  sum(image_count) AS image_count,
      date_format (begin_time, '%%Y-%%m-%%d') AS begin_date
    FROM
      model_usage_agg
    WHERE
      begin_time BETWEEN '%s' AND '%s'
      AND end_time BETWEEN '%s' AND '%s'
      AND (%d = 0 OR caller_app IN ('%s'))
    GROUP BY
      date_format (begin_time, '%%Y-%%m-%%d'),
      caller_app,
      sku_name
  )
SELECT
  detail.caller_app,
  detail.sku_name,
  unix_timestamp(detail.begin_date),
  detail.input_token_count AS input_token_count,
  detail.output_token_count AS output_token_count,
  detail.image_count AS image_count,
  total.input_token_count AS total_input_token_count,
  total.output_token_count AS total_output_token_count,
  total.image_count AS total_image_count
FROM
  detail
  JOIN total ON detail.sku_name = total.sku_name
ORDER BY
  detail.caller_app,
  detail.begin_date,
  detail.sku_name
`, beginAtFormatted, endAtFormatted, beginAtFormatted, endAtFormatted, modelName, modelName, beginAtFormatted, endAtFormatted, beginAtFormatted, endAtFormatted, len(appNames), strings.Join(appNames, "','")))
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query model usage")
		return nil, err
	}
	defer rows.Close()

	records := make([]*record, 0, 5)
	for rows.Next() {
		var r record
		err := rows.Scan(&r.CallerApp, &r.SkuName, &r.Timestamp, &r.InputTokenCount, &r.OutputTokenCount, &r.ImageCount, &r.TotalInputTokenCount, &r.TotalOutputTokenCount, &r.TotalImageCount)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan model usage")
			return nil, err
		}
		records = append(records, &r)
	}

	partitions := lo.GroupBy(records, func(item *record) string {
		return item.CallerApp
	})

	skus, err := h.modelDAO.ListSkus(ctx)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to list skus")
		return nil, err
	}
	skuMap := lo.FromEntries(lo.Map(skus, func(item *model.Sku, _ int) lo.Entry[string, *model.Sku] {
		return lo.Entry[string, *model.Sku]{
			Key:   item.Name,
			Value: item,
		}
	}))
	metrics := lo.MapValues(partitions, func(items []*record, _ string) []*PointDTO[CostPointValue] {
		points := lo.Map(items, func(item *record, _ int) *PointDTO[CostPointValue] {
			skuModel := skuMap[item.SkuName]
			var prices []*model.PriceItem
			if skuModel != nil {
				prices = skuModel.Prices
			}
			price := lo.Filter(prices, func(price *model.PriceItem, _ int) bool {
				return price.BeginAtMs < item.Timestamp*1000 && item.Timestamp*1000 < price.EndAtMs
			})
			if len(price) == 0 {
				return &PointDTO[CostPointValue]{
					Timestamp: item.Timestamp,
					Value:     CostPointValue{CentCount: 0},
				}
			}

			cost := price[0].ByInputTokenCount*item.InputTokenCount/1000000 +
				price[0].ByOutputTokenCount*item.OutputTokenCount/1000000 +
				price[0].ByImageCount*item.ImageCount/100 +
				price[0].ByTotalTokenQuota*(item.InputTokenCount+item.OutputTokenCount)*1000000/(item.TotalInputTokenCount+item.TotalOutputTokenCount+1)/1000000/1000000 +
				price[0].ByTotalImageQuota*item.ImageCount*1000000/(item.TotalImageCount+1)/1000000/1000000
			return &PointDTO[CostPointValue]{
				Timestamp: item.Timestamp,
				Value:     CostPointValue{CentCount: cost},
			}
		})
		subPartitions := lo.PartitionBy(points, func(item *PointDTO[CostPointValue]) int64 {
			return item.Timestamp
		})
		points = lo.Map(subPartitions, func(items []*PointDTO[CostPointValue], _ int) *PointDTO[CostPointValue] {
			var sum int64
			for _, item := range items {
				sum += item.Value.CentCount
			}
			return &PointDTO[CostPointValue]{
				Timestamp: items[0].Timestamp,
				Value:     CostPointValue{CentCount: sum},
			}
		})
		return points
	})

	// 查询业务线
	currAppNames := lo.MapToSlice(metrics, func(key string, _ []*PointDTO[CostPointValue]) string {
		return key
	})
	allApps, _ := h.appDAO.ListAllAppsByNames(ctx, currAppNames)
	appDepartmentDict := lo.SliceToMap(allApps, func(item *model.App) (string, string) {
		return item.Name, item.OwnerBizLineName
	})

	return ResponseSuccess(normalizeMetrics(lo.Map(lo.Entries(metrics), func(item lo.Entry[string, []*PointDTO[CostPointValue]], index int) *MetricDTO[CostPointValue] {
		return &MetricDTO[CostPointValue]{
			Name:       item.Key,
			Department: appDepartmentDict[item.Key],
			Points:     item.Value,
		}
	})))
}

type PointDTO[V any] struct {
	Timestamp int64 `json:"timestamp"`
	Value     V     `json:"value"`
}

type MetricDTO[V any] struct {
	Name       string         `json:"name"`
	Department string         `json:"department"`
	Points     []*PointDTO[V] `json:"points"`
}

type BillDTO struct {
	Date      string               `json:"date"`
	TotalCost int64                `json:"total_cost"`
	Detail    []*BillDetailItemDTO `json:"detail"`
}

type BillDetailItemDTO struct {
	Name             string `json:"name"`
	InputTokenCount  int64  `json:"input_token_count"`
	OutputTokenCount int64  `json:"output_token_count"`
	ImageCount       int64  `json:"image_count"`
	CentCount        int64  `json:"cent_count"`
}

type record struct {
	CallerApp             string `json:"caller_app"`
	SkuName               string `json:"sku_name"`
	Timestamp             int64  `json:"begin_date"`
	InputTokenCount       int64  `json:"input_token_count"`
	OutputTokenCount      int64  `json:"output_token_count"`
	ImageCount            int64  `json:"image_count"`
	TotalInputTokenCount  int64  `json:"total_input_token_count"`
	TotalOutputTokenCount int64  `json:"total_output_token_count"`
	TotalImageCount       int64  `json:"total_image_count"`
}

type ModelUsageHandler struct {
	rest.BaseHandler

	dorisInternal mysql.Connection
	appDAO        dao.AppDAO
	modelDAO      dao.ModelDAO
}

func NewModelUsageHandler() rest.Handler {
	return &ModelUsageHandler{
		dorisInternal: resource.DorisAISPInternal,
		appDAO:        dao.DefaultAppDAO,
		modelDAO:      dao.DefaultModelDAO,
	}
}

func (h *ModelUsageHandler) Get(ctx *rest.Context) (rest.Response, error) {
	appName := strings.TrimSpace(ctx.QueryArgumentWithFallback("app_name", ""))
	skuName := strings.TrimSpace(ctx.QueryArgument("sku_name"))
	bizLineName := strings.TrimSpace(ctx.QueryArgumentWithFallback("biz_line_name", ""))
	beginAts := ctx.Int64QueryArgument("begin_time", 0)
	endAts := ctx.Int64QueryArgument("end_time", 0)

	logger := log.WithFields(ctx, map[string]any{
		"func":     "handler.ModelCostHandler.Get",
		"app_name": appName,
	})

	beginAtFormatted := time.Unix(beginAts, 0).Format("2006-01-02 15:04:05")
	endAtFormatted := time.Unix(endAts, 0).Format("2006-01-02 15:04:05")

	var appNames []string
	if appName == "" && bizLineName != "" {
		apps, err := h.appDAO.ListApp(ctx, "", bizLineName)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to list apps")
			return nil, err
		}
		appNames = lo.Map(apps, func(item *model.App, _ int) string {
			return item.Name
		})
	} else if appName != "" {
		appNames = util.List(appName)
	}

	rows, err := h.dorisInternal.Query(ctx, fmt.Sprintf(`
WITH
  detail AS (
    SELECT
      caller_app,
	  sku_name,
      sum(input_token_count) AS input_token_count,
      sum(output_token_count) AS output_token_count,
      sum(image_count) AS image_count,
      date_format (begin_time, '%%Y-%%m-%%d') AS begin_date
    FROM
      model_usage_agg
    WHERE
      begin_time BETWEEN '%s' AND '%s'
      AND end_time BETWEEN '%s' AND '%s'
      AND ('' = '%s' OR sku_name = '%s')
      AND (%d = 0 OR caller_app IN ('%s'))
    GROUP BY
      date_format (begin_time, '%%Y-%%m-%%d'),
      caller_app,
      sku_name
  )
SELECT
  detail.caller_app,
  detail.sku_name,
  unix_timestamp(detail.begin_date),
  detail.input_token_count AS input_token_count,
  detail.output_token_count AS output_token_count,
  detail.image_count AS image_count
FROM
  detail
ORDER BY
  detail.caller_app,
  detail.sku_name,
  detail.begin_date
`, beginAtFormatted, endAtFormatted, beginAtFormatted, endAtFormatted, skuName, skuName, len(appNames), strings.Join(appNames, "','")))
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query model usage")
		return nil, err
	}
	defer rows.Close()

	records := make([]*record, 0, 5)
	for rows.Next() {
		var r record
		err := rows.Scan(&r.CallerApp, &r.SkuName, &r.Timestamp, &r.InputTokenCount, &r.OutputTokenCount, &r.ImageCount)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan model usage")
			return nil, err
		}
		records = append(records, &r)
	}

	partitions := lo.GroupBy(records, func(item *record) lo.Tuple2[string, string] {
		return lo.Tuple2[string, string]{item.CallerApp, item.SkuName}
	})

	metricsInput := lo.MapValues(partitions, func(items []*record, _ lo.Tuple2[string, string]) []*PointDTO[UsagePointValue] {
		points := make([]*PointDTO[UsagePointValue], 0, len(items))
		for _, item := range items {
			points = append(points, &PointDTO[UsagePointValue]{
				Timestamp: item.Timestamp,
				Value:     UsagePointValue{Count: item.InputTokenCount},
			})
		}
		return points
	})
	metricsOutput := lo.MapValues(partitions, func(items []*record, _ lo.Tuple2[string, string]) []*PointDTO[UsagePointValue] {
		points := make([]*PointDTO[UsagePointValue], 0, len(items))
		for _, item := range items {
			points = append(points, &PointDTO[UsagePointValue]{
				Timestamp: item.Timestamp,
				Value:     UsagePointValue{Count: item.OutputTokenCount},
			})
		}
		return points
	})
	metricsImage := lo.MapValues(partitions, func(items []*record, _ lo.Tuple2[string, string]) []*PointDTO[UsagePointValue] {
		points := make([]*PointDTO[UsagePointValue], 0, len(items))
		for _, item := range items {
			points = append(points, &PointDTO[UsagePointValue]{
				Timestamp: item.Timestamp,
				Value:     UsagePointValue{Count: item.ImageCount},
			})
		}
		return points
	})

	metrics := append(append(lo.Map(lo.Entries(metricsInput), func(item lo.Entry[lo.Tuple2[string, string], []*PointDTO[UsagePointValue]], index int) *MetricDTO[UsagePointValue] {
		name := fmt.Sprintf("%s:%s:IN", item.Key.A, GetSkuDisplayNameByName(ctx, item.Key.B))
		if appName != "" {
			name = fmt.Sprintf("%s:IN", GetSkuDisplayNameByName(ctx, item.Key.B))
		}
		return &MetricDTO[UsagePointValue]{
			Name:   name,
			Points: item.Value,
		}
	}), lo.Map(lo.Entries(metricsOutput), func(item lo.Entry[lo.Tuple2[string, string], []*PointDTO[UsagePointValue]], index int) *MetricDTO[UsagePointValue] {
		name := fmt.Sprintf("%s:%s:OUT", item.Key.A, GetSkuDisplayNameByName(ctx, item.Key.B))
		if appName != "" {
			name = fmt.Sprintf("%s:OUT", GetSkuDisplayNameByName(ctx, item.Key.B))
		}
		return &MetricDTO[UsagePointValue]{
			Name:   name,
			Points: item.Value,
		}
	})...), lo.Map(lo.Entries(metricsImage), func(item lo.Entry[lo.Tuple2[string, string], []*PointDTO[UsagePointValue]], index int) *MetricDTO[UsagePointValue] {
		name := fmt.Sprintf("%s:%s:IMAGE", item.Key.A, GetSkuDisplayNameByName(ctx, item.Key.B))
		if appName != "" {
			name = fmt.Sprintf("%s:IMAGE", GetSkuDisplayNameByName(ctx, item.Key.B))
		}
		return &MetricDTO[UsagePointValue]{
			Name:   name,
			Points: item.Value,
		}
	})...)
	sort.Slice(metrics, func(i, j int) bool {
		return metrics[i].Name < metrics[j].Name
	})
	return ResponseSuccess(normalizeMetrics(metrics))
}

type UsagePointValue struct {
	Count int64 `json:"count"`
}

type CostPointValue struct {
	CentCount int64 `json:"cent_count"`
}

func normalizeMetrics[P any](metrics []*MetricDTO[P]) []*MetricDTO[P] {
	timestampSet := map[int64]struct{}{}
	for _, metric := range metrics {
		for _, point := range metric.Points {
			timestampSet[point.Timestamp] = struct{}{}
		}
	}

	metricPointMap := map[string]map[int64]P{}
	for _, metric := range metrics {
		metricPointMap[metric.Name] = map[int64]P{}
		for _, point := range metric.Points {
			metricPointMap[metric.Name][point.Timestamp] = point.Value
		}
	}

	timestamps := lo.Keys(timestampSet)
	sort.Slice(timestamps, func(i, j int) bool {
		return timestamps[i] < timestamps[j]
	})

	for _, metric := range metrics {
		metric.Points = make([]*PointDTO[P], 0, len(timestamps))
		for _, timestamp := range timestamps {
			if point, ok := metricPointMap[metric.Name][timestamp]; !ok {
				metric.Points = append(metric.Points, &PointDTO[P]{
					Timestamp: timestamp,
					Value:     metricPointMap[metric.Name][timestamp],
				})
			} else {
				metric.Points = append(metric.Points, &PointDTO[P]{
					Timestamp: timestamp,
					Value:     point,
				})
			}
		}
	}
	return metrics
}
