package failsafe

import (
	"context"
	"fmt"
	"runtime"
	"strings"

	"git.in.zhihu.com/go/cafe/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/getsentry/raven-go"
)

// 带有熔断功能的 failsafe
// 监控平台 https://gf.in.zhihu.com/d/IB6DRCi7z/tong-jiang-ji
// 统一打点
// aisp-core.{app_name}.{unit_name}.failsafe.{model_name}.{file_name}.{func_name}.fallback.*.count 被降级数
// aisp-core.{app_name}.{unit_name}.failsafe.{model_name}.{file_name}.{func_name}.run.*.count 请求数
// aisp-core.{app_name}.{unit_name}.failsafe.{model_name}.{file_name}.{func_name}.run.success.count 成功调用次数
// aisp-core.{app_name}.{unit_name}.failsafe.{model_name}.{file_name}.{func_name}.circuit.is_open 熔断器开启状态

// 自动拼装打点名称
// model_name 打点分类 如:（rpc/dao）
// file_name 函数所在文件名,  (.go 会替换成 _go)
// func_name 函数名称, 调用 failsafe 方法名称
func getFailSafeStatsdName(modelName string) string {
	pc, file, _, _ := runtime.Caller(2)

	funcName := "unknown_func"
	funcNames := strings.Split(runtime.FuncForPC(pc).Name(), ".")
	if len(funcNames) > 0 {
		funcName = funcNames[len(funcNames)-1]
	}
	fileName := "unknown_file"
	fileNames := strings.Split(file, "/")
	if len(fileNames) > 0 {
		fileName = fileNames[len(fileNames)-1]
	}

	modelName = strings.Replace(modelName, ".", "_", -1)
	fileName = strings.Replace(fileName, ".", "_", -1)
	funcName = strings.Replace(funcName, ".", "_", -1)

	return fmt.Sprintf("%s.%s.%s.failsafe.%s.%s.%s", macro.AISPPrefix, env.GetAPPName(), env.GetUnitName(), modelName, fileName, funcName)
}

func defaultFallbackFunc(ctx context.Context, err error) error {
	exception := raven.NewException(err, raven.NewStacktrace(1, 3, raven.IncludePaths()))
	log.Errorf(ctx, "%s", util.ExceptionToString(exception))
	return err
}

func DefaultRPCCircuitBreakerFailSafe(ctx context.Context, runFunc failsafe.RunFunc) {
	_ = failsafe.Execute(ctx, getFailSafeStatsdName("rpc"), runFunc, defaultFallbackFunc)
}
