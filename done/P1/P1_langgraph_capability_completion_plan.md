# LangGraph 能力补全改造方案

> 适用仓库：`https://github.com/leo514937/ai-agent.git`  
> 适用模块：`learning-agent-service`  
> 目标：把当前“基础 LangGraph 编排”升级为“可控、可回放、可测试、可扩展”的本地生活 Agent 工作流。

---

## 0. 当前现状判断

当前项目已经不是纯手写 workflow，已经接入了 LangGraph 的基础能力：

```text
已用到：
- StateGraph
- add_node
- add_edge
- add_conditional_edges
- END
- graph.compile(checkpointer=checkpointer)
- graph.invoke(...)
- configurable.thread_id
```

但当前使用方式仍偏基础：

```text
主要问题：
1. 当前是 StateGraph(dict)，状态结构不够强。
2. route_gate / route_decider 主要返回字符串分支，不是 Command(update + goto) 硬路由。
3. rag_subgraph / tool_subgraph / recommendation_subgraph 更像普通 Python 函数节点，不是真正 compiled subgraph。
4. checkpointer 目前更像可传入接口 + fallback，不是完整生产级 checkpoint / replay / time travel。
5. 当前 SSE 更像手写事件，不是完整基于 LangGraph stream events 的适配层。
6. 没有系统使用 Send API、interrupt/resume、Reducer、RetryPolicy、CachePolicy、Time Travel、Runtime Context 等能力。
```

当前主链路大致是：

```text
load_context
  ↓
understand_turn
  ↓
route_gate
  ├─ compose_answer
  ├─ tool_subgraph
  ├─ rag_subgraph
  ├─ recommendation_subgraph
  └─ plan_execute_subgraph
  ↓
compose_answer
  ↓
persist_session
  ↓
emit_final
```

这说明当前项目已经具备 LangGraph 基础图结构，但还没有充分利用 LangGraph 在生产级 Agent 编排中的关键能力。

---

## 1. 总体改造目标

本次改造不是为了“堆 LangGraph 功能”，而是解决当前本地生活 Agent 的核心问题：

```text
当前核心问题：
1. 路由不够硬：用户只问券，后续可能又回答环境。
2. 状态不可回放：错路由、串店、越权回答难以定位。
3. RAG / Tool / Compose 边界不硬：后续节点可能不遵守路由结果。
4. 多轮澄清不稳定：用户补充信息后可能重新开始，而不是从中断点继续。
5. RAG 证据质量不稳定：不相关召回、空召回、过度拒答难以治理。
6. 子图边界不清：主图承担过多细节，RAG / Tool 难以单独测试。
7. 并行任务能力不足：多商家比较、附近推荐、多维度分析还没有动态 map-reduce 能力。
```

改造后的目标状态：

```text
目标状态：
1. route_decision 成为唯一事实源。
2. GraphState 强类型化，关键字段不可随意覆盖。
3. RAG / Tool / Compose 必须遵守 routing_contract。
4. 每一轮图执行可 checkpoint、可 replay、可 time travel。
5. 多门店歧义、缺位置等场景支持 interrupt/resume。
6. RAG 和 Tool 拆成真正 compiled subgraph，可独立测试。
7. 多商家推荐/比较支持 Send API + map-reduce。
8. SSE 事件逐步接入 LangGraph 原生 streaming。
9. 节点失败有 retry / timeout / degrade。
10. 架构可视化、可验收、可回归测试。
```

---

## 2. 优先级总览

| 优先级 | 能力 | 目标 |
|---|---|---|
| P0 | Typed GraphState | 替代 `StateGraph(dict)`，让状态结构可控 |
| P0 | Command API | 让路由节点同时更新状态并硬跳转 |
| P0 | 路由合同传递 | 让 RAG / Tool / Compose 不越权 |
| P0 | Checkpointer 真实启用 | 支持多轮状态保存、debug、恢复 |
| P0 | Agentic RAG 证据评估 | 解决不相关召回、空召回、过度拒答 |
| P1 | Time Travel / replay | 错路由、串店、越权回答可复现 |
| P1 | interrupt / resume | 多门店歧义、缺位置、确认类操作可暂停恢复 |
| P1 | RetryPolicy / timeout / degrade | 提升 Qdrant、LLM、ToolCall 稳定性 |
| P1 | 真正 compiled subgraph | RAG / Tool / Recommendation 独立成图 |
| P1 | Runtime Context | 把配置和依赖从 state 中剥离 |
| P1 | Reducer / Annotated state | 为并行分支和 Send 做状态合并准备 |
| P1 | Recursion Limit / Loop Guard | 防止工具循环、重写循环失控 |
| P1 | Graph Visualization | 每次改造可视化验收 |
| P2 | Send API + map-reduce | 多商家推荐、多商家比较、多维度分析 |
| P2 | 原生 streaming + SSE adapter | 让前端事件和图执行事件对齐 |
| P2 | Parallel branches + defer | dense/sparse/metadata 固定并行召回 |
| P2 | Max Concurrency | 控制并行任务压力 |
| P2 | CachePolicy | 缓存昂贵但可复用节点 |
| P2 | Long-term Store / Memory | 可选，和现有 Redis/Postgres 记忆边界对齐 |
| P2 | Functional API | 可选，用于长任务/离线任务渐进式改造 |

---

# 第一阶段：P0 正确性改造

---

## 3. P0-1：Typed GraphState，替代 `StateGraph(dict)`

### 3.1 是什么

当前主图使用：

```python
graph = StateGraph(dict)
```

这会导致 state 是一个大 dict，任何节点都可以随意写字段，容易出现：

```text
- 字段名不一致
- 节点覆盖其他节点结果
- route_decision 被后续节点改写
- RAG / Tool / Compose 读错字段
- 测试很难判断 state 是否完整
```

应改为强类型状态：

```python
from typing import TypedDict, NotRequired, Annotated
import operator

class GraphState(TypedDict, total=False):
    raw_query: str
    session_id: str
    user_id: str | None

    runtime: object
    intent: object
    target_shop: object | None
    routing_decision: object | None
    routing_contract: object | None

    evidence_pack: object | None
    tool_result: object | None
    answer_plan: object | None
    final_answer: str | None

    # 需要 append 的字段，用 reducer
    sse_events: Annotated[list[object], operator.add]
    errors: Annotated[list[object], operator.add]
    evidence_items: Annotated[list[object], operator.add]
    tool_results: Annotated[list[object], operator.add]
    shop_analyses: Annotated[list[object], operator.add]
```

然后：

```python
graph = StateGraph(GraphState)
```

### 3.2 作用

```text
1. 明确每个节点能读写什么。
2. 让 route_decision、routing_contract、target_shop 成为明确状态字段。
3. 避免后续节点随意覆盖关键状态。
4. 为 reducer、Send API、并行分支做基础准备。
```

### 3.3 改造文件建议

```text
learning-agent-service/src/learning_agent_service/application/workflow/state.py
learning-agent-service/src/learning_agent_service/application/workflow/builder.py
learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py
```

新增：

```text
workflow/state.py
  - GraphInputState
  - GraphOutputState
  - GraphState
  - RoutingContract
  - EvidencePackState
  - ToolState
  - GraphRuntimeContext
```

### 3.4 验收标准

```text
1. builder.py 不再使用 StateGraph(dict)。
2. GraphState 中显式包含 routing_decision、routing_contract、target_shop、evidence_pack、tool_result、final_answer。
3. sse_events、errors、evidence_items、tool_results、shop_analyses 使用 reducer。
4. 所有节点返回 Partial[GraphState]，不再返回随意 dict。
5. pytest 能覆盖 GraphState 基础字段存在性。
```

---

## 4. P0-2：Command API，让路由变成硬跳转

### 4.1 是什么

当前路由更像：

```text
route_gate 更新一部分 state
route_decider 返回 "rag" / "tool" / "direct"
add_conditional_edges 根据字符串跳转
```

这容易造成：

```text
路由结果只是建议，不是强约束。
后续节点可能二次改路由。
```

应改为 Command：

```python
from langgraph.types import Command
from typing import Literal

def route_decision_node(state: GraphState) -> Command[
    Literal[
        "direct_safe_reply",
        "clarify",
        "rag_graph",
        "tool_graph",
        "rag_plus_tool_graph",
        "recommendation_graph",
        "prepare_candidates",
    ]
]:
    decision = build_routing_decision(state)
    contract = build_routing_contract(state, decision)

    if contract.input_invalid:
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="direct_safe_reply",
        )

    if contract.need_clarify:
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="clarify",
        )

    if contract.required_action == "tool_call":
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="tool_graph",
        )

    if contract.required_action == "rag_retrieval":
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="rag_graph",
        )

    if contract.required_action == "rag_plus_tool":
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="rag_plus_tool_graph",
        )

    if contract.required_action == "recommendation":
        return Command(
            update={
                "routing_decision": decision,
                "routing_contract": contract,
            },
            goto="recommendation_graph",
        )

    return Command(
        update={
            "routing_decision": decision,
            "routing_contract": contract,
        },
        goto="direct_safe_reply",
    )
```

### 4.2 作用

```text
1. 路由节点同时完成 state 更新和 goto。
2. route_decision 成为唯一事实源。
3. 后续节点必须基于 routing_contract 执行。
4. 无效输入不会误入 RAG。
5. 单一意图不会误入 rag_plus_tool。
```

### 4.3 解决的典型问题

```text
用户：有券吗？
旧问题：回答券 + 自动补环境。
新结果：goto tool_graph，compose 只允许回答 coupon。

用户：，
旧问题：误触发检索。
新结果：goto direct_safe_reply。

用户：这家环境怎么样？
旧问题：可能查券。
新结果：goto rag_graph，forbidden_facets 包含 coupon。
```

### 4.4 改造文件建议

```text
workflow/builder.py
workflow/subgraphs.py
workflow/routing.py
application/routing_signals.py
```

### 4.5 验收标准

```text
1. route_decider 字符串路由逐步退场，核心路由节点返回 Command。
2. route_decision_node 同时写入 routing_decision 和 routing_contract。
3. 单测覆盖 coupon-only、review-only、rag_plus_tool、invalid_input、nearby_recommend。
4. 用户输入“，”不进入 RAG / Tool。
5. 用户只问“有券吗”不进入 RAG。
```

---

## 5. P0-3：路由合同传递到 RAG / Tool / Compose

### 5.1 是什么

路由合同不是 LangGraph 官方 API，而是本项目最关键的业务约束。

它要求 route_decision 输出一份 contract，后续所有模块必须遵守：

```python
class RoutingContract(TypedDict):
    required_action: str
    required_facets: list[str]
    optional_facets: list[str]
    forbidden_facets: list[str]

    target_shop_id: str | None
    candidate_shop_ids: list[str]
    single_shop_mode: bool
    recommendation_mode: bool

    rag_allowed: bool
    tool_allowed: bool
    compose_allowed_facets: list[str]

    input_invalid: bool
    need_clarify: bool
    clarify_reason: str | None
```

### 5.2 传递规则

```text
route_decision_node
  ↓
routing_contract
  ↓
RAG：只检索 required_facets 相关内容
Tool：只调用 allowed tools
Compose：只回答 compose_allowed_facets
```

### 5.3 RAG 约束

RAG 节点必须遵守：

```text
1. rag_allowed=False 时不得执行 RAG。
2. required_facets 只包含 coupon 时，RAG 不得检索环境/口味/服务。
3. target_shop_id 存在时，检索必须加 shop_id filter。
4. candidate_shop_ids 存在时，检索不得越过候选范围。
5. forbidden_facets 命中的证据不得进入 evidence_pack。
```

### 5.4 Tool 约束

Tool 节点必须遵守：

```text
1. tool_allowed=False 时不得调用工具。
2. 只调用 required_action 对应工具。
3. coupon_query 只查券。
4. business_status_query 只查营业状态。
5. tool 失败时返回 unavailable，不得编造。
```

### 5.5 Compose 约束

Compose 节点必须遵守：

```text
1. 只能回答 compose_allowed_facets。
2. forbidden_facets 不得出现在最终回答。
3. 没有证据的维度不得补充。
4. tool_result unavailable 时必须明确“无法确认”，不得说“没有”。
5. target_shop_id 与证据 shop_id 不一致时不得使用该证据。
```

### 5.6 验收标准

```text
1. 用户只问“有券吗”：最终回答只包含券信息。
2. 用户只问“环境怎么样”：最终回答只包含环境/评价相关内容，不查券。
3. 用户问“有券吗，环境怎么样”：才允许 rag_plus_tool。
4. 所有 evidence_item 都带 facet、shop_id、source_type。
5. Compose 前有 contract validation。
6. forbidden_facets 命中时测试失败。
```

---

## 6. P0-4：Checkpointer 真实启用

### 6.1 是什么

Checkpointer 用于保存 LangGraph 每一步状态，支持：

```text
- 多轮短期记忆
- 状态恢复
- 错误恢复
- interrupt/resume
- time travel
- replay
```

当前项目虽然已经有 `compile(checkpointer=checkpointer)` 和 `thread_id`，但仍需确保生产级 checkpointer 真实初始化并注入。

### 6.2 推荐实现

开发环境：

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
```

本地持久化：

```python
# 视当前 langgraph 版本选择 sqlite / postgres checkpointer
# 注意：不同版本包路径可能变化，Codex 需要以当前项目依赖版本为准。
```

生产环境：

```text
优先选择 Postgres checkpointer
原因：
- 和现有 Postgres 基础设施一致
- 支持真实多进程/多实例持久化
- 方便后续 replay / audit
```

### 6.3 改造要求

```text
1. dependencies.py 中提供明确 get_checkpointer()。
2. create_workflow_runner(..., checkpointer=checkpointer) 必须传入真实 checkpointer。
3. 每次 graph.invoke / graph.stream 必须带 configurable.thread_id。
4. 禁止仅依赖 _CHECKPOINT_FALLBACKS 作为正式 checkpoint。
5. 保留 fallback 仅用于测试或 LangGraph 不可用场景。
```

### 6.4 验收标准

```text
1. 同一 session_id 多轮调用可以读取上一轮 state。
2. graph.get_state(config) 能拿到最近状态。
3. 失败后可以从最近 checkpoint 定位状态。
4. interrupt/resume 测试可以通过。
5. 没有 checkpointer 时，human-in-the-loop 功能不启用，并明确降级。
```

---

## 7. P0-5：Agentic RAG 证据评估子链路

### 7.1 是什么

当前 RAG 不应该只是：

```text
query → retrieve → 拼 context → answer
```

而应升级成：

```text
query_rewrite
  ↓
retrieve
  ↓
grade_evidence
  ├─ sufficient → evidence_pack
  ├─ partially_sufficient → evidence_pack + limitation
  └─ insufficient → rewrite / degrade / clarify
```

### 7.2 为什么急

你当前本地生活项目已出现或可能出现：

```text
1. RAG 召回不相关。
2. 空召回直接拒答。
3. 召回到别的商家。
4. 用户问券，RAG 补环境。
5. 用户问 A 店，证据来自 B 店。
```

### 7.3 推荐 RAG 子图

```text
rag_graph:
  build_retrieval_plan
    ↓
  query_rewrite
    ↓
  dense_retrieve
  sparse_retrieve
  metadata_retrieve
    ↓
  fusion
    ↓
  rerank
    ↓
  evidence_filter_by_contract
    ↓
  grade_evidence
    ├─ sufficient → build_evidence_pack
    ├─ insufficient_rewriteable → rewrite_once
    └─ insufficient_final → degraded_evidence_pack
```

### 7.4 验收标准

```text
1. evidence_pack 必须包含 evidence_quality。
2. evidence_quality 至少包含：sufficient / partial / insufficient。
3. evidence_item 必须包含 shop_id、facet、score、source_type。
4. target_shop_id 不一致的证据不得进入 evidence_pack。
5. forbidden_facets 命中的证据不得进入 evidence_pack。
6. 空召回和不相关召回要区分。
7. 不相关召回不得进入 compose_answer。
```

---

# 第二阶段：P1 多轮、稳定性、可维护性改造

---

## 8. P1-1：Time Travel / replay / fork

### 8.1 是什么

在真实 checkpointer 基础上，进一步支持：

```text
- get_state
- get_state_history
- update_state
- replay from checkpoint
- fork from checkpoint
```

### 8.2 作用

用于定位：

```text
1. 为什么这轮进了 RAG？
2. 为什么 target_shop 串店？
3. 为什么 compose 多答了环境？
4. 为什么 route_gate 和 route_decision 不一致？
5. 为什么 tool 失败后被解释为“没有券”？
```

### 8.3 建议新增调试接口

```text
GET /internal/v1/session/{session_id}/state
GET /internal/v1/session/{session_id}/state/history
POST /internal/v1/session/{session_id}/state/replay
POST /internal/v1/session/{session_id}/state/fork
```

### 8.4 验收标准

```text
1. 能获取指定 session_id 的最新 state。
2. 能获取节点级 state history。
3. 能从指定 checkpoint 复跑。
4. 能修改 routing_contract 后从 compose 前继续执行。
5. 能把错路由 case 固化为回归测试。
```

---

## 9. P1-2：interrupt / resume

### 9.1 是什么

用于图中途暂停，等待用户输入，再从原状态继续。

### 9.2 适用场景

```text
1. 多门店歧义：用户说“海底捞怎么样”，系统发现多个门店。
2. 缺位置：用户说“附近推荐”，但没有位置。
3. 条件不完整：用户说“推荐适合约会的”，但没有范围/预算。
4. 高风险操作确认：预约、下单、取消等。
```

### 9.3 推荐流程

```text
resolve_target
  ↓
发现多个候选
  ↓
interrupt({
  "type": "shop_disambiguation",
  "candidates": [...]
})
  ↓
用户选择 shop_id
  ↓
Command(resume={"selected_shop_id": "..."} )
  ↓
继续 route_decision / rag / tool
```

### 9.4 验收标准

```text
1. 多门店歧义不再随机猜。
2. 澄清后不重新开始整条链路，而是从中断点继续。
3. pending_clarification 能和 checkpoint 对齐。
4. 用户选择候选后 target_shop_id 被正确写入 routing_contract。
5. interrupt 事件能通过 SSE 返回前端。
```

---

## 10. P1-3：RetryPolicy / timeout / degrade

### 10.1 是什么

对容易临时失败的节点增加：

```text
- timeout
- retry
- fallback
- degrade_reason
```

### 10.2 需要治理的节点

```text
1. LLM intent classify / rewrite / answer
2. Qdrant dense retrieval
3. sparse retrieval / BM25
4. reranker
5. JavaBusinessClient
6. coupon API
7. business status API
8. embedding API
```

### 10.3 设计原则

```text
1. 临时网络错误可以 retry。
2. 业务无结果不能 retry 成功，应标记 empty。
3. tool 接口失败不得解释成“没有券”。
4. RAG 失败和 RAG 无结果要区分。
5. 所有降级都写入 metrics.errors / degrade_reason。
```

### 10.4 验收标准

```text
1. Qdrant 超时后有 retry，最终失败则进入 retrieval_degraded。
2. coupon API 失败时回答“实时券信息暂不可用”，不得回答“没有券”。
3. LLM rewrite 失败时可回退到原始 query。
4. reranker 失败时可回退到 fusion score。
5. 所有失败路径都记录 trace_id、node、error_type、degrade_reason。
```

---

## 11. P1-4：真正 compiled subgraph

### 11.1 是什么

当前 `rag_subgraph`、`tool_subgraph` 更像普通函数节点。应升级为真正 LangGraph 子图：

```text
main_graph
  ├─ rag_graph
  ├─ tool_graph
  ├─ recommendation_graph
  └─ compose_graph
```

### 11.2 推荐目录

```text
workflow/
  builder.py
  state.py
  routing.py
  graphs/
    main_graph.py
    rag_graph.py
    tool_graph.py
    recommendation_graph.py
    compose_graph.py
```

### 11.3 RAG 子图

```text
rag_graph:
  build_retrieval_plan
  → query_rewrite
  → parallel_retrieve
  → fusion
  → rerank
  → evidence_filter
  → grade_evidence
  → build_evidence_pack
```

### 11.4 Tool 子图

```text
tool_graph:
  tool_plan
  → tool_execute
  → tool_normalize
  → tool_validate
  → build_tool_result
```

### 11.5 Recommendation 子图

```text
recommendation_graph:
  resolve_location
  → retrieve_candidate_shops
  → filter_candidates
  → rank_candidates
  → build_recommendation_pack
```

### 11.6 验收标准

```text
1. rag_graph 可以独立单测。
2. tool_graph 可以独立单测。
3. main_graph 不再关心 RAG 内部 dense/sparse/rerank 细节。
4. 子图输入输出有明确 schema。
5. 子图可以单独导出 Mermaid 图。
```

---

## 12. P1-5：Runtime Context / context_schema

### 12.1 是什么

把运行时配置、依赖、开关从 state 里拿出去。

例如：

```python
class GraphRuntimeContext(TypedDict):
    workflow_version: str
    prefer_real_adapters: bool
    qdrant_enabled: bool
    reranker_provider: str
    max_tool_timeout_ms: int
    debug: bool
```

### 12.2 应放入 context 的内容

```text
1. workflow_version
2. prefer_real_adapters
3. enable_online_dense_retrieval
4. enable_online_sparse_retrieval
5. reranker_provider
6. qdrant collection name
7. timeout 配置
8. debug / compare mode
9. service clients
```

### 12.3 不应放入 context 的内容

```text
1. 用户原始问题
2. intent
3. target_shop
4. routing_contract
5. evidence_pack
6. tool_result
7. final_answer
```

### 12.4 验收标准

```text
1. GraphState 不再混入大量环境配置。
2. 节点通过 runtime context 读取配置。
3. 测试可以传不同 context 跑同一张图。
4. 灰度 / AB 开关不污染业务状态。
```

---

## 13. P1-6：Reducer / Annotated state merge

### 13.1 是什么

当多个节点并行写同一个字段时，默认可能覆盖。需要 reducer 合并。

### 13.2 需要 reducer 的字段

```python
sse_events: Annotated[list[SSEEvent], operator.add]
errors: Annotated[list[GraphError], operator.add]
evidence_items: Annotated[list[EvidenceItem], operator.add]
tool_results: Annotated[list[ToolResult], operator.add]
shop_analyses: Annotated[list[ShopAnalysis], operator.add]
retrieval_traces: Annotated[list[RetrievalTrace], operator.add]
```

### 13.3 验收标准

```text
1. 多分支同时写 evidence_items 不覆盖。
2. 多工具结果能追加到 tool_results。
3. 多商家分析能追加到 shop_analyses。
4. 并行错误都能记录到 errors。
5. 没有 INVALID_CONCURRENT_GRAPH_UPDATE。
```

---

## 14. P1-7：Recursion Limit / Loop Guard

### 14.1 是什么

限制图执行步数和工具循环次数，防止无限循环。

### 14.2 需要限制的场景

```text
1. RAG rewrite 循环
2. ToolCall 循环
3. 推荐候选不足后反复扩大检索
4. LLM 一直决定继续查工具
```

### 14.3 推荐限制

```text
1. graph recursion_limit：按环境设置，开发可大，生产保守。
2. query_rewrite max_attempts：1 到 2 次。
3. tool_loop max_steps：2 到 3 次。
4. recommendation_expand max_rounds：1 到 2 次。
```

### 14.4 验收标准

```text
1. 任意 query 不会无限卡死。
2. 达到 loop limit 后进入明确降级。
3. final_answer 说明“信息不足/暂不可用”，而不是静默失败。
4. trace 记录 loop_guard_triggered。
```

---

## 15. P1-8：Graph Visualization

### 15.1 是什么

导出主图和子图 Mermaid，用于验收。

### 15.2 要求

```text
1. main_graph 输出 Mermaid。
2. rag_graph 输出 Mermaid。
3. tool_graph 输出 Mermaid。
4. recommendation_graph 输出 Mermaid。
5. 每次 Codex 改造后自动更新 docs/graphs/*.md。
```

### 15.3 推荐文件

```text
docs/langgraph/main_graph.mmd
docs/langgraph/rag_graph.mmd
docs/langgraph/tool_graph.mmd
docs/langgraph/recommendation_graph.mmd
docs/langgraph/langgraph_topology.md
```

### 15.4 验收标准

```text
1. Mermaid 图和实际 builder 保持一致。
2. 图中不存在绕过 route_decision 的异常边。
3. 图中不存在无限循环。
4. P0 路径、P1 路径、P2 路径可视化清楚。
```

---

# 第三阶段：P2 复杂任务、性能、体验增强

---

## 16. P2-1：Send API + map-reduce

### 16.1 是什么

用于动态分发多个子任务：

```text
prepare_candidates
  ↓
Send analyze_one_shop × N
  ↓
reduce_shop_results
```

### 16.2 适用场景

```text
1. 附近推荐多商家
2. 多商家比较
3. 多维度评价
4. 多 query 检索
5. 多候选答案评分
```

### 16.3 不适用场景

```text
1. 用户只问“有券吗”
2. 用户只问“营业吗”
3. 用户只输入“，”
4. 单商家简单查询
```

### 16.4 推荐流程：附近推荐

```text
understand_turn
  ↓
route_decision: recommendation
  ↓
prepare_candidates
  ↓
dispatch_shop_analysis
    ├─ Send(analyze_one_shop, shop_A)
    ├─ Send(analyze_one_shop, shop_B)
    ├─ Send(analyze_one_shop, shop_C)
    └─ Send(analyze_one_shop, shop_D)
  ↓
reduce_shop_results
  ↓
compose_answer
```

### 16.5 验收标准

```text
1. 附近推荐能分析多个候选商家。
2. 每家商家有独立 ShopAnalysis。
3. reduce 阶段能排序、去重、过滤。
4. shop_analyses 使用 reducer，不覆盖。
5. 可配置 max_concurrency。
```

---

## 17. P2-2：原生 streaming + SSE adapter

### 17.1 是什么

逐步把当前手写 SSE 改成基于 LangGraph stream events 的适配层。

### 17.2 推荐映射

```text
LangGraph updates      → state_update
LangGraph messages     → delta
LangGraph custom       → retrieval_started / tool_call / tool_result
LangGraph checkpoints  → checkpoint_debug
LangGraph tasks        → node_started / node_finished
LangGraph debug        → debug
```

### 17.3 改造原则

```text
1. public SSE contract 不要一次性破坏。
2. 保留 ack / final / error。
3. 内部使用 LangGraph stream，外部通过 adapter 转成现有事件。
4. token 流和状态流分开。
```

### 17.4 验收标准

```text
1. 前端无需大改即可继续消费 SSE。
2. 每个节点开始/结束可观测。
3. retrieval_started 与真实 rag node 对齐。
4. tool_call 与真实 tool node 对齐。
5. final 一定在 emit_final 后出现。
```

---

## 18. P2-3：Parallel branches + defer

### 18.1 是什么

用于固定并行分支，不同于 Send 的动态 N 分支。

### 18.2 适用场景

```text
RAG 三路固定召回：
query_rewrite
  ├─ dense_retrieve
  ├─ sparse_retrieve
  └─ metadata_retrieve
       ↓
fusion
       ↓
rerank
```

### 18.3 作用

```text
1. dense/sparse/metadata 可以并行执行。
2. fusion 节点明确等所有召回完成。
3. RAG 子图结构更清楚。
4. 降低延迟。
```

### 18.4 验收标准

```text
1. dense/sparse/metadata 三路结果都进入 fusion。
2. 任一路失败有 degraded trace。
3. fusion 不会在结果缺失时误合并。
4. 并行字段有 reducer。
```

---

## 19. P2-4：Max Concurrency

### 19.1 是什么

控制并行任务数量，防止 API / 数据库被打爆。

### 19.2 适用场景

```text
1. Send API 多商家分析
2. 多 query 检索
3. 多工具并行调用
4. 多维度评价
```

### 19.3 验收标准

```text
1. 可以通过 config 设置 max_concurrency。
2. 多商家推荐不会同时打爆券接口。
3. Qdrant 并发可控。
4. LLM API 并发可控。
```

---

## 20. P2-5：CachePolicy

### 20.1 是什么

缓存昂贵但可复用节点结果。

### 20.2 适合缓存

```text
1. query_rewrite
2. embedding
3. 静态商家详情
4. 父子 sibling 补全
5. 静态 RAG 检索结果
6. rerank 结果，短 TTL
```

### 20.3 不适合长缓存

```text
1. 实时券
2. 营业状态
3. 排队信息
4. 距离
5. 库存/预约
```

### 20.4 验收标准

```text
1. 重复 query 的 rewrite/embedding 成本下降。
2. 实时券不被长缓存污染。
3. cache hit / miss 可观测。
4. TTL 可配置。
```

---

## 21. P2-6：Long-term Store / Memory

### 21.1 是什么

LangGraph 有长期 store 能力，但本项目已经有 Redis / Postgres 记忆设计，因此不建议盲目替换。

### 21.2 推荐边界

```text
Redis：
- 短期会话
- 当前门店
- last_candidates
- pending_clarification

Postgres：
- 长期用户偏好
- 用户常用位置
- 历史选择
- 结构化事实

Qdrant：
- RAG 检索索引
- 不作为事实真相源

LangGraph checkpoint：
- 图运行状态
- thread-level short-term state
```

### 21.3 可选增强

```text
1. 把用户偏好读取包装为 memory node。
2. 把记忆晋升包装为 persist_memory node。
3. 不把长期事实混进 Qdrant。
```

---

## 22. P2-7：Functional API

### 22.1 是什么

用于不重构全图的情况下，给某些长任务增加 checkpoint / retry / interrupt。

### 22.2 适用场景

```text
1. 离线 eval
2. 批量重建索引
3. 长文档分析
4. 批量生成测试报告
```

### 22.3 不建议

```text
主 chat/stream 链路仍建议使用 Graph API，不建议混成两套主流程。
```

---

# 23. 推荐落地顺序

## Day 1：状态与路由硬化

```text
1. 新增 workflow/state.py。
2. 定义 GraphInputState / GraphOutputState / GraphState / RoutingContract。
3. builder.py 从 StateGraph(dict) 改成 StateGraph(GraphState)。
4. route_gate / route_decider 改造为 route_decision_node + Command。
5. 保留旧 route_decider 作为兼容 fallback，但不作为主路径。
```

验收：

```text
- 用户输入“，”不进入 RAG / Tool。
- 用户问“有券吗”只进入 Tool。
- 用户问“环境怎么样”只进入 RAG。
- routing_contract 写入 state。
```

---

## Day 2：合同贯穿 RAG / Tool / Compose

```text
1. RAG 读取 routing_contract。
2. Tool 读取 routing_contract。
3. Compose 读取 routing_contract。
4. 增加 contract validation。
5. forbidden_facets 生效。
```

验收：

```text
- 只问券不回答环境。
- 只问环境不查券。
- A 店问题不得引用 B 店证据。
- tool unavailable 不得回答“没有券”。
```

---

## Day 3：真实 Checkpointer + Replay

```text
1. dependencies.py 增加 get_checkpointer。
2. runner 注入真实 checkpointer。
3. graph.invoke/stream 带 thread_id。
4. 增加 get_state / state_history debug 接口。
5. 移除对 fallback checkpoint 的生产依赖。
```

验收：

```text
- 同 session 多轮 state 可恢复。
- 错误 case 可回放。
- get_state 能返回最新 GraphState。
```

---

## Day 4：Agentic RAG 子图

```text
1. 拆 rag_graph。
2. 增加 evidence_filter_by_contract。
3. 增加 grade_evidence。
4. 增加 insufficient / partial / sufficient 区分。
5. 增加 rewrite_once / degrade。
```

验收：

```text
- 不相关召回不得进入 evidence_pack。
- 空召回与不相关召回区分。
- evidence_item 必须带 shop_id / facet / score。
```

---

## Day 5：Interrupt + Retry + Loop Guard

```text
1. 多门店歧义接入 interrupt。
2. 用户选择后 resume。
3. Qdrant / LLM / Tool 增加 retry / timeout / degrade。
4. 增加 recursion_limit / tool_loop_limit / rewrite_limit。
```

验收：

```text
- “海底捞怎么样”多门店时返回候选卡片。
- 用户选择后继续原流程。
- 工具失败不胡编。
- 无限循环被 guard 拦截。
```

---

## Day 6：Compiled Subgraph + Visualization

```text
1. main_graph / rag_graph / tool_graph / recommendation_graph 拆文件。
2. 子图独立 compile。
3. 子图输入输出 schema 固定。
4. 导出 Mermaid。
5. 增加图结构验收测试。
```

验收：

```text
- RAG 子图可单独测试。
- Tool 子图可单独测试。
- Mermaid 图和实际拓扑一致。
```

---

## Day 7：Send / Streaming / Cache 增强

```text
1. 附近推荐引入 Send analyze_one_shop。
2. shop_analyses 使用 reducer。
3. 增加 reduce_shop_results。
4. LangGraph stream events 接 SSE adapter。
5. query_rewrite / embedding / 静态详情增加 cache。
```

验收：

```text
- 多商家推荐返回多个候选。
- 每个候选有独立分析结果。
- SSE 与节点执行对齐。
- 重复 query 的昂贵节点有 cache hit。
```

---

# 24. 必须新增的测试用例

## 24.1 路由测试

```text
case_route_invalid_input:
  input: "，"
  expect: direct_safe_reply
  forbid: rag_subgraph, tool_subgraph

case_route_coupon_only:
  input: "有券吗"
  expect: tool_graph
  allowed_facets: ["coupon"]
  forbidden_facets: ["environment", "taste", "service"]

case_route_environment_only:
  input: "环境怎么样"
  expect: rag_graph
  allowed_facets: ["environment", "review"]
  forbidden_facets: ["coupon"]

case_route_rag_plus_tool:
  input: "有券吗，环境怎么样"
  expect: rag_plus_tool_graph
```

## 24.2 合同测试

```text
case_compose_forbidden_facets:
  input: "有券吗"
  fake_evidence: environment evidence
  expect: final_answer does not mention environment

case_target_shop_enforced:
  input: "A店有券吗"
  evidence: B店证据
  expect: B店证据被过滤
```

## 24.3 Checkpoint 测试

```text
case_checkpoint_get_state:
  run graph with session_id
  expect graph.get_state returns routing_contract

case_checkpoint_replay:
  run bad case
  replay from route_decision
  expect deterministic path
```

## 24.4 Interrupt 测试

```text
case_shop_disambiguation_interrupt:
  input: "海底捞怎么样"
  candidates: 3 shops
  expect: interrupt with candidates

case_resume_selected_shop:
  resume selected shop_id
  expect: target_shop_id updated and graph continues
```

## 24.5 RAG 证据测试

```text
case_rag_wrong_shop_filtered:
  target_shop_id=A
  retrieved evidence shop_id=B
  expect: filtered

case_rag_insufficient_not_hallucinate:
  evidence_quality=insufficient
  expect: final answer says evidence insufficient
```

## 24.6 Retry / Degrade 测试

```text
case_coupon_api_timeout:
  tool fails timeout
  expect: tool_result unavailable
  final_answer: 实时券信息暂不可用
  forbid: 没有券

case_reranker_failure:
  reranker fails
  expect: fallback to fusion score
```

## 24.7 Send / Map-Reduce 测试

```text
case_nearby_recommend_multi_shop:
  candidates: 5
  expect: 5 ShopAnalysis
  expect: reduce output topN

case_compare_two_shops:
  input: "A和B哪个适合家庭聚餐"
  expect: analyze A and B separately
  expect: final comparison
```

---

# 25. Codex 执行提示词

下面这段可以直接交给 Codex：

```text
你是资深 Python / LangGraph / RAG / Agent 工程师。请在当前 ai-agent 仓库的 learning-agent-service 中，补全 LangGraph 生产级能力。

重要要求：
1. 不要只写计划，必须实际修改代码。
2. 不要偷懒，不要只完成其中一小部分就停止。
3. 先排查当前 LangGraph 使用情况，再按 P0 → P1 → P2 顺序改造。
4. 任何无法完成的项，必须说明原因、影响、替代方案和后续 TODO。
5. 每完成一项必须补测试。
6. 不允许破坏现有 public SSE contract，除非同时提供兼容 adapter。
7. 不允许让 Tool 失败被解释成“没有结果”。
8. 不允许用户只问券时回答环境、口味、服务等未问维度。
9. 不允许 target_shop_id 不一致的证据进入最终回答。
10. 不允许用 Qdrant 作为长期事实真相源。

P0 必须完成：
- 新增强类型 GraphState，替代 StateGraph(dict)。
- 新增 RoutingContract。
- 路由节点改造为 Command(update + goto)。
- routing_contract 贯穿 RAG / Tool / Compose。
- 真实启用 checkpointer，确保 thread_id 生效。
- RAG 增加 evidence_filter_by_contract 和 evidence_quality。
- 增加 invalid_input、coupon_only、environment_only、rag_plus_tool、wrong_shop_evidence 测试。

P1 尽量完成：
- interrupt/resume 支持多门店澄清。
- RetryPolicy / timeout / degrade。
- RAG / Tool 拆成真正 compiled subgraph。
- Runtime Context / context_schema。
- Reducer / Annotated state merge。
- Recursion limit / loop guard。
- Time travel / state history debug 能力。
- Mermaid 图导出。

P2 后续完成：
- Send API + map-reduce，用于附近推荐和多商家比较。
- 原生 LangGraph streaming + SSE adapter。
- Parallel branches，用于 dense/sparse/metadata 并行召回。
- Max concurrency。
- CachePolicy。
- 可选 Long-term Store / Functional API。

验收重点：
- 输入“，”不得触发 RAG / Tool。
- “有券吗”只查券，只回答券。
- “环境怎么样”只走 RAG，不查券。
- “有券吗，环境怎么样”才走 rag_plus_tool。
- A 店问题不得使用 B 店证据。
- 工具失败必须回答“暂不可用/无法确认”，不得回答“没有”。
- 每轮执行可通过 session_id 获取 state。
- 多门店歧义可以 interrupt，用户选择后 resume。
- RAG 证据不足时不胡编。
- 所有新增能力有 pytest 覆盖。
```

---

# 26. 最终判断

这次补 LangGraph 能力的核心不是 Send，也不是多 Agent，而是：

```text
1. 强类型状态
2. 硬路由
3. 路由合同
4. 真实 checkpoint
5. 证据评估
6. 可回放
7. 可中断恢复
8. 可并行扩展
```

优先级必须遵守：

```text
先修正确性：
- Typed State
- Command
- Routing Contract
- Checkpointer
- Evidence Guard

再修稳定性：
- Interrupt
- Retry
- Subgraph
- Time Travel
- Loop Guard

最后修复杂任务和体验：
- Send
- Streaming
- Cache
- Max Concurrency
```

一句话总结：

> 当前项目已经接入 LangGraph，但还停留在基础图编排层。补完以上能力后，项目才会从“能跑的 LangGraph workflow”升级为“可控、可回放、可测试、可扩展的生产级本地生活 Agent 图编排系统”。
