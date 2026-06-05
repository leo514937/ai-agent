# 兜底原因分析报告

## 概要结论

**缺少用户位置信息（`current_city=None`）是一个因素，但不是主要原因。**

兜底的根本原因是**多个环节级联失败**，最终导致检索结果为空。以下按影响程度排序：

---

## 原因分析

### 🔴 主因1：检索器用的是 Heuristic（关键词启发式匹配），不是真正的向量相似度

**代码证据**：
- `HeuristicDenseRetriever`（[retrieval.py:L355-420](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/retrieval.py#L355-L420)）
  - `_dense_score` 用的是 **Jaccard** 分词交集，不是 embedding 向量余弦相似度
  - 所以 `embedding_latency_ms: 0.0`，根本没有调用 embedding 服务

**日志证据（Query 1，L45）**：
```json
{
  "dense": {"embedding_latency_ms": 0.0, "qdrant_search_latency_ms": 0.0, "hit_count": 0},
  "sparse": {"embedding_latency_ms": 0.0, "qdrant_search_latency_ms": 0.0, "hit_count": 0},
  "metadata": {"embedding_latency_ms": 0.0, "qdrant_search_latency_ms": 0.0, "hit_count": 0}
}
```

**影响**：对于**语义泛化的查询**（如"附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"），Jaccard 分词交集几乎不可能匹配到任何知识 chunk，因为用户查询中没有具体的店铺名称关键词。

> 虽然 `QdrantOnlineDenseRetriever`（真正的向量检索器）已经在代码中实现（L989-1090），且 `enable_online_dense_retrieval=True`，但日志中**没有** `qdrant_dense_timing` 日志输出，说明它**没有被成功启用**（可能因为 OpenAI embedding adapter 或 Qdrant 向量名配置不匹配导致构造失败，回退到了 Heuristic）。

---

### 🔴 主因2：In-memory Chunks 不包含本地生活/商铺数据

**代码证据**：`DEFAULT_KNOWLEDGE_CHUNKS` ([defaults.py:L163-224](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/defaults.py#L163-L224)) 只包含：
- `rag-concept`：RAG 概念
- `spring-aop-compare`：Spring AOP
- `java-threadpool-concept`：Java 线程池
- `react-cot-compare`：ReAct vs CoT
- `family-dinner-restaurant`：一条"北京适合带爸妈的餐厅"mock 数据

这些与"海底捞""约会餐厅""有券"等本地生活查询**完全不匹配**。

虽然启动时从 `local_life_hybrid_chunks` 集合 scroll 了数据（日志 L5-7），但 BM25 和 Jaccard 对泛化查询的匹配能力极弱。

---

### 🟡 次因3：LLM Query Rewrite 失败（JSON 解析错误）

**日志证据（L44）**：
```
rag_llm_rewrite_failed
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

当三路检索（dense/sparse/metadata）全部返回 0 hits 后，系统会尝试 LLM Rewrite 重写查询再试一次，但这次 LLM 返回了空内容（非 JSON），导致 rewrite 失败，进一步加剧了兜底。

---

### 🟡 次因4：LLM Slot Extraction 错误

**日志证据**：对于 Query 2（"海底捞水晶城店有券吗，现在营业吗"），LLM 把 `shop_name` 抽取为 `"现在"` 而不是 `"海底捞水晶城店"`：
```json
"slots": {"scene": "date", "shop_name": "现在"}
```

这导致后续 Tool 调用传了错误的店名给后端 API。

---

### 🟠 辅因5：缺少用户位置信息（current_city=None）

**日志证据（L67）**：
```
memory_persist session=sess-mpvzrqeb-ytklhh fields=... current_city=None
```

**代码证据**：`_build_query_filter` ([local_life_retrieval.py:L713-760](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py#L713-L760)) 会将 `city` 作为 `Must` 条件：
```python
if city:
    must_conditions.append(
        FieldCondition(key="city", match=MatchValue(value=city))
    )
```

**实际影响**：
- 当 `city=None` 时，这个 `Must` 条件**不会被添加**，相当于 city filter 被跳过了
- 这意味着 city=None 实际上**不会过滤掉任何数据**，反而让 filter 更宽松
- 所以 **缺少位置信息不是导致 0 hits 的直接原因**

但 Route Review 正确识别了 `location` 是必选 facet（`missing_policy: "ask_clarification"`），理论上应该向用户追问位置，但系统没有执行追问，而是继续走了 RAG 检索流程。

---

### 🟠 辅因6：`local_life_parent_child_chunks` 集合数据是 mock 数据

**发现**：`local_life_parent_child_chunks` 集合只有 51 个点，且包含的是模拟数据而非真实商铺数据。但这个集合**目前不在主检索链路中**（主链路用的是 `HybridRAGOrchestrator` 的 in-memory retriever），所以暂不影响。

---

## 失败链路图

```
用户查询: "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
    │
    ▼
Intent Analysis → domain=local_life, intent=merchant_status
    │
    ▼
Route Review → required_facets: location(missing!), 但没有追问
    │
    ▼
RAG Retrieval (HybridRetrieverService, 3路检索)
    ├── Dense (Jaccard): 0 hits ← Jaccard 无法语义匹配泛化查询
    ├── Sparse (BM25):   0 hits ← in-memory chunks 没有商铺数据
    └── Metadata:        0 hits ← 无 filter 匹配
    │
    ▼
LLM Rewrite 尝试 → JSON 解析失败
    │
    ▼
最终: fallback_reason="no_hits" → 兜底回答
```

---

## 修复建议（按优先级）

| 优先级 | 问题 | 修复方案 |
|--------|------|----------|
| P0 | 向量检索未启用 | 排查 `QdrantOnlineDenseRetriever` 构造失败的原因，确保 OpenAI embedding adapter 正常工作 |
| P0 | In-memory chunks 缺少商铺数据 | 确保 `local_life_hybrid_chunks` 的真实商铺数据被正确加载到内存中 |
| P1 | LLM Rewrite 返回空内容 | 增加 Rewrite prompt 的鲁棒性，或添加 fallback 策略 |
| P1 | 缺少 location 时未追问用户 | 在 route_gate 阶段严格执行 `missing_policy: ask_clarification` |
| P2 | Slot extraction 错误 | 优化 slot extraction prompt，避免把"现在"等常见词误抽取为 shop_name |
| P2 | parent_child_chunks 数据为 mock | 同步真实商铺数据到 `local_life_parent_child_chunks` |
