# Phase 5 报告：4p trace-only + 4a ContextualizedTurn V1 + 4b FocusContext V1 / FocusResolver

## 结论

PASS

本次完成了第 5 批中的 4p、4a、4b：

- 4p：新增 `ContextualizedTurn V0`、`FocusContext V0`、`FreshnessMeta`、`LocationContext` 的 trace DTO。
- 4a：`ContextualizedTurn V1` 已接入理解层与入口层的 mixed-intent 终止策略。
- 4b：`FocusContext V1` 与 `FocusResolver` 已接入，旧字段仍保留兼容，不做权威迁移。

全量测试通过，未发现对 recommendation / comparison / single_shop 主链路的持续性回归。

## 第 4 批前置验收结果

- 3a 已完成：`RewriteInstruction` 已接入 rewrite loop。
- 3b 已完成：完整 composer 已覆盖主要 answer_type。
- 3c 已完成：`ClaimExtractor / ClaimVerifier L1` 可用。
- 3d 已完成：recommendation / comparison 已有真实独立 workflow。
- 3e 已完成：comparison winner 已由 matrix / RankingPolicy / DecisionPlan 约束。
- 3f 已完成：exploration workflow 已接入共享能力。
- 统一 `final_response` / `ResponseContractV1` 出口保持有效。
- recommendation / comparison / single_shop 主链路测试保持通过。

## 修改前真实代码调研结果

- 第一层原本只有 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 这些会话事实字段。
- `intake_guard_router` 的实际路由仍然是 `top_intent -> local_life / terminal`，没有 mixed-intent 的显式终止策略。
- `understanding_subgraph` 已有 context recovery，但 `ContextualizedTurn` / `FocusContext` 只是 trace-only，未消费到语义解析。
- `active_turn_resolver` 负责 pending clarification 的数字、序号、名称匹配，但没有统一的 focus DTO。
- `context_recovery` 仍然是实体恢复和 comparison target 恢复的权威，不应被第一层替代。
- `slot_extractor` 已覆盖 `task_type`、`preference`、`filters`、`comparison_targets`、`ordinal_references`、`deictic_references`，不适合重复造一套解析权威。
- `hard_guard` 只做 allow / deny，不承担 local_life 路由权威。

## ContextualizedTurn V1 实现说明

新增并接入了：

- `local_life_agent/domain/contextualized_turn.py`
- `local_life_agent/engine/subgraphs/understanding_subgraph.py`

`ContextualizedTurn` 在 V1 中补充了：

- `mixed_intent`
- `terminal_policy`

接入策略：

- 在 `understanding_subgraph._h_semantic_parse` 中，先用 `FocusResolver` 构造 contextualized query，再交给 `parse_semantic_frame`。
- 只在“纯引用补全”场景改写 contextualized query。
- 遇到明确的 coupon / 营业 / 距离等强语义，保留原句，避免上下文改写覆盖原始意图。
- 遇到比较句，默认不做第一层改写，保留原始比较结构给现有语义解析器。

这样做的效果是：

- `“这家有券吗”` 可以使用当前焦点补全到具体店名。
- `“第一家有券吗”`、`“第一家和第二家比一下”` 不会被过度改写，避免把 coupon / comparison 语义冲掉。

## FocusContext V1 实现说明

新增并接入了：

- `local_life_agent/domain/focus_context.py`
- `local_life_agent/target/focus_resolver.py`

`FocusContext` 在 V1 中补充了：

- `resolution_status`
- `clarification_needed`

`FocusResolver` 负责：

- 解析 `这家 / 那家 / 它 / 刚才那个`
- 解析 `第一家 / 第二个 / 第三家`
- 解析 recommendation list 引用
- 解析 comparison targets
- 只做引用和焦点识别，不做实体搜索和门店搜索

接入结果：

- 仍保留 `current_shop`、`last_recommendation_list`、`comparison_targets` 作为旧字段权威。
- `FocusContext` 只做可观察的焦点视图，不替代旧字段。
- 缺上下文时，`clarification_needed=True`，让第一层更容易显式澄清，而不是误入 terminal fallback。

## MixedIntent terminal policy

本次在 `local_life_agent/engine/subgraphs/intake_guard_router.py` 加了一个保守的 mixed-intent 保留策略：

- 若 top intent 已经是 `local_life`，继续走 local-life。
- 若 top intent 不是 `local_life`，但 `FocusResolver` 命中本地生活焦点或本地生活引用信号，则保留 local-life 路由。
- 若没有本地生活信号，则仍然终止，不把一般聊天强行送入 local-life。

这条策略只做“保留 local-life”，不扩大为全局意图控制器。

## 与旧字段的兼容关系

- `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 仍是旧链路权威。
- `FocusContext` 是它们的显式 trace 视图，不反向驱动老字段删除。
- `ContextualizedTurn` 只是对上下文改写痕迹的显式化，不替代 `semantic_frame`。
- `hard_guard`、`slot_extractor`、`active_turn_resolver` 的边界没有被重写。
- `context_recovery` 仍然保留实体恢复职责，没有被第一层抢权。

## 实际修改文件清单

- 新增 [local_life_agent/target/focus_resolver.py](D:/javacode/hm-dianping/local_life_agent/target/focus_resolver.py)
- 修改 [local_life_agent/domain/contextualized_turn.py](D:/javacode/hm-dianping/local_life_agent/domain/contextualized_turn.py)
- 修改 [local_life_agent/domain/focus_context.py](D:/javacode/hm-dianping/local_life_agent/domain/focus_context.py)
- 修改 [local_life_agent/engine/subgraphs/understanding_subgraph.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py)
- 修改 [local_life_agent/engine/subgraphs/intake_guard_router.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py)
- 修改 [local_life_agent/tests/test_phase5_context_trace_v0.py](D:/javacode/hm-dianping/local_life_agent/tests/test_phase5_context_trace_v0.py)
- 新增 [local_life_agent/tests/test_phase5_context_v1.py](D:/javacode/hm-dianping/local_life_agent/tests/test_phase5_context_v1.py)

## 明确没有做的后续阶段内容

- 未做 4c / 4d / 4e
- 未迁移 target_resolve 权威
- 未做 Redis SessionStore
- 未做 ResponseContract V2
- 未做 complex_orchestrator / MapReduce
- 未重写 graph_builder
- 未重写 planning_subgraph

## 测试结果

- `python -m pytest local_life_agent/tests/test_phase5_context_v1.py -q` -> 5 passed
- `python -m pytest local_life_agent/tests/test_phase5_context_trace_v0.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q` -> 17 passed, 2 xfailed
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> 26 passed
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` -> 7 passed, 1 skipped
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_p6_complex_query_matrix.py -q` -> 13 passed
- `python -m compileall local_life_agent` -> passed
- `python -m pytest local_life_agent/tests -q` -> 1358 passed, 37 skipped, 2 xfailed

## 是否建议继续做 4c / 4d / 4e

建议继续，但前提是后续仍保持第一层只做引用与上下文识别，不把实体搜索和第二层路由权威搬到第一层。
下一步如果进入 4c / 4d / 4e，建议优先沿着“引用边界 -> 澄清边界 -> 规则收口”继续，而不是扩大 FocusResolver 的职责。
