package impl

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type PrometheusImpl struct {
	httpClient *util.HttpClient
}

var DefaultPrometheusImpl rpc.Prometheus

func init() {
	DefaultPrometheusImpl = NewPrometheusImpl()
}
func NewPrometheusImpl() rpc.Prometheus {
	return &PrometheusImpl{
		httpClient: util.NewHttpClient("", "", 1000*time.Millisecond),
	}
}

var clusterHostMap = map[string]string{
	rpc.ClusterTypePek02: "https://prometheus-hdd-pek02.pek01.in.zhihu.com",
	rpc.ClusterTypeTsn01: "https://infra-metric.tsn01.in.zhihu.com",
}

const url = "select/0/prometheus/api/v1/query"
const paramFmt = "query=klara_svc_meta_data{inference_service=\"%s\"}"
const defaultLevel = "default"

func (p *PrometheusImpl) GetModelMetric(ctx context.Context, isvcName string, cluster string) (*rpc.Metric, error) {
	requestUrl := fmt.Sprintf("%s/%s?%s", clusterHostMap[cluster], url, fmt.Sprintf(paramFmt, isvcName))
	res, err := p.httpClient.DoGet(ctx, requestUrl, nil)
	if err != nil {
		return nil, err
	}
	resp := rpc.PrometheusResponse{}
	err = json.Unmarshal(res, &resp)

	if resp.Data != nil && len(resp.Data.Result) > 0 && resp.Data.Result[0] != nil {
		return resp.Data.Result[0].Metric, nil
	}

	return nil, nil
}

func (p *PrometheusImpl) CacheGetModelLevel(ctx context.Context, isvcName string, cluster string) string {
	if cluster == "" {
		return defaultLevel
	}

	res := make(map[string]string, 1)
	key := fmt.Sprintf("%s:%s", isvcName, cluster)

	resource.RedisLocalCache.BatchGet(ctx, []string{key}, util.StringKeyGeneratorFunc,
		func(params interface{}) interface{} {
			paramStr := params.([]string)[0]
			paramSlice := strings.Split(paramStr, ":")
			if len(paramSlice) != 2 {
				return nil
			}
			metric, err := p.GetModelMetric(ctx, paramSlice[0], paramSlice[1])
			if metric == nil || err != nil {
				return nil
			}

			return map[string]string{
				paramStr: metric.Level,
			}
		}, &res, util.ModelLevelKeyOption)

	if res[key] == "" {
		return defaultLevel
	}
	return res[key]
}

var _ rpc.Prometheus = (*PrometheusImpl)(nil)
