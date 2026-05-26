package ab

import (
	"fmt"

	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

// ======================================= 布谷实验平台 ab ======================================= //

// 搜索tab的实验接入按照下面的格式填写，参考注释和命名方式，接入之后把冷启的那个例子删了
func GetUniqueKey(abValue zlab.ZlabValue) string {
	return fmt.Sprintf("%s:%s", abValue.Key, abValue.Value)
}
func GetDefaultUniqueKey(abValue zlab.ZlabValue) string {
	return fmt.Sprintf("%s:%s", abValue.Key, abValue.DefaultValue)
}

// 冷启 cb2cf 实验，地址：https://data.in.zhihu.com/ab/owner/exp/11970043
var WarmUpCb2CfDefault = zlab.ZlabValue{Key: "rm_warmup_cb2cf", Value: "0", DefaultValue: "-1"}
var WarmUpCb2CfExp1 = zlab.ZlabValue{Key: "rm_warmup_cb2cf", Value: "1", DefaultValue: "-1"}
var WarmUpCb2CfExp2 = zlab.ZlabValue{Key: "rm_warmup_cb2cf", Value: "2", DefaultValue: "-1"}
var WarmUpCb2CfExp3 = zlab.ZlabValue{Key: "rm_warmup_cb2cf", Value: "3", DefaultValue: "-1"}

// 综搜&实体词模型升级实验，地址：https://data.in.zhihu.com/ab/owner/exp/36960014
var EntitySearchModelDefault = zlab.ZlabValue{Key: "ac_search_entity", Value: "0", DefaultValue: "-1"}
var EntitySearchModelExp1 = zlab.ZlabValue{Key: "ac_search_entity", Value: "1", DefaultValue: "-1"} // doubao1.6
var EntitySearchModelExp2 = zlab.ZlabValue{Key: "ac_search_entity", Value: "2", DefaultValue: "-1"} // qwen3-32b
var EntitySearchModelExp3 = zlab.ZlabValue{Key: "ac_search_entity", Value: "3", DefaultValue: "-1"} // qwen3-14b

// 直答夸克API召回迁移可信搜，https://data.in.zhihu.com/ab/owner/exp/37050097
var QuarkToKexinDefault = zlab.ZlabValue{Key: "ac_zhida_recall", Value: "0", DefaultValue: "-1"}
var QuarkToKexinExp1 = zlab.ZlabValue{Key: "ac_zhida_recall", Value: "1", DefaultValue: "-1"} // 直答夸克API召回迁移可信搜实验组

// 实体词模型升级实验，地址：https://data.in.zhihu.com/ab/owner/exp/36720581
var EntityFlashModelDefault = zlab.ZlabValue{Key: "ac_entityword", Value: "0", DefaultValue: "-1"}
var EntityFlashModelExp1 = zlab.ZlabValue{Key: "ac_entityword", Value: "1", DefaultValue: "-1"} // AA
var EntityFlashModelExp2 = zlab.ZlabValue{Key: "ac_entityword", Value: "2", DefaultValue: "-1"} // doubao1.6 flash

// 开启定时任务，参与 holdout 计算时使用，并且可以定制是否要进行邮件发送
func init() {
	var zlabValues = []zlab.ZlabValue{}
	job := zlab.NewHoldoutNoticeJob(zlabValues)
	job.Start()
}
