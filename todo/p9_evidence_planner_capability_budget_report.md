# P9 EvidencePlanner facet 生成 / 裁剪 / 预算 报告

## 结论

PASS for the P9 core scope.

本轮已补齐 EvidencePlanner 的能力注册、facet taxonomy 校验、预算裁剪与计划元数据回流，并保持了 P1-P8 的主回归集合通过。

## 已实现内容

### 1. Tool capability registry

新增 `local_life_agent/planning/evidence/tool_capabilities.py`，提供：

* `ToolCapabilitySpec`
* `TOOL_CAPABILITY_REGISTRY`
* `preferred_tool_for_facet`
* `tool_supports_facet`
* `build_tool_call_dict`

覆盖了当前链路常用工具：

* `search_shops`
* `get_shop_detail`
* `get_coupon_list`
* `check_open_status`
* `get_distance_eta`
* `get_shop_cards`
* `get_shop_review_summary`
* `get_deal_list`

### 2. Facet validator

新增 `local_life_agent/planning/evidence/facet_validator.py`，提供：

* `FacetCandidate`
* `FacetValidationResult`
* `build_facet_candidates`
* `validate_facet_candidates`

支持：

* 未知 facet 拒绝
* 同义 facet 归一化
* taxonomy 内但工具不支持的 facet 标记为 unsupported
* 引用消解 / comparison 相关的必要 facet 补齐

### 3. Budget controller

新增 `local_life_agent/planning/evidence/facet_budget.py`，提供：

* `FacetBudgetPlan`
* `EvidencePlannerResult`
* `plan_facet_budget`
* `build_evidence_planner_result`

支持：

* `max_facets`
* `max_tool_calls`
* `total_cost_budget`
* `drop_reasons`
* `blocked_tool_calls`

### 4. Schema compatibility

扩展了 `local_life_agent/domain/schemas.py` 的 `ExecutionPlan`，增加兼容字段：

* `facet_candidates`
* `facet_validation_result`
* `facet_budget_plan`
* `blocked_tool_calls`
* `unsupported_facets`
* `missing_inputs`
* `planning_warnings`
* `evidence_planner_result`

### 5. Planner 接线

更新了：

* `local_life_agent/planning/evidence/evidence_planner.py`
* `local_life_agent/planning/plans/execution_plan_builder.py`

让现有 plan 产物挂上 P9 元数据，方便 downstream / review 使用。

## 验证结果

已通过：

* `python -m compileall local_life_agent`
* `python -m pytest local_life_agent/tests/test_p9_evidence_planner_capability_budget.py -q`
* `python -m pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_execution_plan_validator.py -q`

结果：

* 110 passed

## 风险 / 后续

我另外额外跑了：

* `local_life_agent/tests/test_recommendation_flow.py`
* `local_life_agent/tests/test_single_shop_multifacet.py`

这两组在当前树上仍有失败，集中在 recommendation / single-shop multifacet 的端到端行为上，不属于本轮已收敛的 P9 纯函数层核心验证。

本轮没有新增 golden trace，原因是先把可验证的 capability / budget 协议接稳，避免进一步扩大改动面。

## 变更文件

* `local_life_agent/planning/evidence/tool_capabilities.py`
* `local_life_agent/planning/evidence/facet_validator.py`
* `local_life_agent/planning/evidence/facet_budget.py`
* `local_life_agent/planning/evidence/evidence_planner.py`
* `local_life_agent/planning/plans/execution_plan_builder.py`
* `local_life_agent/domain/schemas.py`
* `local_life_agent/tests/test_p9_evidence_planner_capability_budget.py`
