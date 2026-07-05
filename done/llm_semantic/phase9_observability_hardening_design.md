# Phase 9 Observability Hardening Design

## 1. Goal
把当前 Phase 8/9 已经暴露出来的 trace / debug 字段，收敛成一份最小、可落地、不过度扩张的 structured logging contract。

目标不是引入新监控系统，而是让后续 P15-P26 的排障、回归和告警判断有稳定依据。

## 2. Structured Log Contract
建议只在 debug / test / internal structured log 中记录下列字段：

- `trace_id`
- `session_id`
- `turn_id`
- `workflow_name`
- `workflow_candidate_reason`
- `workflow_registry_validation`
- `semantic_parse_source`
- `schema_validation_result`
- `semantic_frame` 的摘要视图
- `router_policy_decision`
- `router_policy_conflicts`
- `target_resolution_status`
- `target_resolution`
- `comparison_target_resolution`
- `grounding_result`
- `missing_slot_type`
- `evidence_status`
- `evidence_review_result`
- `answer_verify_result`
- `state_update_plan`
- `session_state_before`
- `session_state_after`
- `fallback_reason`
- `tool_latency_ms`
- `workflow_latency_ms`
- `verifier_latency_ms`
- `parser_latency_ms`

## 3. Privacy / Redaction Rules
以下内容不建议直接进入生产日志全文：

- 用户原始长文本
- 可能包含隐私的精确位置文本
- 明细门店搜索历史
- 任何 token / credential / 环境变量

建议做法：

- 生产日志保留 `raw_input_hash` 或截断摘要，不保留全文。
- `session_state_before/after` 只保留必要差异，不保留完整会话快照。
- `semantic_frame` 只保留可观测字段摘要，避免携带过多原始候选文本。
- 需要排障时再切到 debug / test 环境的完整 trace。

## 4. Metrics Contract
建议最小统计以下计数器或直方图：

- `parser_fallback_rate`
- `comparison_route_success_rate`
- `comparison_route_fallback_rate`
- `verifier_block_rate`
- `tool_failed_rate`
- `tool_timeout_rate`
- `unknown_facets_rate`
- `failed_facets_rate`
- `partial_facets_rate`
- `clarification_rate`
- `workflow_latency_ms`
- `tool_latency_ms`
- `verifier_latency_ms`

## 5. Alert Suggestions
建议至少配置以下异常告警：

- parser fallback rate 异常升高
- comparison fallback rate 异常升高
- verifier block rate 异常升高
- tool failed / timeout rate 异常升高
- synthetic gate 通过但 integration E2E 失败

## 6. Current State
当前仓库已经在 trace 层暴露了足够多的字段，因此这轮 hardening 不需要重写业务链路，也不需要新增重型监控依赖。

最需要做的是：

1. 统一 structured log 的字段白名单。
2. 区分 debug/test 与生产环境输出。
3. 让后续 P15-P26 的问题定位有一致的字段来源。
