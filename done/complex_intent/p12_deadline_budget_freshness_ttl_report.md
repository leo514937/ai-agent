# P12 Deadline / Budget / Freshness / TTL Report

## 1. Conclusion

PASS.

本轮已按 P12 要求补齐单 workflow 内的 deadline / budget / freshness / TTL 协议，工具执行、扩搜、改写、补证据和动态事实复用都已纳入预算与时效约束，相关核心回归通过。

## 2. P7-P11 Gate

- `todo/p7_p11_unified_acceptance_report.md` 存在
- `P7_P11_ACCEPTANCE = true`
- `READY_FOR_P12 = true`

说明：P7-P11 统一验收已确认，可以进入 P12。

## 3. Inputs

已读取并核对：

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
- `todo/p10_final_p5_comparison_metadata_contract_fix_report.md`
- `todo/p11_observability_metrics_streaming_report.md`
- `todo/p11_followup_router_p6_regression_fix_report.md`
- `todo/p7_p11_unified_acceptance_report.md`
- `todo/complex_intent_query_architecture_stabilization_plan.md`

## 4. Scope

本轮只做 P12，不进入 P13-P14。

目标聚焦于：

- turn-level / workflow-level budget context
- deadline remaining 约束
- freshness / TTL 规则
- same-turn / weak dynamic / strong dynamic / location-bound 事实复用
- budget 耗尽后的稳定 degrade / fallback / clarify

## 5. BudgetContext Protocol

已新增预算上下文协议：

- `tool_round_budget`
- `retry_budget`
- `expand_search_budget`
- `rewrite_budget`
- `facet_enrich_budget`
- `deadline_remaining_ms`

并补充消费态字段：

- `consumed_tool_rounds`
- `consumed_retries`
- `consumed_expand_searches`
- `consumed_rewrites`
- `consumed_facet_enrich`
- `budget_exhausted_reasons`

实现位置：

- `local_life_agent/planning/budget/budget_context.py`

说明：

- 默认预算是小而安全的，不引入无限预算
- budget 可序列化
- budget 可以从 `GraphState` 读取并形成单一快照
- budget 出错时会回退到保守预算，不会让主流程崩溃

## 6. Freshness / TTL Protocol

已新增 freshness 协议：

- `FreshnessClass.STRONG_DYNAMIC`
- `FreshnessClass.WEAK_DYNAMIC`
- `FreshnessClass.STATIC`
- `FreshnessClass.LOCATION_BOUND`
- `FreshnessClass.SAME_TURN_ONLY`

实现位置：

- `local_life_agent/planning/freshness/freshness_policy.py`
- `local_life_agent/planning/freshness/ttl_policy.py`

已覆盖的事实类型：

- 强时效：`open_status`、`open_now`、`coupon`、`queue_status`、`reservation_available`
- 弱时效：`rating`、`review_tags`、`avg_price`、`popularity`、`service`、`environment`、`taste`
- 静态：`shop_name`、`address`、`phone`、`category`、`business_area`
- 位置相关：`distance`、`travel_time`
- same-turn only：临时失败结果、临时排序、batch result

说明：

- 位置相关事实绑定 `location_fingerprint`
- 不同 user_location 下不会复用距离 / ETA
- 过期或位置变化时会回落为 unknown / refresh
- same-turn 结果只允许本轮复用

## 7. Code Changes

### `local_life_agent/domain/schemas.py`

- `ExecutionPlan` 增加 `budget_context_snapshot`
- `EvidenceItem` 增加 `observed_at_ms`、`ttl_seconds`、`freshness_class`、`is_stale`、`cache_hit`、`location_fingerprint`、`budget_context_snapshot`
- `EvidencePack` 增加同类 freshness / budget 元数据字段

### `local_life_agent/domain/graph_state.py`

- 增加 `budget_context`

### `local_life_agent/domain/evidence.py`

- `EvidenceReviewResult` 增加预算剩余额、时效分类、过期 / stale / disclaimer 相关字段

### `local_life_agent/planning/evidence/evidence_review.py`

- 增加 freshness 分类与 stale 判定
- 强时效 + 位置相关过期时会阻断继续当作确定事实
- 预算耗尽时会进入 clarify / fallback / degrade 路径
- 结果会回填到 `trace_payload`

### `local_life_agent/planning/evidence/evidence_builder.py`

- 让构建出的 EvidencePack 携带 freshness / TTL / budget 快照

### `local_life_agent/planning/evidence/evidence_cache.py`

- cache scope 继续保留，可和 location / turn 维度协同使用
- same-turn / location-bound 复用不会互相串用

### `local_life_agent/planning/evidence/facet_budget.py`

- `EvidencePlannerResult` 增加 `budget_context_snapshot`

### `local_life_agent/planning/evidence/tool_capabilities.py`

- 继续承载 capability / facet budget 的下游约束，不新增工具

### `local_life_agent/engine/subgraphs/response_subgraph.py`

- rewrite 行为受 `rewrite_budget` 约束

### `local_life_agent/engine/workflows/deterministic_tool_workflow.py`

- tool round / facet enrich / deadline gating 已接入
- 预算耗尽时会提前走保守降级

### `local_life_agent/engine/workflows/exploration_planning_workflow.py`

- 扩搜和补证据受 tool round / facet enrich / deadline 约束

### `local_life_agent/observability/metrics.py`

- 增加预算剩余、deadline、stale evidence、cache stale / refresh、location fingerprint mismatch 等观测字段

### `local_life_agent/engine/subgraphs/execution_review_subgraph.py`

- 为了兼容现有集成测试的打桩入口，恢复使用模块级 `ExecutionCore`
- 仍保持单 workflow 内执行，不引入新 workflow 或 MapReduce

## 8. Test Changes

新增测试文件：

- `local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py`

覆盖内容：

- budget context 默认值与可序列化
- freshness policy 映射
- location fingerprint scoped cache 复用
- same-turn cache 复用可追踪
- strong dynamic stale evidence 行为
- weak dynamic stale evidence 的 disclaimer 行为
- deterministic workflow 的 tool_round_budget 耗尽行为
- response subgraph 的 rewrite_budget 耗尽行为
- exploration workflow 的 deadline / budget 跳过行为
- metrics 只做观测不改业务决策

## 9. Verification

已执行并通过：

```bash
python -m compileall local_life_agent
python -m pytest local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py -q
python -m pytest local_life_agent/tests/test_evidence_review.py local_life_agent/tests/test_exploration_planning_workflow.py local_life_agent/tests/test_deterministic_tool_workflow.py local_life_agent/tests/test_metrics_eval.py -q
python -m pytest local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p9_evidence_planner_capability_budget.py local_life_agent/tests/test_p10_experience_performance.py local_life_agent/tests/test_p11_observability_streaming.py -q
python -m pytest local_life_agent/tests/test_subgraph_core_integration.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_deterministic_tool_workflow.py local_life_agent/tests/test_exploration_planning_workflow.py -q
python -m pytest local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p9_evidence_planner_capability_budget.py local_life_agent/tests/test_p10_experience_performance.py local_life_agent/tests/test_p11_observability_streaming.py local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py -q
```

结果：

- `compileall` 通过
- `test_p12_deadline_budget_freshness_ttl.py`：`18 passed`
- `test_evidence_review.py` / `test_exploration_planning_workflow.py` / `test_deterministic_tool_workflow.py` / `test_metrics_eval.py`：`39 passed`
- P8-P11 回归：`41 passed, 1 warning`
- `test_subgraph_core_integration.py` 等核心集成回归：`25 passed`
- P8-P12 合并回归：`59 passed, 1 warning`

## 10. Remaining Risks

- `deadline_remaining_ms` 目前是协议层约束，尚未接入真实外部时钟或统一计时源
- `evidence_cache` 的 freshness / location 复用策略仍以当前单 workflow 协议为主，后续若增加新事实类型，需要继续补 policy
- 真实线上环境中的高延迟和工具超时情形仍需持续观察

## 11. P12 Readiness Judgment

P12 已完成。

本轮没有新增 workflow，没有新增 tool，没有引入 workflow-level MapReduce，也没有重写 `graph_builder`。预算、时效、TTL 和降级路径已经在单 workflow 协议内闭环。
