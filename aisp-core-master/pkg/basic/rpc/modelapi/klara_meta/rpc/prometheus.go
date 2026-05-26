package rpc

import (
	"context"
)

type Prometheus interface {
	GetModelMetric(ctx context.Context, isvcName string, cluster string) (*Metric, error)
	CacheGetModelLevel(ctx context.Context, isvcName string, cluster string) string
}

const (
	ClusterTypeTsn01 string = "tsn01"
	ClusterTypePek02 string = "pek02"
)

type Metric struct {
	App                                  string `json:"app"`
	Business                             string `json:"business"`
	BusinessLine                         string `json:"business_line"`
	BusinessTeam                         string `json:"business_team"`
	DestinationCanonicalService          string `json:"destination_canonical_service"`
	DestinationServiceName               string `json:"destination_service_name"`
	GpuSeries                            string `json:"gpu_series"`
	Idc                                  string `json:"idc"`
	InferenceService                     string `json:"inference_service"`
	Instance                             string `json:"instance"`
	Job                                  string `json:"job"`
	K8sCluster                           string `json:"k8s_cluster"`
	KubernetesNamespace                  string `json:"kubernetes_namespace"`
	KubernetesPodName                    string `json:"kubernetes_pod_name"`
	LabelServingKserveIoInferenceService string `json:"label_serving_kserve_io_inferenceservice"`
	Level                                string `json:"level"`
	Namespace                            string `json:"namespace"`
	Owner                                string `json:"owner"`
	PlatformApp                          string `json:"platform_app"`
	PodTemplateHash                      string `json:"pod_template_hash"`
	PrimaryResourcePool                  string `json:"primary_resource_pool"`
	Prometheus                           string `json:"prometheus"`
	Redeploy                             string `json:"redeploy"`
	Rollout                              string `json:"rollout"`
	ServiceType                          string `json:"service_type"`
	ServingKserveIoInferenceService      string `json:"serving_kserve_io_inferenceservice"`
	UserId                               string `json:"user_id"`
	ZaeApp                               string `json:"zae_app"`
}

type Value struct {
	Timestamp int64  `json:"timestamp"`
	Value     string `json:"value"`
}

type Result struct {
	Metric *Metric `json:"metric"`
	Value  *Value  `json:"value"`
}

type Data struct {
	ResultType string    `json:"resultType"`
	Result     []*Result `json:"result"`
}

type Stats struct {
	SeriesFetched     string `json:"seriesFetched"`
	ExecutionTimeMsec int    `json:"executionTimeMsec"`
}

type PrometheusResponse struct {
	Status    string `json:"status"`
	IsPartial bool   `json:"isPartial"`
	Data      *Data  `json:"data"`
	Stats     *Stats `json:"stats"`
}
