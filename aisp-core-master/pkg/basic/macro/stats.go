package macro

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/env"
)

const AISPPrefix = "aisp-core"

const SUCCEED = "succeed"
const FAILED = "failed"
const CANCELED = "canceled"

const DEFAULT = "default"

var KlaraRequestCntStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.scene.%s.ab.%s.client.%s.traffic.%s.reference.%s.isvc.%s.namespace.%s.status.%s.code.%s.count"
var KlaraRequestFirstTimeStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.scene.%s.ab.%s.client.%s.traffic.%s.reference.%s.isvc.%s.namespace.%s.first_token.request_time"
var KlaraRequestTotalTimeStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.scene.%s.ab.%s.client.%s.traffic.%s.reference.%s.isvc.%s.namespace.%s.total.request_time"

var CommonStatsPrefix = env.GetAPPName() + "." + env.GetUnitName() + ".scene.%s.ab.%s.client.%s.traffic.%s.reference.%s"
var CommonErrorStatsPrefix = env.GetAPPName() + "." + env.GetUnitName() + ".scene.%s.error"

// todo: 为避免环比监控失效，双写原始打点，一天后删掉 @wangran
// OriginCommonStatsPrefix 适用于离线打点，例如 kafka 消息，无用户请求来源
var OriginCommonStatsPrefix = env.GetAPPName() + "." + env.GetUnitName() + ".scene.%s"
var OriginKlaraRequestCntStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.isvc.%s.namespace.%s.level.%s.status.%s.code.%d.count"
var OriginKlaraRequestFirstTimeStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.isvc.%s.namespace.%s.level.%s.first_token.request_time"
var OriginKlaraRequestTotalTimeStatsFmt = "span.app." + env.GetAPPName() + ".unit_name." + env.GetUnitName() + ".klara.isvc.%s.namespace.%s.level.%s.total.request_time"
