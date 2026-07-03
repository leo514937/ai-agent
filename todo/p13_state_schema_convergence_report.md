# P13 State 类型收敛与 GraphState BaseModel 分阶段迁移评估报告

## 1. Conclusion

PASS.

本轮已完成 GraphState 字段盘点、关键 schema 的 BaseModel / 校验收敛、`validate_graph_state` 适配层、`GraphStateModel` 评估层，以及 dict / TypedDict / BaseModel 兼容测试。

P13 只做类型边界收敛，不替换生产主路径的 `GraphState` TypedDict，也没有引入新 workflow、新 tool 或 workflow-level MapReduce。

## 2. P12 Gate

- `todo/p12_deadline_budget_freshness_ttl_report.md` 存在
- P12 结论为 `PASS`

说明：P12 已完成，P13 可以继续执行。

## 3. Scope

本轮聚焦于：

- 盘点 `GraphState` 当前字段
- 标记冗余字段、重复字段和语义重叠字段
- 明确关键对象的 schema ownership
- 补齐 `validate_graph_state`
- 新增 `GraphStateModel` adapter 评估层
- 强化 key object 的 BaseModel / schema 兼容性
- 增加 dict / TypedDict / BaseModel 兼容测试

本轮未做：

- 不立即全量替换 `GraphState`
- 不大规模删除 `GraphState` 字段
- 不重写 `graph_builder`
- 不新增 workflow
- 不新增 tool
- 不做 P14 冻结项验收

## 4. GraphState 盘点摘要

当前 `GraphState` 仍然是 dict-shaped `TypedDict`，字段按语义分组保留：

- 路由标识：`trace_id`、`turn_id`、`session_id`、`user_id`
- 输入层：`raw_text`、`normalized_text`、`input_type`
- 语义层：`top_intent`、`task_type`、`semantic_frame`、`facet_set`、`facets`、`target_resolution`、`conflicting_facets`、`ranking_policy`
- 澄清层：`pending_clarification`、`clarification_request`、`active_turn_result`、`active_turn_route`、`restored_task`
- 会话记忆：`current_shop`、`canonical_shop_entity`、`canonical_shop_entities`、`shop_resolution_trace`、`last_recommendation_list`、`active_constraints`、`comparison_targets`、`comparison_result`、`recommendation_candidates`、`precomputed_tool_results`
- 目标与候选：`goal_plan`、`goal_review_result`、`goal_plan_source`、`local_life_goal_draft`、`candidate_spec`、`candidate_set`、`review_results`
- 目标解析：`resolved_target`、`resolve_shop_result`、`target_resolution_status`、`resolution_stage`
- 执行计划：`execution_plan`、`validated_plan`、`execution_plan_source`
- 工具结果：`tool_results`、`tool_result_set`
- 证据层：`evidence_pack`
- 决策层：`p2_decision_plan`、`decision_review_result`
- orchestration：`orchestration_decision`、`orchestration_pattern`、`workflow_name`、`workflow_reason`、`task_complexity`、`requires_tool`、`requires_clarification`、`next_action`
- workflow dispatch：`workflow_run_status`、`workflow_runner_error`、`workflow_runner_reason`、`workflow_started_at`、`workflow_finished_at`、`workflow_registered`、`workflow_callable`
- 回答层：`answer_plan`、`exploration_plan`、`final_response`
- 状态更新：`state_update_plan`
- 观测层：`event_log`、`metrics_tags`、`trace_spans`
- 会话快照：`session_state_before`、`session_state_after`
- 重试 / 回环计数：`expand_search_count`、`replan_evidence_count`、`rewrite_count`
- runtime 辅助：`intake_route`、`merge_clarification_route`、`understanding_route`、`planning_route`、`execution_review_route`、`response_route`、`response_mode`、`session_state`、`pending_check_result`、`merge_clarification_result`、`clarification_result`、`error_code`、`error_message`、`plan_validation_result`、`failed_stage`、`guard_result`、`verify_result`、`draft_response`、`semantic_source`、`fallback_reason`、`answer_fallback_reason`、`llm_called`、`llm_backend`、`planning_llm_backend`、`planning_llm_called`、`planning_failure_code`、`answer_source`、`llm_verbalizer_violation`、`llm_verbalizer_error`、`generated_llm_answer_before_fallback`、`comparison_target_resolution`、`reference_resolution_source`、`answer_verify_passed`、`answer_verify_violations`、`rewrite_needed`、`rewrite_reason`、`final_safety_status`、`recommendation_query`、`subgoals`、`has_temporal_sequence`、`expected_output`、`exploration_round_count`、`tool_availability`、`location_status`、`user_location`、`preview_text`、`preview_policy_result`、`stream_status`、`evidence_cache_key`、`evidence_cache_scope`、`evidence_cache_hit`、`budget_context`

## 5. 重叠字段组盘点

### 5.1 Tool result 相关

- Canonical：`tool_results`
- Compatibility mirror：`tool_result_set`
- Owner：`execution_review_subgraph`
- Consumers：`evidence_builder`、`answer_verify`、`metrics`
- 当前结论：不能立即清理；`tool_result_set` 仅作为兼容镜像保留

### 5.2 Target resolve 相关

- Canonical protocol：`TargetResolutionResult`
- Current state pair：`resolved_target`、`resolve_shop_result`
- Comparison canonical source：`comparison_target_resolution`
- Owner：`planning_subgraph`
- Consumers：`evidence_planner`、`decision_planner`、`state_update_planner`
- 当前结论：不能立即清理；`resolve_shop_result` / `resolved_target` 仍需并存，`resolve_shop_result` 更适合作为后续收敛方向

### 5.3 Session state 相关

- Canonical write target：`session_state`
- Snapshot compatibility fields：`session_state_before`、`session_state_after`
- Canonical write plan：`state_update_plan`
- Owner：`state_update_plan`
- Consumers：`planning_subgraph`、`response_subgraph`、`persist_session_state`
- 当前结论：不能立即清理；`state_update_plan` 是唯一写回入口，快照字段保留用于读取和调试

### 5.4 Orchestration decision 相关

- Canonical object：`OrchestrationDecision`
- Canonical state slot：`orchestration_decision`
- High-frequency mirror：`workflow_name`
- Compatibility mirrors：`response_mode`、`next_action`
- Owner：`orchestration_router`
- Consumers：`workflow_runner`、`trace`、`metrics`
- 当前结论：`workflow_name` 必须单值，不能出现列表语义

### 5.5 Error / fallback 相关

- Business fallback：`fallback_reason`、`answer_fallback_reason`
- Tool / execution failure：`error_code`、`error_message`、`failed_stage`
- Observability error：`trace` / `metrics` 内部错误记录
- Verification / rewrite：`verify_result`、`rewrite_needed`、`rewrite_reason`
- 当前结论：不合并成单一 error 字段，继续按业务 / 工具 / 观测分层

### 5.6 Evidence / decision / answer 相关

- Canonical source: `evidence_pack`
- Decision link: `p2_decision_plan`
- Answer link: `answer_plan`
- Final output: `final_response`
- 当前结论：保持 Evidence -> Decision -> Answer -> Verify 顺序，不允许 answer 反向重决策

## 6. 未来可清理字段

以下字段属于当前必须保留的兼容镜像或过渡字段，适合作为未来清理候选，但本轮不删除：

- `tool_result_set`
- `resolved_target`
- `p2_decision_plan`
- `validated_plan`
- `session_state_before`
- `session_state_after`
- `answer_fallback_reason`
- `workflow_reason`

以下对象名属于兼容层遗留名，适合作为未来迁移方向：

- `SessionWriteDirective`
- `tool_result_set` 语义镜像
- `resolved_target` 语义镜像

本轮没有任何字段被立即清理。

## 7. Canonical Schema Ownership

已确认的关键对象 owner / schema 关系：

- `OrchestrationDecision`：`local_life_agent/domain/schemas.py`
- `ExecutionPlan`：`local_life_agent/domain/schemas.py`
- `EvidencePack`：`local_life_agent/domain/schemas.py`
- `DecisionPlan`：`local_life_agent/domain/decision.py`
- `AnswerPlan`：`local_life_agent/domain/schemas.py`
- `StateUpdatePlan`：`local_life_agent/domain/state.py`
- `EvidenceReviewResult`：`local_life_agent/domain/evidence.py`
- `TargetResolutionResult`：`local_life_agent/domain/facets.py`
- `BudgetContext`：`local_life_agent/planning/budget/budget_context.py`
- `TurnTrace`：`local_life_agent/observability/trace.py`
- `TurnMetrics`：`local_life_agent/observability/metrics.py`

`SessionWriteDirective` 仍保留为 `StateUpdatePlan` 的向后兼容子类，不作为新的业务 owner。

## 8. 新增 / 补齐的适配层

### `local_life_agent/domain/graph_state_model.py`

- 新增 `GraphStateModel`
- 新增 `GraphStateFieldContract`
- 新增 `GraphStateValidationResult`
- 记录关键兼容字段与 owner 信息
- 提供 GraphState 的只读校验和 canonical 镜像

### `local_life_agent/domain/state_validation.py`

- 新增 `validate_graph_state`
- 新增 `describe_graph_state_contracts`
- 作为 GraphState 盘点和验证的入口

### `local_life_agent/observability/trace.py`

- 新增 `TurnTraceModel`
- 新增 `validate_turn_trace`
- 保持 runtime trace 仍然是 dataclass，不改生产路径

### `local_life_agent/domain/state.py`

- 新增 `StateUpdatePlan`
- `SessionWriteDirective` 改为其兼容子类

## 9. 关键 BaseModel / schema 收敛

已强化的对象：

- `OrchestrationDecision`
- `ExecutionPlan`
- `EvidencePack`
- `DecisionPlan`
- `AnswerPlan`
- `StateUpdatePlan`
- `EvidenceReviewResult`
- `TargetResolutionResult`
- `BudgetContext`
- `TurnTrace`
- `TurnMetrics`

本轮做法：

- 增加了关键 list / dict 输入的归一化
- 保留了兼容 dict / BaseModel 输入能力
- 不把兼容输入直接转成 hard error
- 只在 `workflow_name` 多值等关键冲突处记录校验问题

## 10. 验证结果

已执行并通过：

```bash
python -m compileall local_life_agent
python -m pytest local_life_agent/tests/test_p13_state_schema_convergence.py -q
python -m pytest local_life_agent/tests/test_p0_fact_calibration.py local_life_agent/tests/test_subgraph_core_integration.py local_life_agent/tests/test_trace_observability.py local_life_agent/tests/test_p5_session_state_writeback.py -q
python -m pytest local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py -q
```

结果：

- `compileall` 通过
- `test_p13_state_schema_convergence.py`：`4 passed`
- `test_p0_fact_calibration.py` / `test_subgraph_core_integration.py` / `test_trace_observability.py` / `test_p5_session_state_writeback.py`：`23 passed`
- `test_p5_session_state_writeback.py` / `test_p8_evidence_review_iteration.py` / `test_p12_deadline_budget_freshness_ttl.py`：`36 passed`

## 11. Remaining Risks

- `GraphState` 仍然是生产主路径上的 TypedDict，P13 只做了验证层和收敛评估，没有全量迁移
- `tool_result_set`、`resolved_target`、`p2_decision_plan` 等兼容字段仍在过渡期
- `test_domain_schemas.py` 中有少量历史枚举断言与当前仓库状态不一致，这不属于本轮 P13 变更范围

## 12. P13 Readiness Judgment

P13 已完成。

本轮没有破坏 P0-P12 主回归路径，也没有改变 workflow_runner 单 dispatch、router 主协议或 SessionState 写回单入口。
