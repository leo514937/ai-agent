package env

import (
	"context"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const (
	unknown       = "unknown"
	ProductionEnv = "production"
)

func init() {
	_ = GetAPPName()
	_ = GetUnitName()
	_ = GetAPPRoot()
	_ = RunInZAE()
	_ = RunInZAEShadow()
	_ = RunOnline()
	_ = RunDev()
	_ = GetAPPVersion()
	_ = GetMRID()
}

var runDebugPtr *bool

func RunDebug() bool {
	if runDebugPtr != nil {
		return *runDebugPtr
	}
	modeEnv := os.Getenv("DEBUG_MODE")
	runDebug := len(modeEnv) > 0 && modeEnv != "0" && modeEnv != "false"
	runDebugPtr = &runDebug
	log.Infof(context.TODO(), "runDebug=%v", *runDebugPtr)
	return runDebug
}

var unitNamePtr *string

func GetUnitName() string {
	if unitNamePtr != nil {
		return *unitNamePtr
	}
	zaeUnitName := "ZAE_UNIT_NAME"
	unitName := os.Getenv(zaeUnitName)
	if len(unitName) == 0 || unitName == unknown {
		unitName = unknown
	}
	log.Infof(context.TODO(), "unitName=%v", unitName)
	unitNamePtr = &unitName
	return unitName
}

var appNamePtr *string

func GetAPPName() string {
	if appNamePtr != nil {
		return *appNamePtr
	}
	zaeUnitName := "ZAE_APP_NAME"
	appName := os.Getenv(zaeUnitName)
	if len(appName) == 0 || appName == unknown {
		appName = unknown
	}
	log.Infof(context.TODO(), "appName=%v", appName)
	appNamePtr = &appName
	return appName
}

var appRootPtr *string

func GetAPPRoot() string {
	if appRootPtr != nil {
		return *appRootPtr
	}
	zaeAppRoot := "ZAE_APP_ROOT"
	appRoot := os.Getenv(zaeAppRoot)
	if len(appRoot) == 0 || appRoot == unknown {
		appRoot = unknown
	}
	log.Infof(context.TODO(), "appRoot=%v", appRoot)
	appRootPtr = &appRoot
	return appRoot
}

// 是否在线上生产环境
var runInZAEPtr *bool

func RunInZAE() bool {
	if runInZAEPtr != nil {
		return *runInZAEPtr
	}
	unitName := GetUnitName()
	runInZAE := unitName != unknown && unitName != "" && unitName != "offline-rpc"
	runInZAEPtr = &runInZAE
	log.Infof(context.TODO(), "runInZAE=%v", *runInZAEPtr)
	return runInZAE
}

var runInZAEShadowPtr *bool

func RunInZAEShadow() bool {
	if runInZAEShadowPtr != nil {
		return *runInZAEShadowPtr
	}
	unitName := GetUnitName()
	// zae_shadow_container: 调试容器
	runInZAEShadow := unitName == "zae_shadow_container"
	runInZAEShadowPtr = &runInZAEShadow
	log.Infof(context.TODO(), "runInZAEShadow=%v", *runInZAEShadowPtr)
	return runInZAEShadow
}

var runOnlinePtr *bool

func RunOnline() bool { // 说明是在生产环境线上的容器里
	if runOnlinePtr != nil {
		return *runOnlinePtr
	}
	runOnline := RunInZAE() && !RunInZAEShadow() && !RunDebug() && RunEnv() == ProductionEnv
	runOnlinePtr = &runOnline
	log.Infof(context.TODO(), "runOnline=%v", runOnline)
	return runOnline
}

var runDevPtr *bool

func RunDev() bool {
	if runDevPtr != nil {
		return *runDevPtr
	}
	runDev := RunEnv() == "testing" || RunEnv() == "test"
	runDevPtr = &runDev
	return runDev
}

var runEnvPtr *string

func RunEnv() string {
	if runEnvPtr != nil {
		return *runEnvPtr
	}
	runEnv := os.Getenv("ZAE_ENV")
	log.Infof(context.TODO(), "runEnv=%v", runEnv)
	runEnvPtr = &runEnv
	return runEnv
}

var appVersionPtr *string

func GetAPPVersion() string {
	if appVersionPtr != nil {
		return *appVersionPtr
	}
	envName := "ZAE_APP_VERSION"
	envValue := os.Getenv(envName)
	if len(envValue) == 0 || envValue == unknown {
		envValue = unknown
	}
	log.Infof(context.TODO(), "%s=%v", envName, envValue)
	appVersionPtr = &envValue
	return envValue
}

var mrIDPtr *string

func GetMRID() string {
	if mrIDPtr != nil {
		return *mrIDPtr
	}
	envName := "ZAE_MR_ID"
	envValue := os.Getenv(envName)
	if len(envValue) == 0 || envValue == unknown {
		envName = unknown
	}
	log.Infof(context.TODO(), "%s=%v", envName, envValue)
	mrIDPtr = &envValue
	return envValue
}
