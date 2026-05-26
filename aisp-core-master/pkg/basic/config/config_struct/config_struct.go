package config_struct

type RuceneIndex struct {
	IndexName string `json:"index_name"`
}
type RuceneConfig struct {
	Urls        []string               `json:"urls"`
	ClusterName string                 `json:"cluster_name"`
	Indexes     map[string]RuceneIndex `json:"indexes"`
	Timeout     int64                  `json:"timeout"`
}

type RumConfig struct {
	Scheme         string `json:"scheme"`
	SearthHost     string `json:"search_host"`
	UpdateHost     string `json:"update_host"`
	GetHost        string `json:"get_host"`
	SearchPath     string `json:"search_path"`
	UpsertPath     string `json:"upsert_path"`
	DeletePath     string `json:"delete_path"`
	InfosPath      string `json:"infos_path"`
	GetPath        string `json:"get_path"`
	TimeoutDefault int64  `json:"timeout"`
	TimeoutHTTL    int64  `json:"timeout_high_ttl"`
}

type McpConfig struct {
	McpServers map[string]*struct {
		URL string `json:"url"`
	} `json:"mcpServers"`
}
