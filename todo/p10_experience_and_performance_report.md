# P10 体验与性能优化报告

## 目标

按 `complex_intent_query_architecture_stabilization_plan.md` 的 P10 要求，补齐流式状态事件、预览策略、批量工具执行、证据缓存复用，并保持与 P8/P9 的兼容边界。

## 本次实现

- 扩展了流式事件契约：新增 `status`、`preview`、`evidence_update`、`fallback` 事件类型，并保留原有 `trace_started`、`input_normalized`、`answer_delta`、`final` 兼容输出。
- 新增 `local_life_agent/streaming/status_events.py`，统一生成 SSE 事件块。
- 新增 `local_life_agent/streaming/preview_policy.py`，用于阻断未验证事实的预览输出。
- 在 `app.py` 中接入预览策略与结构化流式事件：
  - 保持旧的流式顺序兼容
  - 继续输出 `answer_delta`
  - 补充 `preview` 与 `status` 事件
  - `final` 事件携带 `verified=true`
- 新增 `local_life_agent/planning/evidence/tool_batch_executor.py`，作为工作流侧的批量执行包装器。
- 新增 `local_life_agent/planning/evidence/evidence_cache.py`，提供带作用域与指纹的证据缓存，避免跨会话复用。
- 扩展 `evidence_builder.py`、`evidence_adapter.py`、`evidence_planner.py`、`facet_budget.py`、`tool_capabilities.py`，补充 top-k / budget / cache 元数据。
- 扩展 `deterministic_tool_workflow.py`，支持单店多 facet 的批量执行与证据汇总。
- 扩展 `execution_review_subgraph.py` 与 `exploration_planning_workflow.py`，接入批量执行包装器与证据缓存。
- 扩展 `response_subgraph.py`，补充预览态字段与验证态标记。
- 扩展 `domain/schemas.py` 与 `domain/graph_state.py`，承接缓存、预览与 top-k 元数据。

## 验证结果

### 基础验证

- `python -m compileall local_life_agent`
- 结果：通过

### 核心回归

- `pytest local_life_agent/tests/test_p0_fact_calibration.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_end_to_end.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p9_evidence_planner_capability_budget.py local_life_agent/tests/test_execution_plan_validator.py local_life_agent/tests/test_p10_experience_performance.py -q`
- 结果：`107 passed`

### P10 专项测试

- `local_life_agent/tests/test_p10_experience_performance.py`
- 结果：`9 passed`

## 仍然存在的已知风险

以下两组场景在本次 P10 之后仍失败，且失败形态仍集中在既有的推荐/多维单店链路问题，而不是新的流式事件或缓存契约问题：

- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 结果：`7 failed, 10 passed, 2 xfailed`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
  - 结果：`6 failed, 1 passed`

当前观察到的失败点主要是：

- 推荐场景里 `execution_plan` / `ranking_snapshot` 为空或未正确构建
- 单店多 facet 场景里仍会过早落到澄清/模糊分支

## 结论

P10 的流式体验、预览策略、批量执行和证据缓存已经落地，并通过核心回归与专项测试验证。
推荐流与单店多 facet 的既有问题仍未完全修复，后续如果继续推进，建议优先回到推荐路由与多 facet 计划生成这条链路。
