# Day5：RAG 父子检索、混合检索与 RAG Eval

> 目标：在 Day3 Clean Evidence Guardrail 基础上，升级父子检索、BM25、metadata recall、RRF、rerank 与 RAG Eval。  
> 前置：Day3 已完成脏数据准入；Day4 已明确实时信息由 Tool 负责。  
> 产出：单店不串店，推荐能分组，召回可评测，父子检索不污染上下文。

---

## 1. Day5 和 Day3 的关系

Day3 已经解决：

```text
哪些 evidence 能进入 LLM
哪些 evidence 要被 drop
低质证据如何降级
```

Day5 解决：

```text
如何更好地召回 evidence
如何设计 Qdrant payload
如何做父子检索
如何做 dense + BM25 + metadata + RRF
如何用指标评测 RAG
```

---

## 2. RAG 模式划分

### 2.1 single_shop_rag

```text
必须 filter shop_id = target_shop_id
只返回目标店证据
latest_turn_message 决定 query rewrite
history_summary 只能弱辅助
```

---

### 2.2 recommendation_rag

```text
不能强 filter session.current_shop
必须广谱召回
必须按 shop_id 聚合
每个 shop_id 形成一个候选
最新一轮约束优先于历史偏好
上一轮是单店时必须清除 single_shop anchor
```

---

## 3. Qdrant Payload 设计

```text
doc_id
chunk_id
chunk_level: parent | child
parent_id
parent_chunk_id
child_chunk_ids
shop_id
shop_name
brand_name
category
city
district
business_area
source_type
chunk_role
facet
scene_tags
price_level
suitable_for
not_suitable_for
evidence_time
freshness_level
quality_score
```

关键字段：

```text
shop_id
chunk_level
parent_chunk_id
facet
scene_tags
source_type
chunk_role
business_area
freshness_level
```

---

## 4. 父子检索流程

```text
latest_turn_message
  ↓
query rewrite
  ↓
retrieval filters from AnswerContract / target_shop / recommendation_scope
  ↓
child dense recall
  ↓
child BM25 sparse recall
  ↓
metadata recall
  ↓
RRF fusion
  ↓
按 parent_id 聚合
  ↓
load parent
  ↓
load sibling
  ↓
Day3 LocalLifeRagGuardrail
  ↓
rerank
  ↓
Clean Evidence Pack
```

---

## 5. 混合检索

### Dense Recall

适合：

```text
语义相似
适合约会
适合带长辈
环境安静
服务稳定
```

### BM25 Sparse Recall

适合：

```text
店名
商圈
菜品
标签
券名
具体短语
```

### Metadata Recall

适合：

```text
category = 火锅
business_area = 水晶城
scene_tags contains 约会
shop_id = xxx
```

### Fusion

```text
dense + BM25 + metadata
  ↓
RRF
  ↓
rerank
```

---

## 6. sibling 补全规则

Day5 中 sibling 补全要和 Day3 Guardrail 联动：

```text
1. sibling 必须同 parent_id。
2. sibling 必须 facet-compatible。
3. 每个 parent 最多补 2-3 条。
4. forbidden facet sibling 不进入 context。
5. sibling 只能辅助，不能单独支撑结论。
```

---

## 7. Evidence Pack

```python
class RagEvidencePack:
    rag_mode: str
    target_shop_id: str | None
    evidence_items: list[Evidence]
    grouped_by_shop: dict[str, list[Evidence]]
    dropped_cross_shop_evidence: list[Evidence]
    empty_reason: str | None
```

Evidence 不等于原始 Chunk：

```python
class Evidence:
    evidence_id: str
    shop_id: str
    shop_name: str
    facet: str
    source_type: str
    chunk_role: str
    text: str
    score: float
    freshness_level: str
    support_level: str
```

---

## 8. RAG Eval 数据集

新增：

```text
eval/local_life/rag_eval_cases.jsonl
eval/local_life/rag_dirty_cases.jsonl
```

样例：

```json
{
  "case_id": "single_shop_scene_fit_001",
  "query": "海底捞水晶城店适合约会吗？",
  "expected_route": "rag",
  "expected_rag_mode": "single_shop_rag",
  "expected_shop_id": "shop_haidilao_shuijingcheng",
  "expected_facets": ["scene_fit", "environment"],
  "forbidden_shop_ids": ["shop_banu_xxx"],
  "expected_keywords": ["约会", "环境", "氛围"]
}
```

多轮 latest priority：

```json
{
  "case_id": "recommendation_after_single_shop_anchor_001",
  "turns": [
    "海底捞水晶城店怎么样？",
    "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
  ],
  "expected_route": "recommendation",
  "expected_rag_mode": "recommendation_rag",
  "forbidden_single_shop_anchor": true
}
```

---

## 9. 指标

```text
recall@5
recall@10
mrr@10
ndcg@10
empty_rate
cross_shop_rate
facet_hit_rate
recommendation_diversity
dirty_context_rate
forbidden_facet_rate
weak_evidence_force_answer_rate
final_prompt_dirty_rate
```

---

## 10. 需要修改的模块

```text
learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py
learning-agent-service/src/learning_agent_service/rag/evidence.py
learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py
```

关键修改：

```text
1. retrieve_local_life_evidence 增加 allowed_facets / forbidden_facets 参数。
2. filters 支持 shop_id / facet / scene_tags / business_area。
3. 稀疏检索从 token overlap 替换或封装为 BM25 主路径。
4. dense + BM25 + metadata + RRF + rerank。
5. recommendation_rag 按 shop_id 聚合。
6. RAG eval CLI 输出指标报告。
```

---

## 11. Harness 测试

新增：

```text
tests/local_life/rag/test_single_shop_rag_no_cross_shop.py
tests/local_life/rag/test_recommendation_rag_group_by_shop.py
tests/local_life/rag/test_hybrid_retrieval_fusion.py
tests/local_life/rag/test_rag_evidence_pack.py
tests/local_life/rag/test_rag_eval_metrics.py
tests/local_life/rag/test_rag_latest_turn_priority.py
```

---

## 12. 验收标准

Day5 完成后必须满足：

```text
1. single_shop_rag 不串店。
2. recommendation_rag 按 shop_id 分组。
3. Dense + BM25 + metadata 能融合。
4. Evidence Pack 可解释。
5. RAG Eval 能输出指标。
6. sibling 补全不能污染 context。
7. 最新一轮消息必须优先决定检索 query。
8. 推荐链路不得把单店上下文强制收缩成单店 RAG。
```

---

## 13. 给 Codex 的执行提示词

```text
你是资深 RAG / Qdrant / Context Engineering / Harness Engineering 工程师。

Day1-Day4 已完成。请执行 Day5：RAG 父子检索、混合检索与 RAG Eval。

必须完成：
1. 排查当前 Qdrant payload、retriever、single_shop_rag、recommendation_rag。
2. 设计并实现标准 payload 字段。
3. 单店模式必须强 filter target_shop_id。
4. 推荐模式必须按 shop_id 聚合。
5. 实现 dense + BM25 + metadata + RRF + rerank。
6. 确保 latest_turn_message 是 query rewrite 的第一输入。
7. sibling 补全必须经过 Day3 Guardrail。
8. 新增 RAG eval 和指标脚本。
9. 所有关键测试从 /internal/v1/chat/stream 入口触发。
10. 输出是否需要重建 Qdrant collection、如何灌库、如何验证。

不要只写计划，必须完成代码修改、测试和验证。
```
