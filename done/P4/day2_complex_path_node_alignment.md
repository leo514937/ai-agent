# P4-Day2：复杂路径节点显式化

源文档： [../P4_graph_alignment_finalization_plan.md](../P4_graph_alignment_finalization_plan.md)

## 本日目标

- 把复杂路径从黑盒 `plan_execute_subgraph` 收口为显式节点组合
- 显式暴露 `planner_node`、`plan_validator`、`plan_executor`、`execute_plan_step`、`collect_step_result`、`complex_review`
- 让复杂任务的重规划和回退都能被图拓扑直接表达
- 让复杂路径真正成为“计划驱动的图”，而不是“嵌在单节点里的流程控制”

## 当前对应实现

- `plan_planner`、`plan_validator`、`step_executor`、`progress_checker`、`plan_reviewer` 已经具备能力底座
- 这些能力当前仍主要集中在 `plan_execute.py` 的黑盒流程里
- `replan`、`retry_step`、`degrade` 已经存在语义，但需要从 helper 级控制流提升为图级可见出口
- `complex_review` 已经有事件语义，需要成为复杂路径的稳定收口节点

## 本日要对齐的节点

- `planner_node`
- `plan_validator`
- `plan_executor`
- `execute_plan_step`
- `collect_step_result`
- `complex_review`
- `repair_answer`

## 必须避免的架构冗余

- 不要把步骤规划、步骤执行、结果汇总继续揉进一个大方法
- 不要让复杂路径在节点内部偷偷跳回主生成逻辑
- 不要把 `replan`、`retry_step`、`degrade` 处理藏在 helper 里
- 不要让计划执行链和标准检索链复用同一套隐式控制流
- 不要让复杂路径继续依赖旧的 `plan_execute_subgraph` 黑盒语义

## 完成标准

- 复杂路径的每个步骤可以被独立观察和测试
- `plan_validator`、`plan_executor`、`complex_review` 都有明确输入和输出
- `execute_plan_step` 与 `collect_step_result` 的事件和状态可追踪
- `retry_step`、`replan`、`degrade` 的出口是显式的，而不是在黑盒里发生
- `plan_executor` 内部只负责执行，不再承担最终收口职责
- `repair_answer` 可以从复杂路径中明确回流，但不能再把整个复杂路径变成不可见分支
- 复杂路径的回归测试可以直接验证计划分解、执行轮次和重规划行为
- 如果 `planner_node`、`plan_validator`、`plan_executor`、`execute_plan_step`、`collect_step_result`、`complex_review` 任何一个仍未显式落图，Day2 不算完成
