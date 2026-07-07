# 第三层 Claim Verifier 设计

本文件设计第三层的 claim-based verification：先抽取 claim，再与证据对齐，而不是只做文本规则。

## 1. 当前真实 verifier

当前 verifier 入口：

```text
verify_answer(answer, evidence, task_type)
```

真实实现是混合式：

1. 构造 mock answer plan
2. 运行 heuristic verify
3. 判断是否需要 LLM verifier
4. 必要时调用 `B2MiniVerifier`
5. 返回 `passed / issues / suggested_fix / verification_mode`

证据：

- `local_life_agent/answer/verifier.py:625-664`
- `local_life_agent/answer/verifier.py:219-232`
- `local_life_agent/answer/b2_mini_verifier.py:362-558`

## 2. 现状问题

- verifier 主要依赖中文关键词和文本规则
- 复杂回答没有结构化 claim 对齐
- LLM verifier 只在复杂类型触发
- 没有独立 `ClaimExtractor`

## 3. 目标设计

### 3.1 `AnswerClaim`

建议字段：

```python
AnswerClaim:
    claim_id: str
    facet: str
    value: str | dict
    source_type: str
    evidence_ids: list[str]
    confidence: float
    allow_verbalization: bool
    must_mention: bool
```

### 3.2 `ClaimExtractor`

职责：

- 从 draft_response 中抽取 claim
- 支持单店事实、推荐、对比、探索规划、澄清 / fallback
- 输出结构化 claims，不输出最终结论

### 3.3 `ClaimVerifier`

职责：

- 将 claim 与 `EvidencePack` / `GlobalEvidencePack` 对齐
- 生成：
  - `supported`
  - `unsupported`
  - `contradicted`
  - `unknown`
- 对不可裁决部分保留 unknown

### 3.4 `VerifierResult`

建议字段：

```python
VerifierResult:
    passed: bool
    issues: list[str]
    recoverable: bool
    verifier_mode: Literal["deterministic", "llm"]
    suggested_fix: str | None
    unsupported_claims: list[str]
    unknown_claims: list[str]
```

## 4. 目标验证链

```text
draft_response
  -> claim_extractor
  -> claim_verifier
  -> verifier_result
  -> rewrite_or_fallback
```

## 5. 当前代码中能复用的事实

- `AnswerPlan` 已有 `allowed_claims`、`required_claims`、`forbidden_claims`、`must_mention_unknowns`
- `AnswerPlan` 还含有 `grounded_facts`、`facet_statuses`、`unknown_fields`、`failed_tools`
- `decision_to_answer_plan()` 已经在向 claim 化靠拢

证据：

- `local_life_agent/domain/schemas.py:1304-1354`
- `local_life_agent/domain/decision.py:120-236`
- `local_life_agent/answer/answer_plan_builder.py:54-245`

## 6. 设计原则

- claim 先于文本
- 证据先于修辞
- unknown 不能被修成事实
- 推荐 / 对比 / 规划必须保留 trade-off
- verifier 的职责是裁决，不是补写事实

## 7. 14 种本地生活 Claim 类型

以下 claim 类型覆盖本地生活 Agent 当前需要处理的所有 fact 类型。

| # | claim_type | facet | 证据来源字段 | 当前 verifier 覆盖 |
|---|---|---|---|---|
| 1 | `shop_name` | 店名 | `ToolResult(shop_name)` | ❌ 无独立校验 |
| 2 | `shop_address` | 地址 | `ToolResult(address)` | ❌ 无独立校验 |
| 3 | `shop_phone` | 电话 | `ToolResult(phone)` | ❌ 无独立校验 |
| 4 | `open_status` | 营业状态 | `ToolResult(business_status)` | ✅ `verifier.py:270-290` 关键词规则 |
| 5 | `distance` | 距离 | `ToolResult(distance)` | ✅ `verifier.py:304-327` 关键词规则 |
| 6 | `rating` | 评分 | `ToolResult(rating)` | ⚠️ `verifier.py:333-336` 仅评分正则 |
| 7 | `avg_price` | 人均价格 | `ToolResult(avg_price)` | ⚠️ `verifier.py:340-345` 仅元/价格正则 |
| 8 | `coupon` | 优惠券 | `ToolResult(coupon_list)` | ✅ `verifier.py:246-266` 关键词规则 |
| 9 | `review_summary` | 评价摘要 | `ToolResult(reviews)` | ❌ 无独立校验 |
| 10 | `comparison_winner` | 比较胜出方 | `ComparisonMatrix` | ⚠️ `verifier.py:400-474` 关键词规则 |
| 11 | `comparison_tradeoff` | 比较取舍 | `ComparisonMatrix` | ❌ 无独立校验 |
| 12 | `recommendation_rank` | 推荐排序 | `RankingPolicy` | ❌ 无独立校验 |
| 13 | `exploration_stage` | 探索阶段 | `exploration_stages` | ❌ 无独立校验 |
| 14 | `capability` | 能力说明 | 无（不属于本地生活事实） | ❌ n/a |

### Claim 与 AnswerClaim 的映射

每类 claim 的 `AnswerClaim` 映射：
- `claim_id`：`"{claim_type}_{shop_id}_{index}"`（如 `"open_status_shop123_0"`）
- `facet`：上表中的 `facet`
- `value`：对应的结构化值（如营业状态为 `{"status": "营业中", "hours": "09:00-22:00"}`）
- `evidence_ids`：对应的 `ToolResult` ID 列表
- `confidence`：基于证据新鲜度/完整度（工具直接返回 → 1.0；LLM 推断 → ≤0.7）
- `allow_verbalization`：True（除比较结论不确定时为 False）
- `must_mention`：仅对用户明确询问的 facet 为 True

## 8. `AnswerClaim` 10 字段设计（从旧 06_generation 迁移）

```python
class AnswerClaim(BaseModel):
    """最小可验证回答单元"""
    claim_id: str
    facet: str
    value: str | dict
    source_type: str
    evidence_ids: list[str]
    confidence: float
    allow_verbalization: bool
    must_mention: bool
    uncertainty_note: str | None
    citation: EvidenceCitation | None
```

| 字段 | 必要性 | 说明 |
|---|---|---|
| `claim_id` | 必填 | 全局唯一，遵循 `{facet}_{shop_id}_{index}` |
| `facet` | 必填 | 必须是 14 种 claim 类型之一 |
| `value` | 必填 | 结构化值而非字符串 |
| `source_type` | 必填 | 证据源类型 |
| `evidence_ids` | 必填 | 每个 Claim 至少绑定 1 个 evidence_id |
| `confidence` | 必填 | 工具直接返回 -> 1.0 |
| `allow_verbalization` | 必填 | False 时 verifier 严格校验 |
| `must_mention` | 必填 | True 时 verifier 应为 fail |
| `uncertainty_note` | 可选 | 非 None 时需体现不确定语气 |
| `citation` | 可选 | 证据引用位置 |

### 与现有 AnswerPlan 的对接

```text
AnswerPlan.allowed_claims: list[str]  →  未来改为 list[AnswerClaim]
AnswerPlan.required_claims: list[str] →  未来改为 list[AnswerClaim]
```

当前 `AnswerPlan`（`schemas.py:1304-1354`）中 `allowed_claims` 是纯字符串列表。14 种 claim 类型提供了填充这些列表的完整值域。

