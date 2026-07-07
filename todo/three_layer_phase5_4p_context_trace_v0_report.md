# Phase 5-4p 报告：ContextualizedTurn V0 / FocusContext V0 / FreshnessMeta / LocationContext

## 结论

PARTIAL PASS

本次只完成了 4p 的 trace-only 改造，没有进入 4a / 4b。现有推荐、对比、单店、澄清主链路保持通过，第一层只新增了可观测上下文 DTO 和最小埋点，没有改路由权威，也没有改实体解析权威。

## 第 4 批前置验收结果

- 3a 已完成：`RewriteInstruction` 已接入 rewrite loop。
- 3b 已完成：完整 deterministic composer 已覆盖主要 answer_type。
- 3c 已完成：`ClaimExtractor / ClaimVerifier L1` 已可用。
- 3d 已完成：recommendation / comparison 已有真实独立 workflow。
- 3e 已完成：comparison winner 已由 `ComparisonMatrix / RankingPolicy / DecisionPlan` 约束。
- 3f 已完成：exploration workflow 已接入共享能力。
- 统一 `final_response` / `ResponseContractV1` 出口保持有效。
- `recommendation / comparison / single_shop` 主链路测试保持通过。

## 修改前真实代码调研结果

- 第一层的真实写入点主要还是 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification`。
- `intake_guard_router` 负责加载会话、硬守卫和顶层意图路由，不负责上下文 DTO。
- `active_turn_resolver` 负责 pending clarification 的规则化解析，已经能识别数字、中文序号、指代和候选名，但没有显式的 FocusContext 载体。
- `context_recovery` 已经在做实体恢复和 comparison target 恢复，属于真正的上下文恢复权威。
- `slot_extractor` 已经覆盖 `task_type`、`preference`、`filters`、`comparison_targets`、`ordinal_references`、`deictic_references`，不适合被新的第一层 DTO 覆盖。
- `hard_guard` 只做 allow / deny，不承担 local_life 路由权威。
- 4p 前的链路里没有 `ContextualizedTurn / FocusContext / FreshnessMeta / LocationContext` 这类显式 trace DTO。

## ContextualizedTurn V0 / V1 实现说明

- 新增 `local_life_agent/domain/contextualized_turn.py`。
- `ContextualizedTurn` 只有 trace 语义字段：
  - `original_text`
  - `normalized_text`
  - `contextualized_query`
  - `rewrite_type`
  - `context_used`
  - `confidence`
- 本次只实现 V0 trace-only：
  - 不替换 `semantic_parse`
  - 不接管 `context_recovery`
  - 不改变路由结果
- 在 `understanding_subgraph._h_context_recovery` 中生成并写回 state，作为附加 trace。
- 已能覆盖：
  - follow-up / constraint update 的 trace
  - active turn restoration 的 trace
  - comparison reference 的 trace

## FocusContext V0 / V1 实现说明

- 新增 `local_life_agent/domain/focus_context.py`。
- `FocusContext` 仅用于 trace，可表达：
  - 当前焦点对象
  - 推荐列表 item
  - comparison targets
  - focus source / confidence
- 本次只实现 V0 trace-only：
  - 不替换 `current_shop`
  - 不替换 `last_recommendation_list`
  - 不替换 `comparison_targets`
  - 不改变 reference resolver 主行为
- 在 `understanding_subgraph._h_context_recovery` 中生成并写回 state。

## FreshnessMeta / LocationContext 实现说明

- 新增 `local_life_agent/domain/freshness.py`。
- 新增 `local_life_agent/domain/location_context.py`。
- 两者都是可序列化 DTO：
  - `FreshnessMeta`：`freshness_class`、`is_stale`、`cache_hit`、`location_fingerprint`、`budget_context_snapshot`
  - `LocationContext`：`location_name`、`lat`、`lng`、`location_status`、`location_source`、`location_fingerprint`
- 本次只作为 trace / evidence metadata 的载体，不改变工具调用逻辑，也不改变 session 存储逻辑。

## 与旧字段的兼容关系

- `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 仍然是权威老字段。
- 新增的 `FocusContext` 只是把这些老字段的“当前焦点”显式化，属于旁路 trace，不反向驱动旧链路。
- `ContextualizedTurn` 也只是把上下文改写痕迹显式化，不替代语义解析结论。
- `hard_guard`、`slot_extractor`、`active_turn_resolver`、`context_recovery` 的边界没有改变。

## 实际修改文件清单

- 新增 [local_life_agent/domain/contextualized_turn.py](D:/javacode/hm-dianping/local_life_agent/domain/contextualized_turn.py)
- 新增 [local_life_agent/domain/focus_context.py](D:/javacode/hm-dianping/local_life_agent/domain/focus_context.py)
- 新增 [local_life_agent/domain/freshness.py](D:/javacode/hm-dianping/local_life_agent/domain/freshness.py)
- 新增 [local_life_agent/domain/location_context.py](D:/javacode/hm-dianping/local_life_agent/domain/location_context.py)
- 修改 [local_life_agent/domain/schemas.py](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- 修改 [local_life_agent/domain/graph_state.py](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)
- 修改 [local_life_agent/domain/graph_state_model.py](D:/javacode/hm-dianping/local_life_agent/domain/graph_state_model.py)
- 修改 [local_life_agent/engine/subgraphs/understanding_subgraph.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py)
- 新增 [local_life_agent/tests/test_phase5_context_trace_v0.py](D:/javacode/hm-dianping/local_life_agent/tests/test_phase5_context_trace_v0.py)

## 明确没有做的后续阶段内容

- 未做 4a：`ContextualizedTurn V1 + MixedIntent terminal policy`
- 未做 4b：`FocusContext V1 + FocusResolver`
- 未重写 `graph_builder`
- 未重写 `planning_subgraph`
- 未迁移 `target_resolve` 权威
- 未引入 Redis SessionStore
- 未做 ResponseContract V2
- 未做 complex_orchestrator / MapReduce

## 测试结果

- `python -m pytest local_life_agent/tests/test_phase5_context_trace_v0.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q` -> 17 passed, 2 xfailed
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> 26 passed
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q` -> 6 passed
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q` -> 7 passed
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` -> 7 passed, 1 skipped
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_05_graph.py -q` -> 88 passed
- `python -m pytest local_life_agent/tests/test_stage14_verification.py -q` -> 5 passed
- `python -m compileall local_life_agent` -> passed
- `python -m pytest local_life_agent/tests -q` -> 1353 passed, 37 skipped, 2 xfailed

## 是否建议继续做 4c / 4d / 4e

建议继续推进后续第一层工作，但应先按顺序做 4a / 4b 的消费逻辑验收，再考虑更深的引用边界收口。当前 4p 只提供 trace 载体，不适合直接跳到更强的 first-layer policy 改造。
