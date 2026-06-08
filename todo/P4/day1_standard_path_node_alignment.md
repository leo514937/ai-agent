# P4-Day1：前端与标准路径节点显式化

源文档： [../P4_graph_alignment_finalization_plan.md](../P4_graph_alignment_finalization_plan.md)

## 本日目标

- 把前端合法性、安全、意图分流和直答分支显式拆出来
- 把标准路径的审查和合并节点显式拆出来
- 让 `rule_review`、`select_required_sources`、`merge_or_rank`、`contract_review` 成为清晰的图节点语义
- 从 `compose_answer` 中移出会影响标准路径判断的逻辑
- 把“标准路径只做标准路径该做的事”这件事落实到图上

## 当前对应实现

- `request_legality` / `illegal_request_response` 目前由 `build_initial_routing_decision` 里的 `check_request_legality` 分支承担
- `query_safety` / `safety_reject_response` 目前由 `build_initial_routing_decision` 里的 `check_hard_guard` 分支承担
- `query_merge_for_local_life` / `merged_query_safety` 目前由 `build_initial_routing_decision` 里的 `merge_local_life_query_context` 分支承担
- `top_level_intent_router` 目前由 `build_initial_routing_decision` 里的 `route_top_level_intent` 分支承担
- `identity_answer`、`capability_answer`、`direct_chat_answer`、`out_of_scope_response` 目前被折叠进 `build_initial_routing_decision` 的路由结果和后续大节点处理
- `rule_review` 目前大部分语义散落在 `phase7_compose` 和 `stages_back_core` 里
- `select_required_sources` 的能力分布在 `stages_front_b`、`graphs.py` 和标准路径分流代码中
- `rag_executor`、`tool_executor`、`recommendation_executor` 已有能力底座，但仍需要显式成图
- `merge_or_rank` 的逻辑目前更多是 helper 组合，而不是独立节点
- `contract_review` 仍然偏收口 helper，需要从最终答案组装逻辑里拆出去

## 本日要对齐的节点

- `request_legality`
- `illegal_request_response`
- `query_safety`
- `safety_reject_response`
- `query_merge_for_local_life`
- `merged_query_safety`
- `top_level_intent_router`
- `identity_answer`
- `capability_answer`
- `direct_chat_answer`
- `out_of_scope_response`
- `rule_review`
- `select_required_sources`
- `rag_executor`
- `tool_executor`
- `recommendation_executor`
- `merge_or_rank`
- `contract_review`
- `repair_answer`
- `final_with_limitations`

## 必须避免的架构冗余

- 不要把标准路径的校验、修正、回退继续堆在 `compose_answer`
- 不要让 `route_gate` 继续承担标准路径的业务修补
- 不要让 helper 函数继续充当隐式节点
- 不要再用旧的 `plan_execute_subgraph` 语义覆盖标准路径
- 不要让标准路径和复杂路径共享一套看不见的回退逻辑

## 完成标准

- `request_legality`、`query_safety`、`query_merge_for_local_life`、`top_level_intent_router` 以及它们的直答/拒绝分支都能显式落图
- 标准路径可以按节点逐段追踪
- `rule_review` 只处理规则审查，不再混入编排修补
- `select_required_sources` 只负责源选择与分流
- `rag_executor` / `tool_executor` / `recommendation_executor` 的调用边界清楚
- `merge_or_rank` 只负责证据/候选合并与排序
- `contract_review` 只负责最终审查、retry / repair / degrade 决策
- `repair_answer` 和 `final_with_limitations` 作为明确出口存在，不再和主生成路径混写
- 标准路径的回归测试能直接验证这些节点的存在和顺序
- 如果 `rule_review`、`select_required_sources`、`merge_or_rank`、`contract_review` 任何一个还没有成为可见图节点，Day1 不算完成
