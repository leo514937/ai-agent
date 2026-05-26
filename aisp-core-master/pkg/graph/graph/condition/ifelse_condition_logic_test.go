package condition

import (
	"context"
	"reflect"
	"testing"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

func TestIfElseConditionLogic_chooseKey(t *testing.T) {

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
			name: "test_redline_condition_true",
			args: args{
				config: map[string]string{
					conf.ConditionCondition:  "!=",
					conf.ConditionCompareTo:  `""`,
					conf.ConditionIfBranch:   entities.Break,
					conf.ConditionElseBranch: entities.Normal,
					conf.ConfigInputNames:    graph_macro.ZagKeyRedLineAnswer,
				},
				initContextFunc: func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
					reqContext.DataMap().SetString(context.TODO(), graph_macro.ZagKeyRedLineAnswer, "台湾，是中华人民共和国省级行政区。台湾是中华人民共和国的神圣领土的一部分。中国的主权和领土完整不容侵犯和分割，完成统一祖国的大业是包括台湾同胞在内的全中国人民的神圣职责。")
				},
			},
			want: entities.Break,
		},
		{
			name: "test_redline_condition_false",
			args: args{
				config: map[string]string{
					conf.ConditionCondition:  "!=",
					conf.ConditionCompareTo:  `""`,
					conf.ConditionIfBranch:   entities.Break,
					conf.ConditionElseBranch: entities.Normal,
					conf.ConfigInputNames:    graph_macro.ZagKeyRedLineAnswer,
				},
				initContextFunc: func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
				},
			},
			want: entities.Normal,
		},
		{
			name: "test_security_review_condition_true",
			args: args{
				config: map[string]string{
					conf.ConditionCondition:  "==",
					conf.ConditionCompareTo:  "true",
					conf.ConditionIfBranch:   entities.Normal,
					conf.ConditionElseBranch: entities.Break,
					conf.ConfigInputNames:    graph_macro.ZagKeyQuerySecurityReviewIsAvailable,
				},
				initContextFunc: func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
					reqContext.DataMap().SetBool(context.TODO(), graph_macro.ZagKeyQuerySecurityReviewIsAvailable, true)
				},
			},
			want: entities.Normal,
		},
		{
			name: "test_security_review_condition_false",
			args: args{
				config: map[string]string{
					conf.ConditionCondition:  "==",
					conf.ConditionCompareTo:  "true",
					conf.ConditionIfBranch:   entities.Normal,
					conf.ConditionElseBranch: entities.Break,
					conf.ConfigInputNames:    graph_macro.ZagKeyQuerySecurityReviewIsAvailable,
				},
				initContextFunc: func(reqContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
					reqContext.DataMap().SetBool(context.TODO(), graph_macro.ZagKeyQuerySecurityReviewIsAvailable, false)
				},
			},
			want: entities.Break,
		},
	}

	ctx := context.Background()

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			logic := NewIfElseConditionLogic(tt.name, tt.args.config)
			reqContext := data_frame.NewRequestContext[entities.RequestContext, entities.User, entities.Item]()
			tt.args.initContextFunc(reqContext)
			got := logic.chooseKey(ctx, data_frame.NewFrameworkContext(reqContext))

			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("queryPrompt = %v, want %v", got, tt.want)
			}
		})
	}

}
