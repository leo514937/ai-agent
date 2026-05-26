package entities

type CaseConf struct {
	ExpName      string                       `json:"exp_name"`
	ConfigMap    map[string]map[string]string `json:"config_map"`
	AbParamValue map[string]map[string]string `json:"ab_param_value"`
}
