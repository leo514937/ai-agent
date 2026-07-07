# 第三层事实基线

本文件只基于当前仓库真实代码，梳理“回答层 / 可信表达层”的现状，不修改业务代码。

## 调研范围

本次重点扫描的第三层相关实现与直接依赖：

- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- `local_life_agent/engine/_compat.py`
- `local_life_agent/answer/answer_plan_builder.py`
- `local_life_agent/answer/generator.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/answer/verifier.py`
- `local_life_agent/answer/b2_mini_verifier.py`
- `local_life_agent/answer/final_response_builder.py`
- `local_life_agent/streaming/preview_policy.py`
- `local_life_agent/observability/trace.py`
- `local_life_agent/app.py`
- `local_life_agent/domain/decision.py`
- `local_life_agent/domain/schemas.py`
- 相关测试：`test_answer_verifier.py`、`test_llm_verbalizer.py`、`test_p4_evidence_decision_answer_protocol.py`、`test_p10_experience_performance.py`、`test_phase7_workflows.py`

## 第三层真实调用链

### 1. 主回答链

当前第三层主链路不是单独的 `answer_subgraph`，而是：

`execution_review_subgraph -> response_subgraph -> answer_plan_build -> answer_generate -> answer_verify -> final_response`

证据：

- `h_execution_review_subgraph()`：`local_life_agent/engine/subgraphs/execution_review_subgraph.py:57-103`
- `h_response_subgraph()`：`local_life_agent/engine/subgraphs/response_subgraph.py:128-173`
- `_h_answer_plan_build()`：`local_life_agent/engine/subgraphs/response_subgraph.py:181-188`
- `_h_answer_generate()`：`local_life_agent/engine/subgraphs/response_subgraph.py:191-265`
- `_h_answer_verify()`：`local_life_agent/engine/subgraphs/response_subgraph.py:268-336`
- `_h_final_response()`：`local_life_agent/engine/subgraphs/response_subgraph.py:345-357`

### 2. 进入 response_subgraph 的路由

`h_response_subgraph()` 先看 `response_mode`：

- `direct_response`
- `reject`
- `exploration_plan`

这些会直接 pass-through，不进入回答生成。

如果是澄清或 fallback，则直接走澄清/兜底文本。

否则才进入：

`answer_plan_build -> answer_generate -> answer_verify -> rewrite loop -> final_response`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:128-173`

### 3. 预览 / 流式出口

`app.event_stream()` 会把 `answer_delta` 再经过 `sanitize_preview_text(..., verified=False)`，只向前端输出通过预览策略的文本。

证据：

- `local_life_agent/app.py:120-240`
- `local_life_agent/streaming/preview_policy.py:29-43`

## 当前回答链关键函数

### `h_response_subgraph`

职责：

- 根据 `response_mode` 决定 pass-through / clarify / fallback / answer generation
- 控制 rewrite loop
- 控制 `final_response` 写入

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:128-173`

### `_h_answer_plan_build`

职责：

- 从 `p2_decision_plan` + `evidence_pack` 构造 `AnswerPlan`
- 如果没有 `p2_decision_plan`，则直接把 `decision_to_answer_plan(...)` 的结果验证成 `AnswerPlan`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:181-188`
- `local_life_agent/domain/decision.py:120-236`

### `_h_answer_generate`

职责：

- lazy import `local_life_agent.engine.graph_builder.generate_answer`
- 传入 `answer_plan`、`evidence_pack`、`rewrite_count`、`previous_violations`
- 注入 `conversation_continuity`
- 对 `single_shop` 场景做确定性修正：若 LLM 输出过于泛化，则调用 `_compose_single_shop_response()`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:191-265`
- `local_life_agent/engine/_compat.py:586-632`
- `local_life_agent/engine/subgraphs/response_subgraph.py:44-125`

### `_h_answer_verify`

职责：

- 调用 `verify_answer(draft_response, evidence, task_type)`
- 将 `passed / issues / suggested_fix / recoverable` 写回状态
- 若 `answer_source` 是 `template_fallback` 或 `llm_disabled`，直接跳过验证

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:268-336`
- `local_life_agent/answer/verifier.py:625-664`

### `_h_final_response`

职责：

- 把 `draft_response` 复制到 `final_response`
- 同时写 `preview_text`、`preview_policy_result`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:345-357`

## 当前回答相关对象

### `AnswerPlan`

`AnswerPlan` 已经是第三层最接近“回答合同”的结构，但它仍然混合了表达策略、证据摘要、探索阶段和验证结果。

现有字段包括：

- `answer_type`
- `facets`
- `target_resolution`
- `conflicting_facets`
- `ranking_policy`
- `answerable_facets`
- `unknown_facets`
- `failed_facets`
- `required_disclaimers`
- `target_shop_ids`
- `response_sections`
- `allowed_claims`
- `required_claims`
- `must_mention_unknowns`
- `forbidden_claims`
- `ranking_snapshot_id`
- `comparison_matrix_id`
- `tone`
- `fallback_template_type`
- `semantic_frame`
- `semantic_parse_source`
- `grounding_status`
- `missing_slot_type`
- `router_policy_decision`
- `router_policy_conflicts`
- `conversation_continuity`
- `exploration_stages`
- `stage_queries`
- `stage_evidence_requirements`
- `stage_statuses`
- `scene`
- `time`
- `location`
- `facet_statuses`
- `grounded_facts`
- `facet_reasons`
- `evidence_status`
- `comparison_support_status`
- `ranking_preserved`
- `unsupported_reasons`
- `unknown_fields`
- `failed_tools`
- `partial_fields`
- `evidence_review_result`
- `answer_verify_result`

证据：

- `local_life_agent/domain/schemas.py:1304-1354`

### `build_answer_plan()`

当前的 answer plan builder 会把 evidence、clarification、review_action、comparison matrix、facet triage、disclaimers、response sections、allowed claims 一并折叠进一个 `dict`，再交给 `AnswerPlan.model_validate()`。

证据：

- `local_life_agent/answer/answer_plan_builder.py:54-245`

### `decision_to_answer_plan()`

`DecisionPlan` 会通过 `decision_to_answer_plan()` 映射到 `AnswerPlan` 兼容字典：

- `answer_type`
- `target_shop_ids`
- `response_sections`
- `allowed_claims`
- `required_disclaimers`
- `must_mention_unknowns`
- `facet_statuses`
- `grounded_facts`
- `facet_reasons`

证据：

- `local_life_agent/domain/decision.py:120-236`

### `generate_answer()`

现有回答生成器是 LLM verbalizer 主路径，但它带有规则化 fallback：

- `llm_client` 不可用时回退 `_rule_based_verbalize()`
- prompt 加载失败时回退 `_rule_based_verbalize()`
- LLM 调用失败时回退 `_rule_based_verbalize()`
- verifier 不通过且可重写时会把原文留给图内 rewrite

证据：

- `local_life_agent/answer/generator.py:605-700`
- `local_life_agent/answer/llm_verbalizer.py:429-558`

### `verify_answer()`

`verify_answer()` 是混合式验证器：

- 先构造 `DecisionPlan`
- 再走启发式验证
- 根据 `answer_type` 和 `evidence` 决定是否需要 LLM 验证
- 不需要 LLM 时走 deterministic verify

证据：

- `local_life_agent/answer/verifier.py:625-664`
- `local_life_agent/answer/verifier.py:219-232`

### `sanitize_preview_text()`

预览文本不是最终答案，它只负责过滤未验证 claim 的流式输出。

证据：

- `local_life_agent/streaming/preview_policy.py:29-43`
- `local_life_agent/app.py:120-166`

### `build_final_response()`

这个 helper 目前存在，但在主回答链中没有看到被直接接入。

证据：

- `local_life_agent/answer/final_response_builder.py:6-17`

## GraphState / SessionState 相关事实

### 第三层主要读写的 `GraphState` 字段

从 response_subgraph 和 answer 代码看，第三层会读写这些核心字段：

- `p2_decision_plan`
- `evidence_pack`
- `response_mode`
- `pending_clarification`
- `final_response`
- `preview_text`
- `preview_policy_result`
- `answer_plan`
- `draft_response`
- `answer_source`
- `template_degraded`
- `fallback_used`
- `template_fallback_used`
- `answer_fallback_reason`
- `llm_verbalizer_error`
- `generated_llm_answer_before_fallback`
- `llm_verbalizer_violation`
- `llm_verbalizer_called`
- `llm_backend`
- `answer_verifier_result`
- `verifier_result`
- `verifier_failure_code`
- `verifier_unknown_fields`
- `verifier_unsupported_claims`
- `verifier_false_fields`
- `verifier_recoverable`
- `answer_verify_passed`
- `answer_verify_violations`
- `rewrite_needed`
- `rewrite_reason`
- `fallback_reason`
- `raw_text_fallback_source`
- `final_safety_status`
- `rewrite_count`
- `conversation_continuity`
- `response_route`

### `SessionState` 在第三层的角色

第三层不应再把会话状态当作事实源；它最多只通过 `_build_conversation_continuity()` 读取：

- `session_state_before`
- `current_shop`
- `last_task_type`
- `active_constraints`

这些内容只作为 verbalizer prompt 的连续性提示，不应直接当成事实。

证据：

- `local_life_agent/engine/_compat.py:586-632`

## 当前缺失的第三层能力

当前代码中尚未形成独立、完整的第三层可信表达契约：

- 没有独立的 `AnswerContract` / `ResponseContract`
- 没有独立的 `ClaimCitation` / `SourceSpan` / `EvidenceCitation`
- 没有统一的 `ConfidenceBand`
- 没有显式的 `AnswerTrace`
- 没有把 `build_final_response()` 作为权威出口
- `preview_text` 只是流式预览，不是最终答复合同
- `conversation_continuity` 只是 metadata，不是事实层
- `AnswerPlan` 仍然承担过多职责

## 23 个已知事实核验结果

以下逐条核验第二层需求中已知的 23 个事实，所有结论基于 `2026-07-05` 时点仓库代码。

### 事实 1: `response_subgraph` 是否根据 `response_mode` 分支处理 direct / reject / clarify / fallback / answer / tool_answer / comparison / exploration_plan

**结论：✅ 已确认。** `h_response_subgraph()` (`response_subgraph.py:128-173`) 根据 `response_mode` 做四路分支：

```python
# 第 133 行：`direct_response` / `reject` / `direct` / `exploration_plan` → pass-through
if response_mode in {_OUTER_ROUTE_DIRECT, _OUTER_ROUTE_REJECT, "direct_response", "exploration_plan"}:
    after = {**state, "response_route": _OUTER_ROUTE_PASS}

# 第 137 行：`clarify` / 有 pending_clarification → 澄清
if response_mode in {_OUTER_ROUTE_CLARIFY} or state.get("pending_clarification"):

# 第 145 行：`fallback` → 兜底
if response_mode in {_OUTER_ROUTE_FALLBACK}:

# 第 154 行：其他（answer / tool_answer / comparison）→ answer_plan_build → generate → verify → rewrite loop
```

**注意**：`tool_answer` 和 `comparison` 作为字符串并没有独立的分支处理——它们会落入"其他"分支走正常 answer_plan_build 路径。这意味着比较回答和普通回答在 response_subgraph 层面没有区分。

### 事实 2: `response_mode` 是否没有统一 Enum，而是分散字符串

**结论：✅ 确认。** `response_mode` 是纯字符串。证据：
- `_routes.py:310` 中 `_route_workflow_runner` 直接比较字符串 `"discovery_decision"`、`"planning_subgraph"`、`"comparison"`
- `response_subgraph.py:131` 中直接比较字符串 `"direct_response"`、`"exploration_plan"` 等
- 4 个独立 workflow 各自写不同的字符串值：`"direct_response"`（`direct_response_workflow.py:156`）、`"direct"`（`deterministic_tool_workflow.py:906`）、`"clarify"`（`clarification_fallback_workflow.py:230`）、`"exploration_plan"`（`exploration_planning_workflow.py:1093`）
- 没有任何地方做 `response_mode` 的有效性校验

### 事实 3: `_h_answer_plan_build` 是否读取 `p2_decision_plan`，写入 `answer_plan`

**结论：✅ 确认。** `response_subgraph.py:181-188`：

```python
def _h_answer_plan_build(state: GraphState) -> dict:
    p2_dp = state.get("p2_decision_plan")
    answer_plan_payload = decision_to_answer_plan(p2_dp, state.get("evidence_pack") or {}) if p2_dp is not None else {}
    answer_plan = AnswerPlan.model_validate(answer_plan_payload)
```

有 `p2_decision_plan` 时用它构建 `AnswerPlan`，没有时用空字典构造一个默认 `AnswerPlan`。

### 事实 4: `AnswerPlan` 是否包含 `allowed_claims`、`required_claims`、`forbidden_claims`、`must_mention_unknowns`、`factual_points`、`uncertainty_notes` 等字段

**结论：✅ 确认。** `schemas.py:1304-1354` 中 `AnswerPlan` 包含：

- `allowed_claims`（List[str]）
- `required_claims`（List[str]）
- `forbidden_claims`（List[str]）
- `must_mention_unknowns`（List[str]）
- `factual_points`（不在 `AnswerPlan` 本体，但在 `DecisionPlan` 中——`schemas.py:629`）
- `uncertainty_notes`（在 `DecisionPlan` 中——`schemas.py:641`）

**注意**：`factual_points` 和 `uncertainty_notes` 在 `DecisionPlan` 而非 `AnswerPlan` 中——`AnswerPlan` 本身有 89 个字段（`schemas.py:1304-1354`），但这两个是通过 `decision_to_answer_plan()` 映射进来的。

### 事实 5: `generate_answer()` 是否主要走 LLM verbalizer

**结论：✅ 确认。** `generator.py:605-700` 的 `generate_answer()`：
- 第 664 行：如果 `config.ENABLE_LLM_VERBALIZER == False` → 返回 `"【LLM 服务未启用】无法生成自然语言回答。"`
- 第 672 行：否则调用 `verbalize_decision_plan()`（`llm_verbalizer.py:429-558`）
- `llm_verbalizer.py:444-451`：`llm_client` 不可用时 fallback 到 `_rule_based_verbalize()`
- `llm_verbalizer.py:453-462`：prompt 加载失败时 fallback 到 `_rule_based_verbalize()`
- `llm_verbalizer.py:487-494`：LLM 异常时 fallback 到 `_rule_based_verbalize()`
- `llm_verbalizer.py:496-504`：LLM 返回无效时 fallback 到 `_rule_based_verbalize()`

所以主路径是 LLM verbalizer，但有多层规则化兜底。

### 事实 6: `ENABLE_LLM_VERBALIZER == False` 时是否返回固定占位符

**结论：✅ 确认——且是风险点。** `generator.py:664-670`：

```python
if not config.ENABLE_LLM_VERBALIZER:
    ...
    return "【LLM 服务未启用】无法生成自然语言回答。"
```

这是一个硬编码的占位符字符串，不会根据 `AnswerPlan` / `EvidencePack` 生成有意义的回答。即使有足够的证据，也会返回这句无意义的话。

### 事实 7: LLM 失败 / 超时 / 输出空时当前 fallback 行为是什么

**结论：✅ 确认。** `llm_verbalizer.py:429-558` 中 `verbalize_decision_plan()`：
- LLM client 不可用（`llm_client` 为 None）→ `_rule_based_verbalize()`（第 451 行）
- prompt 加载异常 → `_rule_based_verbalize()`（第 462 行）
- LLM 调用异常 → `_rule_based_verbalize()`（第 494 行）
- LLM 返回不合法 JSON → `_rule_based_verbalize()`（第 504 行）
- LLM 返回空 → `raise RuntimeError("empty_natural_response")`（第 514-515 行）——**这是 bug，不会被优雅处理**

`_rule_based_verbalize()`（`llm_verbalizer.py:231-349`）是保守模板：根据 `answer_type` 拼固定文本（单店：营业/优惠/距离；比较：先选 A 再看 B；推荐：附近最值得看 list；探索：阶段拆分）。

### 事实 8: `_compose_single_shop_response()` 是否只覆盖单店 coupon / open_status / distance 等有限 facet

**结论：✅ 确认——且是风险点。** `response_subgraph.py:44-125` 中的 `_compose_single_shop_response()` 只处理：
- `coupon`（第 69-81 行）
- `open_status`（第 82-92 行）
- `distance`（第 93-107 行）

**缺少**：`rating`、`avg_price`、`review_summary`、多个 facet 组合。对于多 facet 单店查询（如"这家评分多少、人均多少、有什么券"），这个 composer 只输出 `draft_text.strip() or f"{shop_name}的信息我已经整理好了。"`。

### 事实 9: `verify_answer()` 是否在 evidence 为空或 draft_response 为空时直接 pass

**结论：✅ 确认——且是 P0 风险。** `response_subgraph.py:290-298` 的 `_h_answer_verify()`：

```python
if not evidence or not state.get("draft_response", ""):
    return {
        "verify_result": "pass",   # ← 直接 pass
        ...
        "verifier_recoverable": True,
    }
```

当 `evidence` 为空或 `draft_response` 为空时，不做任何校验直接返回 `verify_result="pass"`。这意味着空回答或零证据回答会通过校验进入 `final_response`。

### 事实 10: verifier 是否主要通过中文关键词 / 文本规则校验 coupon、open_status、distance、rating、price、comparison 等事实

**结论：✅ 确认。** `verifier.py` 的 `_facet_rules()`（第 243-346 行）全靠中文关键词匹配：
- "有券"、"暂无可用券"、"优惠券"→ coupon 校验（第 246-266 行）
- "营业中"、"已打烊"、"营业状态"→ open_status 校验（第 270-290 行）
- "公里"、"直线距离"、"步行"等等 → distance 校验（第 304-327 行）
- "评分"、"分"、"星"→ rating 校验（第 333-336 行）
- "人均"、"价格"、"元"→ price 校验（第 340-345 行）
- "更好"、"更优"、"胜出"、"领先"→ comparison 校验（第 456-472 行）

`_comparison_issues()`（第 400-474 行）也是纯文本规则：检查"更好"、"更优"、"胜出"、"更适合"等关键词的出现模式。

### 事实 11: 是否存在 claim-based verification：从回答中抽取结构化 claims，再和 EvidencePack 对齐

**结论：❌ 确认不存在。** 当前 `verifier.py` 全量使用：
1. `_facet_rules()`（第 243 行）— 关键词规则
2. `_comparison_issues()`（第 400 行）— 关键词规则  
3. `B2MiniVerifier`（`b2_mini_verifier.py:362-558`）— LLM 做完整文本判断

没有任何 `ClaimExtractor` 模块，没有从文本中抽取 `(claim_type, shop_id, value, evidence_ref)` 的结构化步骤。

### 事实 12: LLM verifier 是否只在 comparison / exploration_plan 等复杂类型触发

**结论：✅ 确认。** `verifier.py:219-232` 的 `_needs_llm_verification()`：

```python
def _needs_llm_verification(plan, evidence):
    if answer_type in {"comparison", "exploration_plan", "exploration"}:
        return True
    if answer_type == "recommendation" and has comparison_matrix:
        return True
    if selected_targets > 2:
        return True
    if evidence.get("answer_verify_force_llm"):
        return True
    return False
```

否则走 `_deterministic_verify()`（第 498-622 行）的关键词规则。

### 事实 13: `_h_rewrite` 是否只是递增 rewrite_count，并没有构造结构化 RewriteInstruction

**结论：✅ 确认。** `response_subgraph.py:339-342`：

```python
def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1
    txt = state.get("draft_response", "")
    return {"draft_response": txt, "rewrite_count": rc}
```

写入 `draft_response` 原文不动，仅 `rewrite_count += 1`，没有任何结构化 `RewriteInstruction`。

**但 LLM verbalizer 内部有简单 rewrite instruction 文本**（`llm_verbalizer.py:134-152`）：当 `rewrite_count > 0` 时，在 prompt 中追加一段中文 rewrite 指令（如"请修正并重新输出"）。

### 事实 14: `MAX_REWRITE_ATTEMPTS` 的语义是否容易误解，实际重写次数是否等于配置值减一

**结论：✅ 确认——且是风险点。** `config.py:175` 中 `MAX_REWRITE_ATTEMPTS = 2`，但在 `_routes.py:279` 和 `llm_verbalizer.py:12` 中有：

```python
_GRAPH_REWRITE_LIMIT = max(1, MAX_REWRITE_ATTEMPTS - 1)  # = 1
```

所以实际 rewrite 上限是 **1 次**（配置值减一）。同时 `response_subgraph.py:156-157` 还叠加了 `BudgetContext.remaining("rewrite_budget")` 的限制，实际重写次数 ≤ min(配置限, 预算限)。

### 事实 15: `_h_fallback_answer` 的覆盖范围是否主要集中在单店营业、优惠券、工具失败、熔断、unknown/unsupported

**结论：✅ 确认。** `response_subgraph.py:422-491` 的 `_h_fallback_answer()`：
- 单店营业状态（第 450-467 行）
- 单店优惠券（第 468-472 行）
- 工具失败 / 熔断 / unknown / unsupported（第 473-485 行）

**缺少**：比较、推荐、探索规划的 fallback。如果 task_type 不是 `single_shop_query` 相关，退化为通用的"抱歉，暂时无法处理您的请求"（第 423 行）。

### 事实 16: `direct_response_workflow` 是否在第三层重新做关键词分类，例如退款、下单、你好、能做什么等

**结论：✅ 确认。** `direct_response_workflow.py:63-85` 的 `_classify_direct_response()` 中：

```python
# 第 73 行
if any(token in raw_text for token in ("退款", "交易", "下单", "支付", "预约", "订单", "rag")):
    return "forbidden"
# 第 81 行
if any(token in raw_text for token in ("能做什么", "支持什么", "支持哪些", "可以做什么")):
    return "capability"
# 第 83 行
if any(token in raw_text for token in ("你好", "嗨", "您好", "哈喽")):
    return "chat"
```

这与第一层的 `hard_guard` / `top_intent_router` 中的 `TopIntent` 分类有重叠。第一层 `_route_top_intent()`（`_routes.py:72-91`）已经做了 `chat`/`capability`/`unsafe`/`invalid` 分类，但 `direct_response_workflow` 再次做关键词匹配——两层之间的策略共享不透明。

### 事实 17: `deterministic_tool_workflow` 是否在回答层边界内自行完成目标解析、工具调用、EvidencePack 构建、AnswerPlan 构建、文本回答、verify

**结论：✅ 确认。** `deterministic_tool_workflow.py` 内部完整包含：
- **目标解析**：`_resolve_single_shop_target()`（第 293-596 行）
- **执行计划构建**：`_build_execution_plan()`（第 619-720 行）
- **工具调用**：通过 `ToolBatchExecutor` 执行（第 1046 行之后）
- **证据构建**：`build_evidence()`（`evidence_builder.py`）
- **AnswerPlan 构建**：`build_answer_plan()`（`answer_plan_builder.py`）
- **文本回答**：`_tool_result_to_text()`（第 771-846 行）
- **verify**：`verify_answer()`（第 889 行）

**绕过点**：`_build_success_patch()`（第 849-955 行）直接写 `final_response`（第 933 行）、`draft_response`（第 934 行）、`evidence_pack`（第 931 行），完全不经过 `response_subgraph` 的统一流水线。

### 事实 18: `exploration_planning_workflow` 是否在回答层边界内自行完成子目标构建、工具搜索、证据构建、确定性回答、verify

**结论：✅ 确认。** `exploration_planning_workflow.py` 内部完整包含：
- **子目标构建**：`_build_subgoals()`（第 460-542 行）
- **工具搜索**：`_tool_round_search()` + `_tool_round_expand()`（第 622-713 行）
- **证据构建**：`build_evidence_pack_from_tool_results()`（第 943 行）
- **AnswerPlan 构建**：`build_answer_plan_from_evidence()`（第 1008 行）
- **确定性回答**：`_compose_final_response()`（第 716-792 行）
- **verify**：`verify_answer_plan()`（第 1015 行）

**绕过点**：`_build_success_patch()`（第 795-837 行）直接写 `final_response`（第 824 行）、`draft_response`（第 825 行）、`evidence_pack`（第 822 行），完全不经过 `response_subgraph` 的统一流水线。

### 事实 19: 独立 workflow 是否会提前写 `final_response`，从而绕过统一 LLM verbalizer / verifier / ResponseContract

**结论：✅ 确认——且是 P0 风险。** 三个独立 workflow 都直接写 `final_response`：

| Workflow | 文件行 | 直接写 `final_response` |
|---|---|---|
| `direct_response_workflow` | `direct_response_workflow.py:159` | ✅ |
| `deterministic_tool_workflow` | `deterministic_tool_workflow.py:933` | ✅ |
| `exploration_planning_workflow` | `exploration_planning_workflow.py:824` | ✅ |

它们写入的 `final_response` 会被 `workflow_runner` 返回到 graph state，然后 `_route_workflow_runner()`（`_routes.py:311-320`）将它们路由到 `response_subgraph`。但 `response_subgraph.py:128-173` 的入口处对 `direct_response` 和 `exploration_plan` 做了 pass-through（第 133 行），对 `clarify` 和 `fallback` 不会重新写入——这意味着这些 workflow 的 `final_response` **实际上绕过了统一 LLM verbalizer 和 verifier**。

### 事实 20: 所有回答路径是否都有统一 `ResponseContract`

**结论：❌ 确认没有。** 当前没有任何路径输出 `ResponseContract`。当前输出是 `GraphState` 中的多个分散字段（`final_response`、`draft_response`、`preview_text`、`answer_source`、`verifier_result`、`answer_verify_passed` 等），没有统一的输出合同。

### 事实 21: 所有回答路径是否都能追踪 evidence_ref / claim_ref / verifier_result / degraded_reason

**结论：部分能。** 所有回答路径都设了：
- `answer_source`（标记来源：`llm_verbalizer` / `deterministic_tool_workflow` / `direct_response_workflow` 等）
- `answer_verify_passed` + `answer_verify_violations`
- `fallback_reason` / `answer_fallback_reason`

**但缺少**：
- `evidence_ref`（当前没有字段记录"final_response 中的哪句话来自 evidence 的哪个 item"）
- `claim_ref`（没有从文本中抽取 claim 并绑定 evidence）
- `degraded_reason` 的标准化（当前有 `template_degraded`、`fallback_used`、`template_fallback_used` 三个布尔值，互不统一）

### 事实 22: 第三层是否会写入或污染跨轮 SessionState

**结论：⚠️ 部分确认。** `response_subgraph.py` 中 `_h_answer_generate()` 调用 `_build_conversation_continuity(state)`（第 203 行），后者（`_compat.py:586-632`）只读取 `SessionState`，不写入。

但 `deterministic_tool_workflow.py` 在第 293-596 行的目标解析中反复读取 `session_state` 和 `session_state_before`。`exploration_planning_workflow.py` 第 1046 行的 `apply_state_update_plan()`（`state_update_plan_preview`）可能会写 `SessionState`。

**核心发现**：`SessionState` 在独立 workflow 和 `response_subgraph` 之间没有被隔离——workflow 在写入 `final_response` 后可能已经修改了 `SessionState`，但 `response_subgraph` 不会再次校验。

### 事实 23: 第三层 trace 是否能解释 answer_plan、generation、verification、rewrite、fallback、final_response 的耗时和原因

**结论：⚠️ 部分满足。** 当前 `TurnTrace`（`trace.py:80-198`）能收集：
- `response_mode`、`answer_source`、`verifier_result`、`fallback_reason`、`rewrite_count`
- `trace spans` 和 `event log`

**但不足**：
- 没有每个阶段的独立 span（generation / verification / rewrite / fallback 合并为一个长 span）
- 没有每个阶段的耗时拆分
- 没有 `rewrite_reason` 的结构化记录（当前只是字符串）
- 没有 `degraded_reason` 的标准化枚举
- `preview` / `final` / `verify` 之间的关系没有完整 trace

`Trace` 证据：`trace.py:386-573` 的 `build_turn_trace()` 从整个 graph state 拼 trace，`response_subgraph` 内部没有插入额外的 trace span。

## 文档与代码偏差

与"第三层 = 可信表达层"的目标相比，当前真实代码的偏差主要是：

- 现有主链路是 `response_subgraph`，不是独立的 `answer_subgraph`
- `generate_answer()` 仍然以 LLM verbalizer 为主，可靠性依赖后验 verifier
- `build_final_response()` 是独立 helper，但不是主链路权威出口
- 当前缺少显式的 citation / source / confidence / uncertainty 契约
- `sanitize_preview_text()` 只约束流式预览，不约束完整答复结构

## 所有 `response_mode` / `response_route` 值域和来源

### `response_mode` 取值

| 值 | 编程写入位置 | 从 GraphState 消费位置 |
|---|---|---|
| `"direct_response"` | `direct_response_workflow.py:156` | `response_subgraph.py:133` |
| `"direct"` | `deterministic_tool_workflow.py:906` | `response_subgraph.py:133`（`_OUTER_ROUTE_DIRECT`） |
| `"reject"` | orchestration_router_shadow | `response_subgraph.py:133` |
| `"exploration_plan"` | `exploration_planning_workflow.py:819,1093` | `response_subgraph.py:133` |
| `"clarify"` | `clarification_fallback_workflow.py:230` | `response_subgraph.py:137`（`_OUTER_ROUTE_CLARIFY`） |
| `"fallback"` | `clarification_fallback_workflow.py:230`（部分情况） | `response_subgraph.py:145`（`_OUTER_ROUTE_FALLBACK`） |
| `"answer"` | planning_subgraph 内设 | 无独立分支——落入通用 answer 路径 |
| `"tool_answer"` | planning_subgraph 内设 | 无独立分支——落入通用 answer 路径 |
| `"comparison"` | planning_subgraph 内设 | `_routes.py:318`（决定走 planning_subgraph 而非 response_subgraph） |

**注意**：`"answer"`、`"tool_answer"`、`"comparison"` 作为 response_mode 字符串存在，但 `response_subgraph.py:133-152` 的四路分支中没有一个专门处理它们——它们都落入第 154 行的通用 answer 路径。

### `response_route` 取值

| 值 | 编程写入位置 | 含义 |
|---|---|---|
| `"pass"` | `response_subgraph.py:136,164` | 正常通过 |
| `"clarify_ready"` | `response_subgraph.py:142` | 澄清已就绪 |
| `"fallback_ready"` | `response_subgraph.py:150,170` | 兜底已就绪 |

`_GRAPH_RESPONSE_ROUTES`（`_routes.py:443-447`）将这三个 route 映射到 `state_update_plan`。

## 所有 `final_response` 写入位置

| 文件 | 行号 | 路径 | 是否经过统一 verifier |
|---|---|---|---|
| `response_subgraph.py:348` | `_h_final_response()` | `draft_response → final_response` | ✅ 已 verify |
| `response_subgraph.py:382-418` | `_h_clarify_response()` | 直接写 final_response | ❌ 未进入统一 generate/verify |
| `response_subgraph.py:487` | `_h_fallback_answer()` | 直接写 final_response | ❌ 未进入统一 generate/verify |
| `direct_response_workflow.py:159` | `run_direct_response_workflow()` | 直接写 final_response | ❌ 未进入统一 generate/verify |
| `deterministic_tool_workflow.py:933` | `_build_success_patch()` | 直接写 final_response（workflow 内已 verify） | ⚠️ 绕过 response_subgraph verifier |
| `deterministic_tool_workflow.py:1028` | `_build_clarify_patch()` | 直接写 final_response | ❌ |
| `exploration_planning_workflow.py:824` | `_build_success_patch()` | 直接写 final_response（workflow 内已 verify） | ⚠️ 绕过 response_subgraph verifier |
| `exploration_planning_workflow.py:233` | `_build_fallback_patch()` | 直接写 final_response | ❌ |
| `clarification_fallback_workflow.py:233` | `run_clarification_fallback_workflow()` | 直接写 final_response | ❌ |

## 缺失能力清单

当前代码中完全缺失或严重不足的能力：

| 能力 | 状态 | 说明 |
|---|---|---|
| `ResponseMode` 统一 Enum | ❌ 缺失 | 散落 7+ 个字符串值，无有效性校验 |
| `ResponseContract` | ❌ 缺失 | 无统一输出合同 |
| `ResponseInput` | ❌ 缺失 | 无统一第三层入口 DTO |
| `ClaimExtractor` | ❌ 缺失 | 无从 draft 中抽取 claim 的模块 |
| `ClaimVerifier` | ❌ 缺失 | 当前只有文本规则和 LLM 双重校验 |
| `RewriteInstruction` | ❌ 缺失 | `_h_rewrite` 只递增计数 |
| `ResponsePolicy` | ❌ 缺失 | 无按 answer_type 控制策略 |
| `AnswerContract` | ❌ 缺失 | `AnswerPlan` 职责过重 |
| `FallbackDirective` | ❌ 缺失 | fallback 指令分散在 4+ 位置 |
| `ClarificationResponsePlan` | ❌ 缺失 | 澄清无结构化计划 |
| `MultiTypeDeterministicComposer` | ❌ 缺失 | 只有单店 composer |
| `EvidenceRefTrace` | ❌ 缺失 | 无法追踪 answer 到 evidence |

