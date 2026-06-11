# P4 图编排最终对齐

源文档：

- [../arc_core.md](../arc_core.md)
- [../arc_detail.md](../arc_detail.md)

预计工期：3 天

## 目标

把 `P3` 之后已经具备的能力，最终收口到 `arc_core.md` / `arc_detail.md` 要求的显式图编排结构中。

P4 不是继续扩能力，而是做最后一次结构对齐：

- 标准路径节点化
- 复杂路径节点化
- 最终出口与兼容清理

## 这轮对齐的核心判断

当前实现的问题不是“能力不够”，而是“能力还分散在 helper、phase、adapter 和大节点里”。

P4 的目标是把这些能力变成图上可见、可追踪、可验证的节点，让最终结构和文档里的拓扑一一对应。

## 完成门槛

P4 只有在下面几条全部满足时才算完成：

- 前端链路已经补齐到 `request_legality -> illegal_request_response`、`query_safety -> safety_reject_response`、`query_merge_for_local_life -> merged_query_safety`、`top_level_intent_router -> identity_answer/capability_answer/direct_chat_answer/out_of_scope_response`
- `builder.py` 的主图节点和边已经改成 `arc_core.md` 对应的显式拓扑
- 标准路径、复杂路径、最终出口都不再依赖黑盒大节点来承接编排职责
- 每个 arc 节点都能在代码中找到明确的实现位置，而不是只在 helper、测试或注释里出现
- 图导出、黄金集、回归测试三者能同时证明结构已对齐
- 兼容层只保留临时过渡，不再是默认实现

## 这一阶段要解决什么

当前代码已经有了足够多的“功能能力”，但还存在两个问题：

- 许多能力还停留在 helper / phase / adapter 里，没有成为图上可见的独立节点
- 部分路径仍然靠大节点内的条件分支串起来，导致拓扑和职责边界不够清楚

P4 的目标就是把这两个问题一次性收口。

## 必须避免的架构冗余

- 不要再保留“能力有了但节点没拆开”的双轨实现
- 不要让 `route_gate` 继续承担修补和兜底
- 不要让 `compose_answer` 继续吸收验证、审查和回退职责
- 不要把复杂路径继续挂在一个黑盒 `plan_execute_subgraph` 里
- 不要在 P4 再引入新的平行主链路
- 不要把 `final_answer_safety`、`response_builder`、`persist_session`、`emit_final` 再折叠回一个收口大方法

## P4 结束时应该长什么样

- `hard_guard` / `clarification_or_reject` 在图上可见
- `resolve_target_shop -> build_answer_contract -> build_source_contract -> complexity_router` 这一段是稳定的前置链路
- 标准路径能明确看出 `rule_review -> select_required_sources -> rag_executor/tool_executor/recommendation_executor -> merge_or_rank -> contract_review`
- 复杂路径能明确看出 `planner_node -> plan_validator -> plan_executor -> execute_plan_step -> collect_step_result -> complex_review`
- 最终出口链路能明确看出 `final_answer_safety -> final_safety_fallback / response_builder -> persist_session -> emit_final`

## 分天文档

1. [day1_standard_path_node_alignment.md](./day1_standard_path_node_alignment.md)
2. [day2_complex_path_node_alignment.md](./day2_complex_path_node_alignment.md)
3. [day3_exit_and_cleanup.md](./day3_exit_and_cleanup.md)

## 完成标准

- 标准路径中的 `rule_review`、`select_required_sources`、`merge_or_rank`、`contract_review` 能显式落图
- 复杂路径中的 `planner_node`、`plan_validator`、`plan_executor`、`execute_plan_step`、`collect_step_result`、`complex_review` 能显式落图
- 最终出口、持久化和发射节点职责清楚，且与 `arc_core.md` / `arc_detail.md` 一致
- 图拓扑导出、黄金集和回归测试能直接证明“结构已经对齐”
