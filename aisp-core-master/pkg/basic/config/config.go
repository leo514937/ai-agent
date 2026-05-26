package conf

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config/config_struct"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var defaultAispConfig *AispConfig

type AispConfig struct {
	RumConfig *config_struct.RumConfig
	McpConfig *config_struct.McpConfig
}

func init() {
	rumConfig := &config_struct.RumConfig{}
	mcpConfig := &config_struct.McpConfig{}

	GenCommonConfig("rum_config.json", rumConfig)
	GenCommonConfig("mcp_config.json", mcpConfig)

	defaultAispConfig = &AispConfig{
		RumConfig: rumConfig,
		McpConfig: mcpConfig,
	}
}

func GenCommonConfig(path string, v interface{}) {
	err := util.FileUnmarshal(GetCommonConfigPath()+path, v)
	if err != nil {
		panic(err)
	}
}

func GetCommonConfigPath() string {
	return getCommonConfigPath().(string)
}

var getCommonConfigPath = util.Make(
	func() interface{} {
		var envPath = GetEnvPath()
		configPath := fmt.Sprintf("%s/pkg/basic/etc/%s/", env.GetAPPRoot(), envPath)
		log.WithField(context.TODO(), "config", "getCommonConfigPath").Infof(context.TODO(), "config path:"+configPath)

		return configPath
	},
)

// 结果只有两种，production or dev
func GetEnvPath() string {
	zaeEnv := env.RunEnv()
	log.WithField(context.TODO(), "config", "getEnvPath").Infof(context.TODO(), "ZAE_ENV = %s", zaeEnv)
	if zaeEnv == env.ProductionEnv {
		return env.ProductionEnv
	}
	return "dev"
}

func GetRumConfig() *config_struct.RumConfig {
	return defaultAispConfig.RumConfig
}

func GetMcpConfig() *config_struct.McpConfig {
	return defaultAispConfig.McpConfig
}
