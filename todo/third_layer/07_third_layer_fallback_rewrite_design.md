# 第三层 Fallback / Rewrite 设计

本文件设计第三层的重写和降级策略，避免当前 `_h_rewrite` 只是递增计数。

## 1. 当前真实行为

### `_h_rewrite`

当前实现仅仅：

- `rewrite_count += 1`
- `draft_response` 原样回写
- 依赖外层循环再次走 `generate -> verify`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:339-342`

### rewrite loop

`response_subgraph` 依赖 `rewrite_count` 与 `rewrite_limit` 控制循环次数。

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:154-173`
- `local_life_agent/engine/_compat.py:586-632`

## 2. 当前问题

- 没有 `RewriteInstruction`
- `MAX_REWRITE_ATTEMPTS` 的语义不够直观
- rewrite 只是次数控制，不是结构化修复
- fallback composer 主要偏单店
- 推荐 / 对比 / 探索规划的 fallback 不足

## 3. 目标设计

### 3.1 `VerifierViolation`

建议字段：

```python
VerifierViolation:
    code: str
    message: str
    claim_id: str | None
    severity: Literal["info", "warning", "error"]
    recoverable: bool
```

### 3.2 `RewriteInstruction`

建议字段：

```python
RewriteInstruction:
    instruction_id: str
    target_claim_ids: list[str]
    remove_claim_ids: list[str]
    strengthen_claim_ids: list[str]
    add_uncertainty_notices: list[str]
    preserve_tradeoff: bool
    fallback_mode: Literal["rewrite", "deterministic_fallback", "clarify", "fail"]
```

### 3.3 `rewrite_or_fallback`

职责：

- 根据 violation 生成 rewrite instruction
- 能重写时优先局部修复
- 不能重写时降级为 deterministic fallback / clarify / trusted failure

## 4. fallback 设计

### 4.1 单店事实 fallback

当前 `_h_fallback_answer()` 已经覆盖：

- 营业状态
- 优惠券
- 距离
- 工具失败 / 熔断 / unknown / unsupported

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:422-491`

### 4.2 推荐 / 对比 fallback

目标是：

- 不能只套单店文案
- 应输出保守的 recommendation / comparison 文案
- 必须保留不确定性和 trade-off

### 4.3 探索规划 fallback

目标是：

- 保留阶段信息
- 说明哪些阶段不完整
- 不要把规划硬压成单店事实

## 5. rewrite 策略原则

- 只修 claim，不重造事实
- 只删 unsupported claim，不放大推断
- 不确定项要显式保留
- 复杂场景优先 deterministic fallback

## 6. RewritePolicy 按 answer_type 控制

```python
class RewritePolicy(BaseModel):
    """按 answer_type 控制的 rewrite 策略"""
    max_rewrite_attempts: int                              # 最大重写次数
    deterministic_fallback_on_failure: bool                # 重写失败时是否降级到 deterministic
    need_llm_verbalize_on_rewrite: bool                    # 重写时是否需要 LLM 重新生成
    unsupported_claim_action: Literal["remove", "weaken", "keep_with_uncertainty"]
    contradicted_claim_action: Literal["correct_to_unknown", "remove", "keep_contradiction"]
```

### 按 answer_type 的策略表

| answer_type | max_rewrite_attempts | deterministic_fallback_on_failure | need_llm_verbalize_on_rewrite | unsupported_claim_action | contradicted_claim_action |
|---|---|---|---|---|---|
| `single_shop` | 1 | True | False（重试走 deterministic） | remove | correct_to_unknown |
| `recommendation` | 2 | False | True | weaken | remove |
| `comparison` | 2 | True（保留 trade-off） | True | weaken | keep_contradiction（保留为 trade-off） |
| `exploration_plan` | 1 | True | True | keep_with_uncertainty | correct_to_unknown |
| `clarify` | 0 | n/a | n/a | n/a | n/a |
| `fallback` | 0 | n/a | n/a | n/a | n/a |

### 当前代码与目标的差距

| 项目 | 当前状态 | 目标 |
|---|---|---|
| rewrite 策略 | `verifier.py:219-232` 硬编码判断 | `RewritePolicy` 策略对象 |
| rewrite 指令 | `response_subgraph.py:339-342` 只递增计数 | `RewriteInstruction` 结构化指令 |
| unsupported 处理 | 无特定逻辑 | 按策略表执行 remove/weaken/keep |
| contradicted 处理 | 无特定逻辑 | 按策略表执行 correct/remove/keep |

## 7. 6 类 DeterministicComposer（从旧 07_verification 迁移）

### Composer 1：`compose_single_shop_facts(shop_id, facets, evidence)`

覆盖 coupon/open_status/distance/rating/avg_price/review_summary/address/phone（8 个 facet）。
fallback 文案不使用"店铺信息已整理好"等无意义兜底。
当前近似代码：`response_subgraph.py:44-125`（仅覆盖其中 3 个 facet）。

### Composer 2：`compose_recommendation(shops, ranking_policy, evidence)`

输出排序列表，排名不能静默变化，推荐理由必须可解释。
当前近似代码：`llm_verbalizer.py:300-320`（规则化推荐模板）。

### Composer 3：`compose_comparison(comparison_matrix, shop_evidence_list)`

输出各 facet 对比 + winner（如有足够证据）+ trade-off（如证据不足）。
不能强行给出无依据 winner。
当前近似代码：`llm_verbalizer.py:270-295`（规则化对比模板）。

### Composer 4：`compose_exploration_stages(exploration_stages, stage_evidence)`

阶段化文本，每阶段标明已完成/进行中/未开始和关键信息。
当前近似代码：`llm_verbalizer.py:332-345`（规则化探索模板）。

### Composer 5：`compose_clarify(pending_clarification, missing_info)`

结构化 clarify 文案：为什么需要确认、需要用户提供什么。
当前近似代码：`response_subgraph.py:382-418`（`_h_clarify_response`）。

### Composer 6：`compose_fallback(fallback_reason, task_type, error_info)`

按 task_type 输出保守文案，不能输出通用的"抱歉，暂时无法处理"。
当前近似代码：`response_subgraph.py:422-491`（`_h_fallback_answer`）。

### 集成流程

```text
VerifierViolation 列表
  → RewritePolicy（按 answer_type 选择策略）
  → 需要 rewrite？
    → 是：生成 RewriteInstruction
        → LLM verbalizer 或 DeterministicComposer
    → 否：需要 fallback？
        → 是：选对应的 DeterministicComposer（1-6）
        → 否：输出 final_response
```

