# Phase 8 ExplorationPlanningWorkflow 验收报告

## 结论

- 结果：PASS
- 范围：仅完成 Phase 8 的最小独立 `ExplorationPlanningWorkflow`
- 结论：可以进入 Phase 9

## 本轮完成内容

- 新增 `local_life_agent/engine/workflows/exploration_planning_workflow.py`
- 在 `local_life_agent/engine/workflow_registry.py` 中把 `exploration_planning` 从占位适配器替换为真实 callable
- 在 `response_subgraph` 中把 `response_mode="exploration_plan"` 作为直通结果处理，避免 answer generator 重写
- 新增 Phase 8 专项测试 `local_life_agent/tests/test_exploration_planning_workflow.py`
- 回写 Phase 8 相关 todo 文档状态

## Phase 8 边界确认

- 只处理 Phase 8，不进入 Phase 7 / Phase 9 的重构收尾
- 只做最小独立 workflow，不抽共享 Core
- 不引入 RAG
- 不引入交易 / 下单 / 支付 / 退款 / 预约 / mutation
- 不调用 `search_pois`、`search_business_areas`、`estimate_travel_time`、`calculate_distance`
- 不做开放式 ReAct
- 不做无限 replan
- 不动态发现工具
- 不编造 POI / 商家事实

## 验证结果

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_exploration_planning_workflow.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `pytest local_life_agent/tests/test_05_graph.py -q`
- `pytest local_life_agent/tests/test_trace_observability.py -q`

以上命令本轮均已通过。

## 业务行为确认

- `coffee_then_dinner` 最多 2 个 subgoal
- `date_plan` / `family_activity_plan` 最多 3 个 subgoal
- 超过 3 个 subgoal 时进入现有 `clarification_fallback`
- 工具扩展最多 2 轮
- 信息不足 / 位置缺失时进入现有 `clarification_fallback`
- 工具失败时不胡编，直接回退
- 普通推荐仍走 `discovery_decision`
- 单店事实仍走 `deterministic_tool`
- 问候 / 能力说明仍走 `direct_response`
- 指代失败仍走 `clarification_fallback`
- 未污染 `last_recommendation_list` / `comparison_targets` / `current_shop`

## 已知敏感项

- `test_fuzzy_shop_does_not_call_coupon_tool` 仍按历史敏感项单独记录，未在本轮作为 Phase 8 目标处理

## 是否可进入 Phase 9

- 可以
- 原因：Phase 8 的最小独立探索规划链路已落地，验证命令通过，且未引入 RAG / 交易 / mutation，也未破坏 Phase 6 / Phase 7 的已完成语义
