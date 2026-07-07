# Architecture Overlap Phase 1 Canonical Path Freeze Report

## 1. 结论

PASS

Phase 1 的目标是冻结 canonical import path、标记 deprecated 兼容层、补齐边界测试，并且不改业务逻辑。这个目标已经完成。

## 2. 前置条件

- Phase 0 事实基线报告已存在并通过：[`architecture_overlap_phase0_fact_baseline_report.md`](./architecture_overlap_phase0_fact_baseline_report.md)
- 当前 Phase 1 的 canonical 路径表已补齐：[`architecture_phase1_canonical_import_paths.md`](./architecture_phase1_canonical_import_paths.md)
- 兼容层已经补上 `DEPRECATED_COMPAT` 标记
- 新增 architecture boundary test

## 3. 冻结结果

### 3.1 canonical path 冻结

本阶段没有改业务实现，只把权威路径写清楚并固定下来。

已明确的 canonical 面：

- `local_life_agent.semantic.intent_parser`
- `local_life_agent.target.context_recovery`
- `local_life_agent.target.candidate_resolver`
- `local_life_agent.target.shop_resolver`
- `local_life_agent.planning.orchestration_router`
- `local_life_agent.planning.goal.goal_planner`
- `local_life_agent.planning.evidence.evidence_builder`
- `local_life_agent.planning.decision.decision_planner`
- `local_life_agent.planning.policies.review_policy`
- `local_life_agent.planning.policies.replan_policy`
- `local_life_agent.planning.policies.ranking_policy`
- `local_life_agent.planning.plans.plan_validator`
- `local_life_agent.planning.plans.state_update_planner`
- `local_life_agent.tools.gateway`
- `local_life_agent.answer.generator`
- `local_life_agent.answer.verifier`
- `local_life_agent.domain.state`
- `local_life_agent.engine.graph_builder`
- `local_life_agent.observability.trace`
- `local_life_agent.streaming.events`

### 3.2 deprecated 标记结果

已补标记的兼容层包括：

- `local_life_agent.core` family
- `local_life_agent.planning` 顶层 legacy shim family
- `local_life_agent.semantic.top_intent_router`

这些文件现在都带有 `DEPRECATED_COMPAT` 说明，明确 Phase 1 后不再扩散新的调用方。

### 3.3 boundary tests

新增测试文件：

- [`local_life_agent/tests/test_phase1_architecture_boundaries.py`](../local_life_agent/tests/test_phase1_architecture_boundaries.py)

它覆盖三件事：

- 旧 `core/` 导入面只允许既有调用方
- 旧 `planning/*.py` 顶层 shim 只允许既有调用方
- `graph_builder` 的兼容导出和模块导入面不再无限扩张

## 4. 变更性质

本阶段没有做以下事情：

- 没有重写 router
- 没有改 workflow 调度逻辑
- 没有拆 tools registry
- 没有动 DB fixture fallback
- 没有删除任何兼容文件

## 5. 验证结果

已完成验证：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase1_architecture_boundaries.py -q`
- `pytest local_life_agent/tests/test_core_wrappers.py -q`
- `pytest local_life_agent/tests/test_phase1_acceptance.py -q`

之前已通过的相关基线测试也继续成立：

- `pytest local_life_agent/tests/test_phase0_baseline.py -q`
- `pytest local_life_agent/tests/test_p0_fact_calibration.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_tool_gateway.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`

## 6. 残余风险

- `local_life_agent.core.candidate_core`、`local_life_agent.target.candidate_resolver`、`local_life_agent.target.reference_resolver`、`local_life_agent.engine.workflows.deterministic_tool_workflow` 仍然依赖 `engine.graph_builder` 兼容面
- `SessionState` 写回责任还没有在 Phase 1 解决
- `tools/db_client.py` 的 fixture fallback 仍然保留，属于后续 Phase 5/7 议题
- `tools/db_tools.py` 仍然读取 `local_life_agent/mock_data/`，也属于后续阶段

## 7. Phase 2 判断

可以进入 Phase 2。

说明：

- Phase 1 已经完成“冻结与标记”
- 后续如果要做路由权威层收敛，可以在这个冻结基线上继续推进
- 但 Phase 2 不应顺手扩大状态写回、DB fallback 或 tools registry 的改动范围

