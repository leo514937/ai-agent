# 三层改造 Phase 1：第三层安全与确定性表达基础收敛报告

## 结论
- 批次结论：`PARTIAL PASS`
- 当前分支：`toolcall`
- 当前提交：`0852816`
- 结论依据：第三层安全边界和确定性 fallback 已完成收敛，`llm_verbalizer` / verifier 相关单测已恢复为全绿；但 `recommendation_flow` 与部分 `e2e` 仍有既有失败，且按本阶段范围不做大改 workflow，因此不满足全局 PASS。

## 修改前调研结论
- `ResponseMode` 已覆盖当前实际写入和消费的值，包含 `direct / direct_response / reject / clarify / fallback / answer / tool_answer / comparison / exploration_plan`。本阶段未新增重复枚举，也未改 workflow registry 主语义。
- `ResponseDirective` 已经存在，可作为最小回答中间结构；本阶段没有重新造 `ResponseContract`。
- `RewriteInstruction` 目前仍是 DTO，Phase 1 不做 claim-driven rewrite，也没有引入新的 rewrite 平行链路。
- `SingleShopFactComposer`、`_rule_based_verbalize()`、`_compose_single_shop_response()` 职责部分重叠，但本阶段只做最小收敛，不重写整套 composer 架构。
- `response_subgraph._h_answer_verify` 之前仍存在空态绕行风险：`template_fallback / llm_disabled` 分支会掩盖空 evidence / 空 draft 的安全问题，需要前置修复。
- `llm_verbalizer` 失败测试的真实根因主要是 `DecisionPlan` 缺少 `fallback_template_type`，导致确定性 composer 回退直接抛异常；另外 disabled / failure 元数据不够完整。
- `recommendation_flow` 的失败属于更上层的 workflow / 状态写回问题，本阶段不做大迁移，只记录结果。

## 本阶段实际改动
### 1. 修复确定性 composer 契约缺口
- 在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py) 的 `DecisionPlan` 中补了 `fallback_template_type` 字段，避免 `SingleShopFactComposer` 在 fallback 时访问缺字段崩溃。
- 在 [local_life_agent/answer/generator.py](/D:/javacode/hm-dianping/local_life_agent/answer/generator.py) 中把 `answer_plan` / evidence 上的 `fallback_template_type` 透传进 `DecisionPlan`。

### 2. 收敛 LLM disabled / failure 的 deterministic fallback
- 在 [local_life_agent/answer/generator.py](/D:/javacode/hm-dianping/local_life_agent/answer/generator.py) 中，LLM disabled 不再返回占位符文本，而是走已有 deterministic composer。
- 同时补齐了 disabled 路径的元数据：`fallback_reason`、`answer_fallback_reason`、`final_safety_status`、`verifier_result`、`verifier_failure_code`、`verifier_recoverable` 等。
- 单店 fast path 继续走 deterministic single shop 摘要，保留 `answer_source=deterministic_single_shop`，并补齐相关降级元数据。

### 3. 对齐 verbalizer 与 composer 的失败回退
- 在 [local_life_agent/answer/llm_verbalizer.py](/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py) 中，把 `llm_client_unavailable`、prompt 载入失败、调用异常、空输出等分支统一导向已有 deterministic composer。
- `_mark_template_fallback_metadata()` 补充了 `fallback_reason`、`verifier_recoverable`、`fallback_used`，让回退元数据更完整。
- `_rule_based_verbalize()` 仍保留保守表达，但现在可以稳定落到 composer，而不是因为缺字段崩溃。

### 4. 修复 verifier 安全边界
- 在 [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py) 中，`empty evidence / empty draft` 现在会优先进入失败路径，而不是被 `template_fallback / llm_disabled` 直接放行。
- 同文件中，外层 response loop 会根据 `rewrite_needed` / `verifier_recoverable` 直接 fallback，避免不可恢复的空态继续 rewrite。
- 这条修复只收紧安全边界，没有改 workflow registry，也没有引入新的中间对象。

## 已复用的已有对象
- `ResponseMode`：直接复用，没有新增平行枚举。
- `ResponseDirective`：仍然作为最小回答中间结构保留，没有新增新 DTO 替代它。
- `RewriteInstruction`：继续保留为现有 DTO，本阶段没有扩展成 claim-driven rewrite。
- `SingleShopFactComposer`：作为 deterministic fallback 的主实现继续复用。

## 第 0 批遗留的修复情况
- 已修复：
  - `test_llm_verbalizer.py` 的 fallback / metadata 契约问题。
  - `response_subgraph` 的空 evidence / 空 draft 安全边界。
  - `DecisionPlan` 缺少 `fallback_template_type` 导致的 composer 崩溃。
- 仍遗留：
  - `test_recommendation_flow.py` 的 closed / failed shop 过滤、`last_recommendation_list` 写回、以及后续“第一家”引用工具链。
  - `test_e2e_llm_main_path.py` 的 ordinal / deictic follow-up 路径仍会落到 clarification fallback。

## 实际修改文件
- [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [local_life_agent/answer/generator.py](/D:/javacode/hm-dianping/local_life_agent/answer/generator.py)
- [local_life_agent/answer/llm_verbalizer.py](/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py)
- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py)

## 明确没有做的内容
- 没有改 `workflow_registry.py` 主语义。
- 没有拆 `discovery_decision`。
- 没有新增 recommendation / comparison workflow。
- 没有引入 `ClaimExtractor` / `ClaimVerifier`。
- 没有引入 `ResponseContract V1/V2`。
- 没有做 `deterministic_tool -> single_shop_fact_workflow` 迁移。
- 没有重做 `ContextualizedTurn / FocusContext`。
- 没有做 ranking 或 target resolution 的大范围迁移。

## 测试结果
### 已通过
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`，`14 passed`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`，`23 passed`
- `python -m pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`，`4 passed`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`，`10 passed`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`，`6 passed`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`，`24 passed`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`，`7 passed`
- `python -m pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q`，`27 passed`
- `python -m compileall local_life_agent`，通过

### 仍失败
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 失败点集中在 recommendation 的结果过滤、会话写回和 follow-up 引用链路。
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - 失败点集中在 ordinal / deictic 跟随仍落入 `clarification_fallback_workflow`。

### 汇总
- 最近一次合并回归：`51 passed, 8 warnings`
- 这表示第三层安全与确定性表达基础已经收敛，但全局链路仍受 recommendation / e2e 遗留影响。

## 是否建议进入 Phase 2
- 建议：`可以进入，但必须按最小安全边界继续`
- Phase 2 优先级建议：
  1. 先处理 recommendation 流的会话写回与 follow-up 引用稳定性。
  2. 再处理 ordinal / deictic 的主路径路由。
  3. 最后再碰更大的 workflow 或 target resolution 重构。

## 备注
- 本阶段没有新增重复 DTO，也没有为“好看”而重构整套回答链路。
- Phase 1 的核心目标是“安全边界 + 确定性 fallback 对齐”，这部分已经达成。
