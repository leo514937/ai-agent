# 聊天链路性能优化说明（2026-05-22）

## 1. 背景与瓶颈
本次优化目标是在不回退业务能力前提下，降低用户等待感与真实端到端延迟。  
已确认的主要瓶颈并非死循环，而是链路中多个同步串行 I/O：

- 同步非流式 LLM 分类（intent）
- query rewrite（LLM/规则回写）
- embedding API
- Qdrant dense/sparse/metadata 检索串行执行

## 2. 关键改造

### 2.1 阶段观测与统一日志
为以下阶段统一采集 `elapsed_ms` 并写入结构化日志：

- `load_context`
- `intent_analysis`
- `query_rewrite`
- `embedding`
- `dense_retrieve`
- `sparse_retrieve`
- `metadata_retrieve`
- `rrf_fusion`
- `rerank`
- `compose_answer`

统一日志字段：

- `trace_id`
- `session_id`
- `turn_id`
- `stage`
- `status`
- `elapsed_ms`
- `degrade_to`
- `error`

并在 `final.payload.metrics` 输出关键指标：

- `stages: { stage_name: elapsed_ms }`
- `total_elapsed_ms`
- `embedding_cache_hit`
- `degrade_to`（数组）

### 2.2 SSE 协议细化
后端事件按细粒度阶段发射：

- `ack`
- `load_context_started`
- `load_context_done`
- `intent_analysis_started`
- `intent_analysis_done`
- `retrieval_started`
- `embedding_started`
- `embedding_done`
- `qdrant_search_started`
- `qdrant_search_done`
- `rerank_started`
- `rerank_done`
- `answer_stream_started`
- `delta`
- `final`
- `error`

并支持长阶段 `heartbeat`（默认 800ms 周期）用于“保活感知”。  
正文流主事件统一为 `delta`，兼容旧 `answer_delta`（短期双栈）。

### 2.3 分类阶段优化
- 在 OpenAI 分类前增加 `HeuristicIntentGate`，对问候/感谢/附近推荐/商家详情/比较/路线计划类做本地快速判断。
- 命中高置信规则直接返回 `FastDecision`，绕过 LLM。
- 分类输出精简为：
  - `intent`
  - `needs_rag`
  - `needs_tool`
  - `needs_clarify`
  - `needs_query_rewrite`
  - `confidence`
  - `key_slots`
- 分类超时默认 1200ms，降级标记：`classify_timeout_fallback`。

### 2.4 Query Rewrite 优化
- 仅在指代、省略、上下文依赖、低置信槽位等场景触发 rewrite。
- 完整 query 直接跳过 rewrite。
- rewrite 超时默认 1000ms，回退 raw query。
- raw query embedding warmup 与 rewrite 并发启动。

### 2.5 RAG 并行与容错
- `dense/sparse/metadata` 改为 `asyncio.gather(return_exceptions=True)` 并发。
- 单路失败不阻断整体，降级为其余路径继续融合（RRF）。
- 默认参数收敛：
  - `dense_top_k=10`
  - `sparse_top_k=8`
  - `metadata_top_k=8`
  - `fused_top_k=15`
  - `rerank_top_k=8`
  - `final_evidence_top_n=5`

### 2.6 Embedding 缓存
- Redis 优先缓存。
- key 结构：`embedding_model + embedding_model_version + normalized_query_hash`。
- 命中后跳过 embedding API，记录 `embedding_cache_hit`。

## 3. 降级策略
- 分类超时：`classify_timeout_fallback`
- 分类异常：`classify_error_fallback`
- rewrite 超时：`query_rewrite_timeout_raw_query`
- rewrite 异常：`query_rewrite_error_raw_query`
- 检索单路失败：标记对应 route failed/degraded，整体继续执行

降级标记会进入 `runtime.metrics.degrade_to_list` 并在 `final.payload.metrics.degrade_to` 回传前端。

## 4. 前后端协议联动
- 前端消费新阶段事件并按“最新 stage”更新状态文案。
- 避免长时间停留在旧文案（如“读取上下文”）。
- 兼容旧 `answer_delta` 输入，统一渲染为 `delta`。

## 5. 测试覆盖

### 5.1 后端
- 问候命中 heuristic，不调用 LLM
- 附近推荐命中 heuristic
- LLM 分类超时 fallback
- rewrite 超时 fallback 到 raw query
- dense/sparse/metadata 任一路失败仍可融合返回
- SSE 事件顺序 + heartbeat 行为
- payload contract 与序列化校验

### 5.2 前端
- 事件映射与阶段文案切换
- `final/error`/`clarification_card`/`cancelled` 终态收敛
- 流取消后无异步异常泄漏

## 6. 性能结果（模拟基准）
来源：`learning-agent-service/tests/rag/test_performance_optimization.py`

- 串行检索：`P50=363.2ms`，`P95=364.2ms`
- 并行检索：`P50=130.3ms`，`P95=146.7ms`

结论：并行化显著降低检索阶段延迟，P50/P95 均有明显改善。
