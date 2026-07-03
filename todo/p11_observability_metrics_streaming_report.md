# P11 Observability Metrics Streaming Report

## 1. Conclusion

PARTIAL PASS.

P11 的观测 / 指标 / streaming 协议已经按目标补齐，`test_p11_observability_streaming.py` 通过，相关观测回归也通过。
但本轮要求的更宽回归里仍有 6 个既有失败，集中在 `test_orchestration_router.py` 和 `test_p6_complex_query_matrix.py`，因此还不能判定整体可以进入 P12。

## 2. P10 Follow-up Gate

- 是否存在 P10 follow-up 报告：`todo/p10_final_p5_comparison_metadata_contract_fix_report.md` 存在
- `P10_FOLLOWUP_FIXED`：true
- `READY_FOR_P11`：true

说明：上一阶段的 comparison metadata contract 已经修复并验证通过，本轮可以进入 P11。

## 3. Inputs

已读取的输入文档与报告：

- `todo/complex_intent_query_architecture_stabilization_plan.md`
- `todo/p0_fact_calibration_and_adr_freeze_report.md`
- `todo/adr_p0_single_owner_workflow_no_map_reduce.md`
- `todo/p1_single_owner_workflow_invariants_report.md`
- `todo/p2_router_priority_and_keyword_conflict_report.md`
- `todo/p3_facet_protocol_and_retention_report.md`
- `todo/p4_evidence_decision_answer_protocol_report.md`
- `todo/p5_session_state_writeback_safety_and_reference_retention_report.md`
- `todo/p6_complex_query_matrix_report.md`
- `todo/p7_exploration_planning_protocol_isomorphism_report.md`
- `todo/p8_evidence_insufficiency_iteration_and_degrade_report.md`
- `todo/p9_evidence_planner_capability_budget_report.md`
- `todo/p10_experience_and_performance_report.md`
- `todo/p10_followup_recommendation_and_single_shop_fix_report.md`
- `todo/p10_final_p5_comparison_metadata_contract_fix_report.md`

## 4. Scope

本轮检查 / 修改的文件：

- `local_life_agent/observability/trace.py`
- `local_life_agent/observability/metrics.py`
- `local_life_agent/streaming/events.py`
- `local_life_agent/tests/test_p11_observability_streaming.py`

说明：

- 没有新增 workflow
- 没有新增 tool
- 没有重写 `graph_builder`
- 没有修改 recommendation ranking_snapshot 来源
- 没有修改 evidence_builder / answer_plan_builder 主协议
- 没有扩大 fuzzy 规则
- 没有改 canonical shop entity 主链路

## 5. Trace Protocol

已补齐的 trace 协议：

- `TraceSpan`
- `TurnTrace`
- one turn -> one trace
- 单 trace 内允许多个 spans
- trace / spans / errors 仅做观测，不写 SessionState

实现要点：

- `TraceSpanRecord` 兼容新增的 `span_id`、`parent_span_id`、`name`、`workflow_name`、`started_at_ms`、`ended_at_ms`、`latency_ms`
- `TurnTrace` 兼容 `spans`、`metrics`、`errors`
- `build_turn_trace()` 会把事件日志和 trace store 归一到同一个 trace
- trace 异常通过安全错误结构隔离，不打断主流程

## 6. Metrics Protocol

已补齐的 metrics 协议：

- `TurnMetrics`
- `workflow_name`
- `route_task`
- `response_mode`
- `facet_count`
- `facets`
- `tool_call_count`
- `evidence_count`
- `answerable_facets_count`
- `unknown_facets_count`
- `failed_facets_count`
- `verification_status`
- `fallback_reason`
- `final_latency_ms`

另外补了 P9 相关的派生计数：

- `facet_candidates_count`
- `accepted_facets_count`
- `rejected_facets_count`
- `unsupported_facets_count`
- `planner_selected_tool_call_count`
- `planner_blocked_tool_call_count`
- `planner_dropped_facet_count`
- `budget_exceeded_count`

metrics 只做观测，不改变业务决策，也不写 SessionState。

## 7. Business Quality Metrics

已补齐聚合 helper，并在测试中覆盖：

- `answer_verify_pass_rate`
- `clarification_rate`
- `tool_failure_rate`
- `avg_facets_per_query`
- `evidence_sufficiency_rate`
- `state_write_block_rate`
- `preview_block_rate`
- `fallback_rate`
- `degrade_rate`
- `retry_action_rate`
- `expand_search_action_rate`

## 8. Streaming Protocol

已补齐的 streaming 协议：

- `status`
- `preview`
- `evidence_update`
- `final`
- `fallback`
- `error`
- `trace_id`
- `span_id`

关键规则已在测试中验证：

- `status.partial == True`
- `preview.partial == True`
- `preview.verified == False`
- `evidence_update.partial == True`
- `final.partial == False`
- `final.verified == True`
- `fallback.verified == False`
- 每轮最多一个 final 事件
- 没有多 workflow token stream merge

## 9. P8 / P9 / P10 Metrics Integration

已覆盖的观测点：

- P8 evidence review action 进入 metrics
- P9 capability / budget 相关计数进入 metrics
- P10 preview / batch / cache / stream event 计数进入 metrics

说明：

- 这些指标只用于观测与评估，不参与业务决策
- 没有改变 P8 / P9 / P10 原有协议

## 10. Observability Isolation

已验证：

- trace 失败不打断主流程
- metrics builder 失败不打断主流程
- stream metadata 失败不打断主流程
- trace / event / metrics 都不写 SessionState

## 11. Golden Trace Updates

本轮没有新增 golden trace 文件。

原因：

- 为了控制 P11 的改动范围，优先用单元测试直接覆盖协议和隔离行为
- 当前实现已经可以通过 deterministic tests 验证 one trace / spans / metrics / streaming 规则

## 12. Code Changes

### `local_life_agent/observability/trace.py`

- 新增 / 补齐 `TraceSpanRecord` 的 P11 字段兼容
- 新增 `TraceSpan` 别名
- 新增 `start_span`、`end_span`、`safe_trace_error`
- 新增 trace span 归一化
- 新增 turn metrics snapshot 接入
- 修复了 `build_turn_trace()` 的运行时变量问题

### `local_life_agent/observability/metrics.py`

- 新增 `TurnMetrics`
- 新增 `build_turn_metrics`
- 新增 `aggregate_quality_metrics`
- 新增 P9 相关计数字段
- 新增 preview / state write 计数 helper

### `local_life_agent/streaming/events.py`

- 补齐 event envelope 的 `trace_id` / `span_id` / `workflow_name` / `stage` / `facets` / `partial` / `verified` / `evidence_ref`
- 统一 event factory 的 payload 与 envelope 结构
- 保持旧事件兼容

### `local_life_agent/tests/test_p11_observability_streaming.py`

- 新增 P11 观测测试
- 覆盖 one trace、spans、metrics、stream events、source scan、failure isolation、quality aggregate

## 13. Test Changes

新增测试覆盖点：

- one turn -> one trace
- core spans 记录
- metrics 派生且不改 state
- stream event 携带 trace_id / span_id
- preview 不冒充 final
- no multi-workflow stream merge
- P8 / P9 / P10 相关 metrics 计数
- observability failure isolation
- business quality metrics aggregate

## 14. Test Results

### 已通过

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_p11_observability_streaming.py -q`
  - 15 passed
- `pytest local_life_agent/tests/test_streaming_event_contract.py local_life_agent/tests/test_trace_observability.py local_life_agent/tests/test_observability_regression.py local_life_agent/tests/test_p10_experience_performance.py -q`
  - 26 passed
- `pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p7_exploration_protocol.py local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p9_evidence_planner_capability_budget.py -q`
  - 80 passed

### 仍失败

宽回归命令中仍有 6 个失败：

- `local_life_agent/tests/test_orchestration_router.py::test_orchestration_router_falls_back_when_single_shop_anchor_missing`
- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_complex_query_matrix[multi_constraint_recommendation]`
- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_complex_query_matrix[empty_search_result]`
- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_complex_query_matrix[clarification_resume]`
- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_smoke_cases[all_tools_timeout_smoke]`
- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_smoke_cases[malformed_llm_output_smoke]`

宽回归统计：

- `120 passed`
- `6 failed`

这些失败集中在 router / P6 语义路径，不在本轮 P11 观测协议修改范围内。

## 15. Acceptance Judgment

- one turn -> one trace: PASS
- trace spans 存在: PASS
- metrics protocol 存在: PASS
- business quality metrics 存在: PASS
- stream events 携带 trace_id: PASS
- 每轮最多一个 final: PASS
- preview 不冒充 final: PASS
- no multi-workflow stream merge: PASS
- metrics 不改业务决策: PASS
- trace / event 不写 SessionState: PASS
- observability failure 不打断主流程: PASS
- P8 / P9 / P10 metrics 集成: PASS
- P1-P10 回归未破坏: PARTIAL PASS
- 是否可以进入 P12: NO

原因：

- P11 观测层已经收敛完成
- 但更宽的回归仍有 6 个失败，尚未达到“全套验收通过”的门槛

## 16. Remaining Risks

- P11 不解决 P12 的 deadline / freshness / TTL
- P11 不解决 P13 BaseModel 全量迁移
- 真实监控系统 / dashboard 尚未接入
- Prometheus / OpenTelemetry 仍是后续事项
- `test_orchestration_router.py` 和 `test_p6_complex_query_matrix.py` 仍有独立失败，需要后续单独处理

## 17. Deferred to Later Phases

- P12 deadline / budget / freshness / TTL
- P13 State 类型收敛与 BaseModel 迁移评估
- P14 长期冻结项

