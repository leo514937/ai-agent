# Day3：RAG Dirty Data Guardrail 与 Clean Evidence Pack

> 目标：补齐尚未完成的 Day2.5，把 RAG 脏数据治理单独作为 Day3 的 P0 改造。  
> 前置：Day1 Context Boundary 已完成；Day2 AnswerContract 已完成。  
> 产出：RAG 不再把低相关、跨店、错误 facet、污染 sibling 证据交给 LLM。

---

## 1. Day3 要解决什么

当前问题：

```text
RAG 返回内容与 query 相关度不大。
RAG evidence 可能跨店。
问环境召回券信息。
问约会召回泛泛综合评价。
父子检索 sibling 补全可能把无关信息带入 context。
弱证据也可能被塞给 LLM，导致模型强答。
```

Day3 目标：

```text
召回之后、进入 LLM 之前，必须完成 evidence 准入。
```

完整链路：

```text
raw retrieved chunks
  ↓
EvidenceJudgement
  ↓
drop_cross_shop_evidence
  ↓
drop_forbidden_facet_evidence
  ↓
drop_low_relevance_evidence
  ↓
limit_sibling_context
  ↓
Clean Evidence Pack
  ↓
low_quality_degradation
```

---

## 2. 新增 LocalLifeRagGuardrail

### 2.1 新增文件

```text
learning-agent-service/src/learning_agent_service/local_life/rag_guardrail.py
learning-agent-service/src/learning_agent_service/local_life/rag_relevance.py
```

---

### 2.2 核心职责

```text
1. validate_retrieval_plan
2. judge_evidence_relevance
3. drop_cross_shop_evidence
4. drop_forbidden_facet_evidence
5. drop_low_relevance_evidence
6. limit_sibling_context
7. build_clean_evidence_pack
8. return_low_quality_degradation
```

---

## 3. EvidenceJudgement

新增：

```python
@dataclass(frozen=True)
class EvidenceJudgement:
    evidence_id: str
    shop_id: int | None
    shop_match: bool
    facet: str | None
    facet_match: bool
    lexical_overlap: float
    semantic_score: float | None
    rerank_score: float | None
    metadata_match: float
    support_level: str  # strong / medium / weak / irrelevant
    drop_reason: str | None
    debug: dict
```

---

## 4. RagGuardrailResult

新增：

```python
@dataclass(frozen=True)
class RagGuardrailResult:
    clean_items: list
    weak_items: list
    dropped_items: list
    judgements: list[EvidenceJudgement]
    rag_quality_status: str  # ok / weak / empty / dirty
    dirty_reasons: list[str]
    metrics: dict
```

---

## 5. Evidence 准入规则

### 5.1 single_shop_rag

必须满足：

```text
shop_id == target_shop_id
facet in allowed_rag_facets 或 facet compatible
support_level in strong / medium
```

直接 drop：

```text
cross_shop
forbidden_facet
low_relevance
weak_support
realtime_facet_from_rag
```

---

### 5.2 recommendation_rag

必须满足：

```text
按 shop_id 分组
每个 shop 至少 1 条 strong/medium evidence
每个 shop 最多注入 2 条 evidence
同一 shop 不能重复占据多个推荐位
```

候选不足时：

```text
不强行推荐；
回答候选不足。
```

---

### 5.3 sibling 补全

sibling 必须经过二次准入：

```text
1. sibling 必须属于同 parent_id。
2. sibling 的 chunk_role / facet 必须与 query facet compatible。
3. 每个 parent 最多补 2-3 条 sibling。
4. forbidden facet sibling 不进入 context。
5. sibling 只能作为辅助证据，不能单独支撑结论。
```

---

## 6. Facet 兼容规则

```python
FACET_COMPATIBILITY = {
    "environment": {"environment", "scene_fit", "crowd", "noise", "seat", "parking"},
    "scene_fit": {"scene_fit", "environment", "crowd", "noise", "service", "price"},
    "coupon": {"coupon", "deal", "package"},
    "open_status": {"open_status", "business_hours"},
    "taste": {"taste", "dish", "product"},
    "service": {"service", "queue"},
    "recommendation": {"scene_fit", "environment", "taste", "price", "location", "category"},
}
```

AnswerContract 必须提供：

```text
allowed_rag_facets
forbidden_rag_facets
realtime_facets
```

---

## 7. 相关度打分

无 rerank 模型时：

```python
final_relevance = (
    0.30 * dense_or_score
    + 0.25 * lexical_overlap
    + 0.25 * facet_match_score
    + 0.20 * metadata_match_score
)
```

分类：

```text
>= 0.70 strong
>= 0.50 medium
>= 0.35 weak
< 0.35 irrelevant
```

有 rerank 模型时：

```python
final_relevance = (
    0.35 * rerank_score
    + 0.20 * dense_or_score
    + 0.20 * lexical_overlap
    + 0.15 * facet_match_score
    + 0.10 * metadata_match_score
)
```

强制规则：

```text
single_shop_rag 中 shop_id != target_shop_id 直接 drop。
facet in forbidden_rag_facets 直接 drop。
coupon / open_status 试图由 RAG 生成实时结论直接 drop 或降级。
```

---

## 8. 低质证据降级

规则：

```text
clean_evidence_count = 0 → RAG_EMPTY_DEGRADED
strong_or_medium_count = 0 → RAG_WEAK_DEGRADED
cross_shop_dropped > 0 → trace 记录
forbidden_facet_dropped > 0 → trace 记录
```

单店降级：

```text
我目前没有检索到这家店与“{facet}”直接相关的可靠评价证据，不能直接判断。你可以补充更具体的问题，例如环境、排队、价格或适合场景。
```

推荐降级：

```text
我目前没有找到足够多同时满足这些条件的商家证据，暂时不强行推荐。你可以放宽条件，例如先只看“附近 + 适合约会”，再筛选有券或营业状态。
```

---

## 9. 需要修改的模块

```text
learning-agent-service/src/learning_agent_service/rag/evidence.py
learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
learning-agent-service/src/learning_agent_service/local_life/answer_contract.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py
```

关键修改：

```text
1. EvidenceGovernance 增加 local_life strict_mode。
2. topic mismatch 不允许 fallback 到 hits[:min_items]。
3. EvidencePack.extra 写入 guardrail 信息。
4. response_builder 不允许引用 dropped evidence。
5. answer_contract 提供 allowed_rag_facets / forbidden_rag_facets / realtime_facets。
```

---

## 10. Trace 字段

```text
rag_mode
latest_turn_message
retrieval_query
raw_retrieved_count
raw_evidence_count
dropped_by_shop_count
dropped_by_facet_count
dropped_by_relevance_count
dropped_by_sibling_count
final_clean_evidence_count
strong_evidence_count
medium_evidence_count
weak_evidence_count
rag_quality_status
rag_dirty_reasons
final_allowed_facets
forbidden_facets
```

---

## 11. Harness 测试

新增：

```text
tests/local_life/rag/test_rag_dirty_data_guardrail.py
tests/local_life/rag/test_rag_context_pruning_chat.py
tests/local_life/rag/test_recommendation_rag_guardrail.py
tests/local_life/rag/test_rag_low_quality_degradation.py
```

---

### 11.1 必测 Case

```text
1. 问 A 店召回 B 店，必须 drop。
2. 问环境召回 coupon evidence，必须 drop。
3. 问约会召回泛评价，只能 weak，不能强答。
4. 全部 weak/irrelevant 时必须降级。
5. sibling 补全不能污染 context。
6. recommendation_rag 必须按 shop_id 分组。
7. final prompt / final_answer 不包含 dropped evidence。
```

---

## 12. 验收标准

Day3 完成后必须满足：

```text
1. single_shop_rag 不允许 cross-shop evidence 进入 LLM。
2. forbidden facet evidence 不允许进入 LLM。
3. sibling 补全必须经过 facet-compatible 过滤。
4. 全部 weak/irrelevant evidence 时必须降级，不允许强答。
5. recommendation_rag 必须按 shop_id 分组。
6. 同一家店不能重复占据多个推荐位。
7. final prompt 不包含 dropped evidence。
8. trace 能显示每类 evidence 被 drop 的数量和原因。
9. 所有关键 E2E 测试从 /internal/v1/chat/stream 触发。
```

---

## 13. 给 Codex 的执行提示词

```text
你是资深 RAG / Context Engineering / Harness Engineering 工程师。

Day1-Day2 已完成，但 Day2.5 未完成。请将 Day2.5 作为新的 Day3 实施：RAG Dirty Data Guardrail 与 Clean Evidence Pack。

必须完成：
1. 新增 LocalLifeRagGuardrail。
2. 新增 EvidenceJudgement。
3. single_shop_rag 必须 drop cross-shop evidence。
4. forbidden facet evidence 必须 drop。
5. low relevance evidence 必须 drop。
6. sibling 补全必须 facet-compatible。
7. clean_evidence_count=0 或 strong_or_medium_count=0 时必须降级。
8. final prompt / final_answer 不允许包含 dropped evidence。
9. 增加 rag_guardrail trace。
10. 增加 dirty data harness。
11. 所有关键测试从 /internal/v1/chat/stream 入口触发。
12. 输出修改文件、测试命令、测试结果、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
