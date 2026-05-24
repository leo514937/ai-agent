# Learning Agent Service

`learning-agent-service` is the standalone Python service for local-life Q&A and general RAG workflows.
This README describes the **current runtime behavior in this folder**, not an aspirational future design.

## Purpose

The service sits between the external chat client and the internal request workflow. It is responsible for:

- accepting chat requests
- running the workflow orchestration layer
- emitting structured SSE events on the public streaming route
- serving local-life question answering and general RAG retrieval flows
- loading and persisting session-oriented conversation context

Public routes are:

- `POST /internal/v1/chat/stream`
- `GET /internal/v1/session/{session_id}/state`
- `POST /internal/v1/feedback/report`
- `GET /internal/v1/feedback/samples`
- `GET /internal/v1/memory/records`
- `GET /internal/v1/memory/records/{memory_id}`
- `GET /internal/v1/memory/candidates`
- `GET /internal/v1/memory/traces`
- `GET /internal/v1/memory/traces/{trace_id}`
- `GET /internal/v1/memory/records/{memory_id}/access-logs`
- `GET /internal/v1/memory/deletion-jobs`
- `POST /internal/v1/memory/candidates/{candidate_id}/confirm`
- `POST /internal/v1/memory/candidates/{candidate_id}/reject`
- `POST /internal/v1/memory/records/{memory_id}/supersede`
- `POST /internal/v1/memory/records/{memory_id}/delete`

## 记忆分层与冲突处理

当前实现保留四层记忆：

- 感知记忆：`InMemorySensoryMemoryBuffer`，仅缓存当前 turn 的原始输入，不持久化。
- 短期记忆：`SessionStore + ShortTermMemoryStore`，保存 session 上下文和消息窗口，默认 Redis，fallback 为进程内存。
- 长期记忆：`MemoryType.SEMANTIC / EPISODIC / PROCEDURAL`，事实源在 PostgreSQL，Qdrant 只做语义索引。
- 实体记忆：`MemoryType.ENTITY` 和结构化偏好事实，默认落 PostgreSQL，不默认进 Qdrant。

### 状态语义

- `active`：当前可用于推荐和回答。
- `inactive`：历史保留，但默认不参与决策。
- `superseded`：被新记忆替代，保留审计用途。
- `deleted`：软删除，保留删除痕迹。

### 冲突规则

- `今天 / 这次 / 最近 / 暂时 / 先` 这类表达默认只写入 session 约束。
- `以后 / 从现在开始 / 我不再 / 我戒掉` 这类明确长期表达会生成新的 active 长期偏好，并让旧记忆变为 `superseded`。
- 默认检索只召回 active 记忆，session 约束优先于 current profile，current profile 优先于历史长期记忆。
- Qdrant 中旧向量会在 supersede 时同步失活或删除，避免继续命中旧偏好。

### 当前画像投影

项目新增了按 `preference_key` 维护的 current profile projection，用于承载当前生效的用户偏好，例如 `food.spicy_preference=no_spicy`。推荐和工具决策优先读这个投影，而不是扫描全部历史记忆。

## 中文架构图（快速阅读）

下面 3 张图对应当前代码里的真实链路，适合直接贴到方案文档里。

### 1. Local-life 主链路

```text
+-------------------+
| 用户 / 对话请求   |
+---------+---------+
          |
          v
+----------------------------------------------------------+
| LocalLifeSubgraph.run_stream                              |
| learning_agent_service/local_life/subgraph.py            |
+-------------------+--------------------------------------+
                    |
                    v
        +-------------------------------+
        | load_context / memory 注入     |
        | session / short / entity /    |
        | mastery / long-term           |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | normalize_query               |
        | query_rewriter.py             |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | extract_slots                 |
        | slot_extractor.py             |
        +---------------+---------------+
                        |
            +-----------+------------+
            | 是否需要澄清信息        |
            +-----------+------------+
                        |
               yes      |      no
                        v
          +-----------------------------+
          | clarification_card          |
          | persist_context             |
          | FINAL                       |
          +-----------------------------+
                        |
                        v
        +-------------------------------+
        | RETRIEVAL_STARTED             |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | TOOL_CALL: search_restaurants |
        +---------------+---------------+
                        |
                        v
        +-----------------------------------------------+
        | JavaBusinessClient                             |
        | adapters/java_business.py                      |
        |  - 门店 / 券 / 博客 / 订单 / 预约              |
        |  - Java 后端不可用 -> catalog fallback         |
        +-------------------+---------------------------+
                            |
                            v
        +-------------------------------+
        | TOOL_RESULT                   |
        +---------------+---------------+
                        |
                        v
        +-----------------------------------------------+
        | build_evidence                                |
        | shop + voucher + blog                         |
        | catalog.py                                    |
        +-------------------+---------------------------+
                            |
                            v
        +-------------------------------+
        | fuse_candidates               |
        | fusion.py                     |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | rank_candidates               |
        | ranker.py                     |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | safety_guard / approval check |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | response_builder              |
        | cards / next_steps / task_chain |
        | response_builder.py           |
        +---------------+---------------+
                        |
                        v
        +-------------------------------+
        | persist_context               |
        | turn state 落盘                |
        | next_steps / task_chain 续写   |
        +---------------+---------------+
                        |
                        v
                   +--------+
                   | FINAL   |
                   +--------+
```

这条链路是打通的，核心步骤已经在代码里接上了：

- `normalize_query -> extract_slots -> search_restaurants`
- `build_evidence -> fuse_candidates -> rank_candidates`
- `safety_guard -> response_builder -> FINAL`

### 2. RAG 链路

```text
+-------------------+
| 用户 / 问知识问题 |
+---------+---------+
          |
          v
+--------------------------------------------------+
| load_context + memory 注入                       |
| session / short-term / entity / mastery / long   |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| understand_turn                                  |
| parse intent / slots / reference                 |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| rag_gate                                         |
|  - 闲聊 / 低信息 -> 直接回复                      |
|  - 明确问题 -> 继续                              |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| rewrite_query                                    |
| rewrite.py                                       |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| hybrid_retrieve                                  |
| retrieval.py                                     |
| dense + sparse + metadata                        |
| qdrant snapshot / bundled fallback               |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| evaluate_evidence                                |
| evidence.py                                      |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| citation_builder                                 |
| citation.py                                      |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| compose_answer                                   |
| grounding / citations / answer 拼装             |
+------------------+-------------------------------+
                   |
                   v
+--------------------------------------------------+
| persist_session / update_mastery                 |
| memory.service / memory.orchestrator             |
+------------------+-------------------------------+
                   |
                   v
               +--------+
               | FINAL   |
               +--------+
```

RAG 的实际流程不是“一个模型直接回答”，而是：

- `query rewrite`
- `hybrid retrieve`
- `evidence governance`
- `citation build`
- `answer composition`

### 3. Java <-> Python 通信链路

```text
+-------------------+
| 浏览器 / 前端     |
+---------+---------+
          |
          v
+--------------------------------------------------+
| Java Spring Boot                                 |
| /ai/chat                                         |
| AiAssistantController                            |
| AiAssistantService                               |
+------------------+-------------------------------+
                   |
                   +--> AiQueryContext / AiBusinessQueryFacadeImpl
                   |     - 上下文归一
                   |     - 路由与业务摘要
                   |
                   +--> [fallback] 本地业务兼容响应
                   |
                   +--> [if ai.remote.enabled == true]
                         AiRemoteClient
                           POST /internal/v1/chat/stream
                           internal token
                           SSE request / response
                                |
                                v
+--------------------------------------------------+
| Python FastAPI                                   |
| app.py -> router -> /internal/v1/chat/stream     |
| -> WorkflowLearningAgentService.run_stream       |
| -> ChatWorkflowService / LocalLifeSubgraph /     |
|    SequentialWorkflowRunner                      |
+------------------+-------------------------------+
                   |
                   v
          SSE 事件返回 Java
          ack / retrieval_started / tool_call /
          tool_result / final / error
                   |
                   v
+--------------------------------------------------+
| AiRemoteStreamParser                             |
| 扁平化 payload, 提取 answer / cards / steps      |
+------------------+-------------------------------+
                   |
                   v
               +-----------+
               | 最终回复   |
               +-----------+
```

这条链路当前**可以打通**，但 Java 侧默认是关闭的：

- `ai.remote.enabled=false`
- 需要同时启动 Python 服务
- 远程地址默认是 `http://127.0.0.1:8000`

### 当前打通情况

- `Local-life`：已打通，并会回传 `cards / next_steps / task_chain`
- `RAG`：已打通
- `Toolcall`：已打通
- `Memory / Session / Feedback`：已打通
- `Java <-> Python`：链路存在，Java 侧已支持扁平化 SSE payload 和结构化结果映射，但默认关闭，需要显式打开远程开关
- Java 业务内网 token 统一使用 `x-internal-token`，Python 侧会优先读取 `LEARNING_AGENT_JAVA_BUSINESS_INTERNAL_TOKEN`，缺省时继承 `LEARNING_AGENT_INTERNAL_API_TOKEN`，避免业务接口出现 401。

### 当前产品态输出

本地生活链路的最终 `final` 事件，已经不是纯文本回答，而是带结构化业务信息的产品态结果：

- `answer_text`：最终回复文本
- `cards`：结构化卡片，前端可以直接渲染
- `shops` / `vouchers`：店铺和优惠券实体结果
- `suggested_replies`：可点击的追问建议
- `next_steps`：下一步可继续执行的动作提示
- `task_chain`：当前任务链路和步骤状态
- `citations` / `retrieval_summary` / `metrics`：可解释性和调试信息

这几个字段会沿着下面这条链路流转：

```text
local_life/subgraph.py
-> response_builder.py 生成 final payload
-> domain/contracts.py 的 FinalPayload 约束字段
-> local_life/subgraph.py 写回 session context
-> Java AiRemoteStreamParser 扁平化 SSE payload
-> Java AiAssistantService 映射到 AiChatResponse
```

因此，当前架构的“可用结果”已经是：

- Python 侧生成结构化产品态输出
- Java 侧消费结构化结果并做远端 / 本地兜底
- 会话上下文保留 `next_steps` 和 `task_chain`，支持下一轮继续追问或继续执行

## Runtime Layout

```text
+--------------------------------------------------------------------------------+
|                         learning-agent-service runtime                         |
+--------------------------------------------------------------------------------+
| API boundary                                                                   |
| - FastAPI router                                                               |
| - HTTP request/response DTOs                                                   |
| - SSE envelope serialization + payload validation                              |
+--------------------------------------------------------------------------------+
| Application layer                                                              |
| - WorkflowLearningAgentService                                                 |
| - Chat / local-life Q&A / general RAG / session / feedback / memory use cases   |
| - Workflow runner                                                              |
+--------------------------------------------------------------------------------+
| Workflow state                                                                 |
| - PersistentSessionContext                                                     |
| - TurnRuntimeState                                                             |
| - GraphRuntimeMeta                                                             |
+--------------------------------------------------------------------------------+
| Capability layer                                                               |
| - RAG: rewrite -> retrieve -> evidence -> citation                             |
| - Memory: persist session -> update mastery -> recommend next                  |
| - Tools: planner -> executor -> normalizer                                     |
+--------------------------------------------------------------------------------+
| Infrastructure                                                                 |
| - Redis / in-memory session store                                              |
| - Postgres / in-memory mastery + outbox                                        |
| - Qdrant snapshot-backed knowledge loading                                     |
| - OpenAI-backed or heuristic turn classification                               |
+--------------------------------------------------------------------------------+
```

## Workflow Overview

The chat workflow is driven by the application service and workflow runner. The current high-level shape is:

```text
load_context
-> understand_turn
-> [clarify] emit_final
-> [need_rag] rag_subgraph
-> [need_tool] tool_subgraph
-> compose_answer
-> persist_session
-> update_mastery
-> emit_final
```

Subgraphs are organized as:

```text
understand_turn:
parse_intent_slots
-> resolve_reference
-> ambiguity_check
-> rewrite_query

rag_subgraph:
hybrid_retrieve
-> evaluate_evidence
-> citation_builder

tool_subgraph:
tool_planner
-> tool_executor
-> tool_result_normalizer
```

## Public SSE Contract

The public streaming contract is defined and validated in:

- `src/learning_agent_service/api/contracts.py`
- `src/learning_agent_service/api/sse.py`

Only these event types are public:

- `ack`
- `retrieval_started`
- `retrieval_result`
- `tool_call`
- `tool_result`
- `clarification_card`
- `final`
- `error`

Dead public events such as `state_update` and `delta` are intentionally not part of the contract.

### SSE lifecycle

Once a request enters a valid SSE session, the lifecycle is:

```text
ack
-> zero or more middle events
-> exactly one terminal event
```

Terminal events are:

- `clarification_card`
- `final`
- `error`

Typical sequences are:

```text
knowledge answer:
ack -> retrieval_started -> retrieval_result -> final

tool-assisted answer:
ack -> retrieval_started -> retrieval_result -> tool_call -> tool_result -> final

clarification:
ack -> clarification_card

in-stream failure:
ack -> error
```

Pre-stream failures are handled differently:

```text
request received
-> service raises before stream is created
-> HTTP error response
```

They do **not** masquerade as partial SSE sessions.

### Envelope shape

Every SSE event uses the same envelope:

```text
event_type
trace_id
session_id
turn_id
timestamp
workflow_version
payload
```

### Clarification payload

`clarification_card.options` is a structured object list, not a string array:

```text
id
label
value
description
```

## HTTP DTO Ownership

The public API boundary keeps one canonical public payload model set for streaming:

- `api/contracts.py` owns HTTP request DTOs and public event validation
- the SSE envelope serializes through one validation map before emitting

Where reuse is practical, the API layer imports shared domain payload models instead of redefining parallel SSE payloads.

## RAG Behavior

Current RAG is a structured pipeline, not a single opaque call:

```text
raw query
-> query rewrite
-> hybrid retrieve
-> evidence governance
-> citation build
```

### Query rewrite

The rewrite stage produces:

- `semantic_query`
- `keyword_query`
- `retrieval_filters`
- `preferred_chunk_types`

It incorporates:

- current query text
- detected intent
- resolved reference/topic
- session topic
- requested output style

### Hybrid Retrieval

The generic retriever still uses three retrieval routes:

- dense-style route
- sparse/BM25-style route
- metadata filter route

Then it runs:

- RRF fusion
- rerank
- evidence selection

The canonical strategy string on the public boundary is:

```text
dense+sparse+metadata->rrf->rerank->evidence
```

### Local Life Parent-Child RAG

The local-life service now uses a real Parent-Child layout in Qdrant.

Collections:

- `local_life_hybrid_chunks` stores the hybrid retrieval collection
- `local_life_parent_child_chunks` stores the parent-child collection

Chunk layout:

- `chunk_level=parent` means merchant / shop-type / platform-rule summary points
- `chunk_level=child` means the evidence points used for retrieval
- parent chunks carry `child_chunk_ids` and `child_roles`
- child chunks carry `parent_id` and `parent_chunk_id`
- hybrid retrieval and parent-child retrieval now have separate Qdrant collections, so a wrong collection name fails fast instead of silently falling back

Payload fields that can be filtered directly:

- `chunk_level`
- `parent_id`
- `parent_chunk_id`
- `parent_title`
- `chunk_role`
- `entity_type`
- `entity_id`
- `source_type`
- `category`
- `subcategory`
- `shop_id`
- `shop_type_id`
- `voucher_id`
- `blog_id`
- `shop_name`
- `city`
- `area`
- `is_active`
- `is_latest`
- `version`

Text strategy:

- dense embedding uses `title + summary + text`
- sparse / keyword text keeps `title + summary + text + shop_name + city + area + subcategory + tags + search keywords + role labels`
- technical fields such as `hash`, UUIDs and point ids are not included in embedding text

Retrieval chain:

```text
child recall
-> parent enrich
-> sibling supplement
-> rerank
```

Optional comparison / recommendation chain:

```text
parent recall
-> child expand
-> rerank
```

Cleanup behavior:

- full rebuild can clear stale local-life points
- scoped seed runs with `shop_ids` / `voucher_ids` / `shop_type_ids` only clean inside the current scope
- this avoids deleting unrelated merchant data during partial refreshes

Seed CLI:

```bash
python -m learning_agent_service.rag.local_life_seed --collection-name local_life_parent_child_chunks
python -m learning_agent_service.rag.local_life_retrieval --query "适合约会的家常菜" --enable-parent-recall
```

Useful tests:

```bash
python -m pytest tests/test_local_life_seed.py tests/rag/test_local_life_parent_child_retrieval.py
python -m pytest tests/test_local_life_pipeline.py tests/test_qdrant_runtime.py tests/rag/test_hybrid_retrieval.py
```

### Metadata-aware retrieval

Metadata filtering is part of the actual pipeline. Current retrieval filters may include fields such as:

- `category`
- `subcategory`
- `difficulty`
- `source_type`
- `chunk_type`
- `version`
- `tags`

### Current runtime mode

The current "real" RAG mode is **Qdrant snapshot-backed**, not per-request online vector querying:

```text
Qdrant available
-> load knowledge snapshot from collection
-> run hybrid retrieval in-process
```

If Qdrant is unavailable or empty, the service falls back to bundled default chunks.

## Memory Behavior

The service currently works with three state layers:

### 1. PersistentSessionContext

Cross-turn session context, including:

- `current_topic`
- `recent_entities`
- `clarification_result`
- `user_preferences`
- `last_retrieval_topic`
- `active_plan_id`
- `response_mode`
- `history_summary`
- `pending_clarification`

### 2. TurnRuntimeState

Per-turn execution state, including:

- intent and confidence
- slots
- reference resolution
- retrieval plan / recall / evidence / citations
- tool plan / raw tool result / normalized tool result
- final answer / recommendation

### 3. GraphRuntimeMeta

Execution metadata, including:

- trace/session/turn identifiers
- workflow version
- metrics
- errors
- terminal event
- emitted events
- memory update summary

### Storage boundaries

The current truth boundaries are:

- Redis: short-term session truth
- Postgres: durable structured facts
- Qdrant: retrieval index, not business truth
- Memory outbox: durable retry queue for Postgres -> Qdrant sync, used to保证最终一致性；supersede 只做软失活，`delete` 只留给显式 forget / cleanup。

### Memory promotion and vectorization

- `MemoryPromotionGate` 先决定一条候选是否能进入长期记忆。
- 默认拒绝进入长期记忆的内容包括：`system_event + session_fact`、澄清模板、`missing_slots`、模糊 query、单次 intent 结果、guest 的低稳定事件、`confidence < 0.7`、`stability < 0.7`、`importance < 0.6`。
- 这些内容如果需要记录，只能落成 `scope=session` 或 `scope=turn` 的短期事件，并设置有限 TTL。
- `MemoryVectorizationGate` 再决定是否写入 Qdrant。
- 只有 `semantic / episodic / procedural` 且 `scope=user/project/global`、`status=active|confirmed`、`is_active=true`、`should_vectorize=true`、未过期、`importance>=0.6`、`stability>=0.6` 的长期记忆才会进入 Qdrant。
- `MemoryType.ENTITY` 默认不进 Qdrant，除非显式允许 profile summary / preference summary。
- guest 用户默认不进入 user-scope 长期记忆，只保留 session 级临时信息。
- procedural memory 会保留标题、场景、触发条件、操作步骤、失败处理、标签等结构化内容，避免只靠短 summary 参与语义召回。

### Qdrant payload

- Qdrant 只保存轻量 payload，用来做检索过滤和回查。
- 完整 memory record 只保存在 PostgreSQL，Qdrant 不嵌套完整 `record`、`content.raw_evidence` 或其他大对象。
- Qdrant payload 仅保留索引字段，例如 `memory_id`、`user_id`、`memory_type`、`scope`、`status`、`should_vectorize`、`summary`、`tags`、`entities`、`confidence`、`importance`、`stability`、`source`、`source_turn_id`、`source_session_id`、`created_at`、`updated_at`、`effective_from`、`effective_to`、`valid_until`、`schema_version`。
- `memory_id` 是业务主键，`vector_id` 统一由 `uuid5(memory_id)` 推导，Qdrant point id 只保留这一套语义。

### Memory collection rebuild

- Durable memory collection 的 vector size 现在固定来自 settings，默认是 4096。
- memory embedding 也来自 settings：`embedding.memory_model=qwen-embedding-8b`，`embedding.memory_provider=openai`。
- 64 维只用于测试里的 FakeEmbedding 或显式构造的测试夹具，生产 durable backend 不允许默认回退到 64。
- Qdrant collection 不能原地修改维度，旧的 64 维 collection 必须删除后重建。
- 删除 memory collection 只会删除 Qdrant 索引，不会删除 PostgreSQL 里的 memory records，Postgres 仍然是 source of truth。
- 重建时只会重新索引 PostgreSQL 中满足 gate 的 active long-term memory：`semantic / episodic / procedural`，`status=active|confirmed`，`is_active=true`，`should_vectorize=true`，`scope=user/project/global`，未过期，且通过 `MemoryVectorizationGate`。

重建命令示例：

```bash
python -m learning_agent_service.memory.reindex_qdrant \
  --drop-existing \
  --expected-old-vector-size 64 \
  --confirm-nonstandard-existing-collection \
  --batch-size 64
```

如果已经在 settings 里配置了 `memory_collection / memory_vector_size / memory_vector_name / memory_distance / embedding.memory_model`，也可以只保留 `--drop-existing`、`--expected-old-vector-size 64` 和必要的确认开关，其余参数走配置。

推荐的显式命令是：

```bash
python -m learning_agent_service.memory.reindex_qdrant \
  --drop-existing \
  --expected-old-vector-size 64 \
  --confirm-nonstandard-existing-collection \
  --collection-name agent_memory_chunks \
  --vector-name embedding \
  --vector-size 4096 \
  --batch-size 64
```

如果只是处理历史 64 维 collection，且确认旧集合就是 64 维，可以省略 `--confirm-nonstandard-existing-collection`。

### 验证方式

- `memory_vector_size` 必须和 embedding 模型输出一致，写入前会做维度校验。
- 如果 collection 已存在且维度是 64，而 settings 期望 4096，启动或写入前会报 `Memory Qdrant collection shape mismatch`。
- 可以用重建命令完成旧索引删除、4096 维新建和 Postgres 重新索引，然后再用 Qdrant collection inspect / client API 验证新的 vector size。

### Cleanup and verification

- 旧污染数据可以通过 reindex 逻辑自动跳过，或者在 Qdrant 中按 `source=system_event`、`fact_type=session_fact`、`scope=session|turn`、`should_vectorize=false`、`importance<0.6`、`stability<0.6`、`summary` 含澄清模板等条件清理或失活。
- 默认检索只回 `is_active=true`、`status=active|confirmed`、`should_vectorize=true`、未过期、`scope` 不为 `turn/session` 的记忆。
- 如果 collection 维度不匹配，rebuild 命令会拒绝直接复用，避免把 64 维旧索引继续带到生产环境。

### Memory outbox and sync

- `memory_outbox` 和 `outbox_event` 分离，前者专门承载记忆向量同步事件。
- `memory_records` / `user_profile_preference` 的写入先落 Postgres，再通过 outbox 异步同步到 Qdrant。
- Qdrant 旧点在 `supersede` 时只做 soft deactivate，不会物理删除；只有显式删除接口才会真正删除 point。
- Qdrant 检索默认过滤 `status=active|confirmed`、`is_active=true`、`should_vectorize=true`、长期 scope，避免历史 superseded 或 session 事件继续影响召回。

## Tool Calling

The shared runtime tool stack is:

```text
ToolPlanner -> ToolExecutor -> ToolResultNormalizer
```

This same stack is used by:

- the chat workflow
- the local-life question answering path
- the general RAG retrieval path

Current runtime keeps the tool stack narrow and aligned with the active workflows:

- `ToolPlanner -> ToolExecutor -> ToolResultNormalizer`
- local-life business tool calls go through the same planner/executor/normalizer pipeline
- general RAG answers rely on retrieval, evidence selection, citation building, and answer composition rather than legacy learning-plan tools

## Runtime Profiles and Dual Mode

Dependency assembly lives in `src/learning_agent_service/application/dependencies.py`.

The runtime advertises a profile such as:

- `full`
- `partial`
- `dev_fallback`

And exposes adapter-level modes like:

- `real`
- `fallback`
- `noop`
- `unavailable`

At startup, the app stores infrastructure status on application state. The status includes:

```text
runtime_profile
dependency_status
```

## Testing

The current test suite emphasizes the real public contract:

- public SSE event enum only contains supported events
- chat stream route serializes canonical SSE events
- pre-stream failures return HTTP errors instead of partial SSE streams
- clarification uses structured options
- tool tests use the canonical runtime planner/executor/normalizer DTO flow
- runtime smoke tests verify the actual service starts with `ack` and ends with one supported terminal event
- bootstrap tests verify dependency status and runtime profile exposure

Run the suite with:

```bash
python -m unittest discover -s learning-agent-service/tests -p "test_*.py"
```

## Current Integration Assumptions

This folder is aligned to the public API/SSE boundary, but some deeper runtime behavior still depends on other modules evolving independently. In particular:

- the public contract is strict even if internal workflow paths degrade to `ack -> error`
- actual runtime smoke tests avoid assuming every internal branch is healthy in every workspace state
- richer event-order coverage is exercised through deterministic service stubs at the API boundary

## Local Run

```bash
cd learning-agent-service
pip install -e .[dev]
cp .env.example .env
uvicorn learning_agent_service.app:app --reload --port 9000
```
