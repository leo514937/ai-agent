package prompt

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

func TestOriginQueryPromptBaseLogic_queryPrompt(t *testing.T) {
	type args = struct {
		config          map[string]string
		initContextFunc func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item])
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "test1",
			args: args{
				config: map[string]string{
					conf.ConfigPrompt:      "<用户>你叫知海图，是由知乎和面壁智能联合研发的大型语言模型。\n你的知识库截止至2022年4月，当前时间是{{.Now}}。<{{.Query}}><AI>",
					conf.ConfigPromptID:    "1004",
					conf.ConfigInputNames:  graph_macro.ZagKeyQueryText,
					conf.ConfigOutputNames: graph_macro.ZagKeyGeneratedPrompt,
				},
				initContextFunc: func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
					reqContext.DataMap().SetString(graph_macro.ZagKeyQueryText, "你好")
				},
			},
			want: fmt.Sprintf("<用户>你叫知海图，是由知乎和面壁智能联合研发的大型语言模型。\n你的知识库截止至2022年4月，当前时间是%s。<你好><AI>", time.Now().Format("2006年1月2日")),
		},
	}

	ctx := context.Background()

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			logic := NewQueryPromptBaseLogic(tt.name, tt.args.config)
			reqContext := data_frame.NewRequestContext[entities.RequestContext, entities.User, entities.Item]()
			tt.args.initContextFunc(reqContext)
			err := logic.queryPrompt(ctx, reqContext)
			if err != nil {
				t.Error(err.Error())
			}

			got, ok := reqContext.DataMap().GetString(graph_macro.ZagKeyGeneratedPrompt)

			if !ok {
				t.Error("no value")
			}

			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("queryPrompt = %v, want %v", got, tt.want)
			}
		})
	}
}
