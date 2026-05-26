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

// IfElseConditionLogic 条件判断算子，支持if else 形式
// input[0]：在reqContext中的字段名 string
// output：无
type IfElseConditionLogic struct {
	*logic.BaseLogic[entities.RequestContext]

	field string
}

func NewIfElseConditionLogic(name string, config map[string]string) *IfElseConditionLogic {
	res := &IfElseConditionLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}

	res.RealDoFunc = res.empty

	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (q *IfElseConditionLogic) chooseKey(ctx context.Context, reqCtx *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	condition := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionCondition)
	compareTo := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionCompareTo)
	ifBranch := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionIfBranch)
	elseBranch := reqCtx.RequestContext.GetBizContext().GetLogicConfig(q.GetName(), conf.ConditionElseBranch)
	fieldName := q.GetInputName(0)
	if executeCondition(ctx, reqCtx.RequestContext, fieldName, condition, compareTo) {
		log.Infof(ctx, "%s enter if branch: %s", q.Name, ifBranch)
		return ifBranch
	} else {
		log.Infof(ctx, "%s enter else branch: %s", q.Name, ifBranch)
		return elseBranch
	}
}

func (q *IfElseConditionLogic) empty(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	return nil
}

// 执行一个判断逻辑的表达式，返回执行结果, 例如：
func executeCondition(ctx context.Context, reqCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	fieldName string, condition string, compareTo string) bool {
	value, _, ok := util.GetFieldValue(ctx, reqCtx, fieldName)
	if !ok {
		log.Error(ctx, "get field value error. field=", fieldName)
		return false
	}

	env := map[string]interface{}{
		"value": value,
	}

	code := "value " + condition + compareTo

	program, err := expr.Compile(code, expr.Env(env))
	if err != nil {
		log.Errorf(ctx, "expr compile err. expression: %s, err: %v", code, err)
	}

	output, err := expr.Run(program, env)
	if err != nil {
		log.Errorf(ctx, "expr run err. expression: %s, err: %v", code, err)
	}

	return cast.ToBool(output)
}
