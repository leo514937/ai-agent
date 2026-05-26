package offline

import (
	"flag"
	"fmt"
	"os"

	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/bundle"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type bundleFunc func() cafe.Bundle

var taskMap = map[string]struct {
	introduce string
	bundles   []bundleFunc
}{
	"digital_author_index_change": {
		introduce: "数字分身索引更新",
		bundles: []bundleFunc{
			bundle.DigitalAuthorIndexChangeProcessBundle,
		},
	},
	"prefab_word_change": {
		introduce: "预制词更新",
		bundles: []bundleFunc{
			bundle.PrefabWordChangeProcessBundle,
		},
	},
	"prefab_word_change_v2": {
		introduce: "预制词增删改同步实时流",
		bundles: []bundleFunc{
			bundle.PrefabWordV2ChangeProcessBundle,
			bundle.HotEventIndexProcessBundle,
		},
	},
	"zhida_outsite_index": {
		introduce: "直达站外内容索引写入",
		bundles: []bundleFunc{
			bundle.ZhidaOutSiteIndexProcessBundle,
		},
	},
	"content_activity": {
		introduce: "内容平台内容分更新",
		bundles: []bundleFunc{
			bundle.ContentActivityProcessBundle,
		},
	},
	"paper_analysis_index": {
		introduce: "学术搜索内容解析",
		bundles: []bundleFunc{
			bundle.DocumentParsingProcessBundle,
		},
	},
	"crawler_webpage_index": {
		introduce: "自建搜索引擎索引构建",
		bundles: []bundleFunc{
			bundle.CrawlerWebpageIndexProcessBundle,
		},
	},
}

func Main(argsIndex int) {
	txn, ctx := log.StartTransaction("offline")
	defer txn.End(ctx)

	taskName := flag.String("task_name", "", "task_name")
	_ = flag.CommandLine.Parse(os.Args[argsIndex:])

	if *taskName == "content_activity" {
		resources.Init(graph_constant.ApiStreamChat)
	}

	task, exist := taskMap[*taskName]

	if !exist {
		panic(fmt.Sprintf("not such task: %s", *taskName))
	}

	app := cafe.NewApplication(cafe.WithProfiler(6060))

	for _, b := range task.bundles {
		app.AddBundle(b())
	}

	app.Run()

}
