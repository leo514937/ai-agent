package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/expr-lang/expr"
	"github.com/spf13/cast"
)

// IfElseMultiConditionLogic 条件判断算子，支持if else 形式
// input[]：在reqContext中的字段名 string...
// output：无
type IfElseMultiConditionLogic struct {
	*logic.BaseLogic[entities.RequestContext]

	field string
}

func NewIfElseMultiConditionLogic(name string, config map[string]string) *IfElseMultiConditionLogic {
	res := &IfElseMultiConditionLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}

	res.RealDoFunc = res.empty

	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (q *IfElseMultiConditionLogic) chooseKey(ctx context.Context, reqCtx *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	expression := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionExpression)
	ifBranch := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionIfBranch)
	elseBranch := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionElseBranch)
	fields := make([]string, 0)
	for i := 0; i < q.GetInputSize(); i++ {
		fields = append(fields, q.GetInputName(i))
	}

	if q.executeCondition(ctx, reqCtx.RequestContext, expression, fields) {
		log.Infof(ctx, "%s enter if branch: %s", q.Name, ifBranch)
		return ifBranch
	} else {
		log.Infof(ctx, "%s enter else branch: %s", q.Name, elseBranch)
		return elseBranch
	}
}

func (q *IfElseMultiConditionLogic) empty(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	return nil
}

// 执行一个判断逻辑的表达式，返回执行结果, 例如：
func (q *IfElseMultiConditionLogic) executeCondition(ctx context.Context, reqCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	expression string, fields []string) bool {

	env := map[string]interface{}{}

	for _, field := range fields {
		fieldValue, _, _ := util.GetFieldValue(ctx, reqCtx, field)
		env[field] = fieldValue
	}

	program, err := expr.Compile(expression, expr.Env(env))
	if err != nil {
		log.Errorf(ctx, "expr compile err. expression: %s, err: %v", expression, err)
	}

	output, err := expr.Run(program, env)
	if err != nil {
		log.Errorf(ctx, "expr run err. expression: %s, err: %v", expression, err)
	}

	return cast.ToBool(output)
}
