package halo

import (
	"runtime"
	"strings"
)

// inspired by https://github.com/sirupsen/logrus/pull/989

var (
	skipPackageNamesForCaller = map[string]struct{}{
		"git.in.zhihu.com/go/logrus":                {},
		"git.in.zhihu.com/go/base/telemetry/log":    {},
		"git.in.zhihu.com/go/base/telemetry/sentry": {},
	}
)

func GetFrames() (frames []runtime.Frame) {
	callerPcs := make([]uintptr, 100)
	numCallers := runtime.Callers(4, callerPcs)
	callersFrames := runtime.CallersFrames(callerPcs[:numCallers])

	for f, again := callersFrames.Next(); again; f, again = callersFrames.Next() {
		packageName, function := ParsePackage(f.Function)

		if packageName == "runtime" && function == "gopanic" {
			continue
		}

		var skip bool
		for skipPackageName := range skipPackageNamesForCaller {
			if strings.HasPrefix(packageName, skipPackageName) {
				skip = true
				break
			}
		}

		if !skip {
			frames = append(frames, f)
		}
	}
	return frames
}

func ParsePackage(fName string) (pack string, name string) {
	name = fName
	// We get this:
	//	runtime/debug.*T·ptrmethod
	// and want this:
	//  pack = runtime/debug
	//	name = *T.ptrmethod
	if idx := strings.LastIndex(name, "."); idx != -1 {
		pack = name[:idx]
		name = name[idx+1:]
	}
	name = strings.Replace(name, "·", ".", -1)
	return
}
