# Phase 9 / 6a-6b Complex Orchestrator + SubTaskDAG / WorkerResult / Reducer Report

**结论：PASS**

## 前置门禁验收结果

- 第 8 批 5c 已完成：三层 trace schema、latency / cost benchmark、ResponseContract V2 都已存在并通过回归。
- 当前全量测试无遗留失败：`python -m pytest local_life_agent/tests -q` 结果为 `1389 passed, 37 skipped, 2 xfailed`。
- `recommendation / comparison / single_shop / coupon / exploration` 主链路均通过。
- `ResponseContract V2` 当前仍由统一 response 出口消费，没有 workflow 直写绕过。
- `complex_orchestrator` 之前不存在于路由和注册表中，本批次已补齐。

## 修改前真实代码调研结果

- `local_life_agent/planning/orchestration_router.py` 里只有 `low / medium / high` 三档复杂度，没有 `super_complex`。
- `local_life_agent/engine/workflow_registry.py` 只有 `discovery_decision / recommendation_decision_workflow / comparison_decision_workflow / direct_response / single_shop_fact_workflow / deterministic_tool / clarification_fallback / exploration_planning`。
- `local_life_agent/engine/_routes.py` 的 `workflow_runner` 只有通往 `planning_subgraph` 和 `response_subgraph` 的路径。
- `local_life_agent/engine/workflows/` 中没有 `complex_orchestrator_workflow.py`。
- `local_life_agent/planning/` 下没有 `orchestrator/` 共享模块。

## task complexity 入口说明

- 新增 `super_complex` 路由任务。
- `semantic_frame.task_complexity == "super_complex"`、`workflow_hint == "complex_orchestrator_workflow"` 或显式 `task_type == "super_complex"` 时，`normalize_route_task()` 会进入 `super_complex`。
- `OrchestrationDecision` 的复杂度白名单已扩展到 `super_complex`。

## complex_orchestrator_workflow 实现说明

- 新增 `local_life_agent/engine/workflows/complex_orchestrator_workflow.py`。
- workflow 以 `SubTaskDAG` 驱动子任务拓扑排序。
- 每个子任务在独立的 `WorkerResult` 中执行，避免共享可变 `GraphState`。
- workflow 使用 `EvidenceReducer` 和 `DecisionReducer` 汇总多子任务结果。
- 最终输出走 `ResponseDirective` / `ResponseContractV2`，并保留 `draft_response` / `preview_text` 供统一 response 出口消费。
- workflow 不把 complex orchestrator 当成 fallback；它只在 `super_complex` 路由进入。

## SubTaskDAG / WorkerResult / Reducer / ConflictResolver 说明

- `SubTaskDAG` 支持节点、依赖和拓扑排序。
- `WorkerResult` 负责封装单个子任务的隔离状态、证据、决策和响应草稿。
- `EvidenceReducer` 负责合并多子任务证据、工具结果、引用和 provenance。
- `DecisionReducer` 负责合并多子任务决策、winner、ranking 和不确定性说明。
- `ConflictResolver` 负责识别 winner 冲突和 answer type 冲突，并保留 uncertainty notices。

## 为什么普通 query 不会误入 complex_orchestrator

- 只有显式 `super_complex` 语义信号才会进入新 route_task。
- 普通 recommendation / comparison / single_shop / exploration 仍命中原有策略表。
- `workflow_runner` 仍按现有规则把 `complex_orchestrator_workflow` 送到 `response_subgraph`，不会回流到 `planning_subgraph`。

## 与 exploration_planning_workflow 的边界

- `exploration_planning` 仍保留为已有高复杂度探索流程。
- `complex_orchestrator_workflow` 是更上层的子任务编排入口，不替代 exploration workflow。
- reducer 只负责汇总子任务结果，不复制原有 exploration planning 逻辑。

## 与 ResponseContract V2 / trace 的衔接

- workflow 直接构造 `ResponseDirective` 和 `ResponseContractV2`，并保留 `response_contract_v1` 兼容字段。
- 子任务、DAG 和 reducer 的 summary 都写入 `metadata` / `trace_summary`，便于统一出口消费。
- 最终仍由统一 response 流水线收口，不新增旁路最终答案出口。

## 实际修改文件清单

- `local_life_agent/domain/schemas.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/planning/orchestrator/__init__.py`
- `local_life_agent/planning/orchestrator/sub_task_dag.py`
- `local_life_agent/planning/orchestrator/worker_result.py`
- `local_life_agent/planning/orchestrator/conflict_resolver.py`
- `local_life_agent/planning/orchestrator/evidence_reducer.py`
- `local_life_agent/planning/orchestrator/decision_reducer.py`
- `local_life_agent/engine/workflows/complex_orchestrator_workflow.py`
- `local_life_agent/engine/workflows/__init__.py`
- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/tests/test_orchestration_router.py`
- `local_life_agent/tests/test_workflow_registry.py`
- `local_life_agent/tests/test_workflow_runner.py`
- `local_life_agent/tests/test_second_layer_complex_orchestrator.py`
- `local_life_agent/tests/test_second_layer_conflict_resolver.py`
- `local_life_agent/tests/test_second_layer_map_reduce_reducer.py`
- `local_life_agent/tests/test_second_layer_worker_state_isolation.py`

## 明确没有做的 6c / 6d 内容

- 没有加入 ClaimVerifier L2 / L3。
- 没有引入更高阶的复杂任务终验链路。
- 没有改写 graph_builder 的整体结构。
- 没有把 complex_orchestrator 变成普通 query 的 fallback。

## 测试结果

- `python -m compileall local_life_agent`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_orchestration_router.py -q`
- `python -m pytest local_life_agent/tests/test_second_layer_map_reduce_reducer.py -q`
- `python -m pytest local_life_agent/tests/test_second_layer_conflict_resolver.py -q`
- `python -m pytest local_life_agent/tests/test_second_layer_worker_state_isolation.py -q`
- `python -m pytest local_life_agent/tests/test_second_layer_complex_orchestrator.py -q`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
- `python -m pytest local_life_agent/tests -q`

本轮复验补充：

- `python -m pytest local_life_agent/tests/test_second_layer_complex_orchestrator.py local_life_agent/tests/test_second_layer_map_reduce_reducer.py local_life_agent/tests/test_second_layer_conflict_resolver.py local_life_agent/tests/test_second_layer_worker_state_isolation.py -q`：9 passed
- `python -m pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_orchestration_router.py -q`：18 passed
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_single_shop_multifacet.py local_life_agent/tests/test_e2e_llm_main_path.py -q`：63 passed, 1 skipped, 2 xfailed
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py local_life_agent/tests/test_phase3_completion_contracts.py -q`：14 passed
- `python -m compileall local_life_agent`：通过
- `python -m pytest local_life_agent/tests -q`：1391 passed, 37 skipped, 2 xfailed

最终全量结果：`1391 passed, 37 skipped, 2 xfailed`

## 是否建议进入 6c ClaimVerifier L2/L3

建议进入，但前提是先基于当前 `complex_orchestrator_workflow` 的输出稳定性，再定义更高阶的 claim 校验范围，避免把 reducer 和校验器同时大改。
