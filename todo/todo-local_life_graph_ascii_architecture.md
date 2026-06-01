# 本地生活 Agent 当前图编排结构 ASCII 架构图

> 目标：画出当前本地生活 Agent 的实际图编排结构、各类子图结构，并明确说明哪些部分是真正 LangGraph 控制，哪些只是“图式模块/阶段函数”。
>
> 结论先行：当前本地生活 Agent 有明显的“图式编排思想”，但很多节点并不是由 LangGraph `StateGraph` 统一编排和控制，而是由 `LocalLifeSubgraph.run_stream()` 这个主方法顺序调用模块，并通过条件分支进入不同执行路径。

---

# 1. 当前是否真的使用 LangGraph 编排？

## 1.1 结论

当前本地生活部分更准确地说是：

```text
Sequential Workflow / Subgraph-like Orchestration
```

而不是严格意义上的：

```text
LangGraph StateGraph Runtime
```

也就是说：

```text
代码里有“节点感”：
- normalize_query
- extract_slots
- UserNeedParser
- RouteReview
- EntityResolver
- RAG
- Tool
- EvidenceScopeGuard
- ResponseBuilder
- AnswerSanitizer

但这些大多数不是通过 LangGraph 的：
- StateGraph(...)
- add_node(...)
- add_edge(...)
- add_conditional_edges(...)
- compile(...)
来注册和运行。
```

当前更像：

```text
LocalLifeSubgraph.run_stream()
  手动串联多个模块
  手动维护 state
  手动 yield SSE
  手动 if/else 分支
```

---

## 1.2 什么才算真正 LangGraph 编排？

真正 LangGraph 编排通常应该具备：

```python
graph = StateGraph(State)

graph.add_node("load_context", load_context)
graph.add_node("understand_query", understand_query)
graph.add_node("route_review", route_review)
graph.add_node("execute_tools", execute_tools)
graph.add_node("retrieve_evidence", retrieve_evidence)
graph.add_node("build_response", build_response)

graph.add_edge(START, "load_context")
graph.add_edge("load_context", "understand_query")
graph.add_conditional_edges("route_review", route_decider)
graph.add_edge("build_response", END)

compiled = graph.compile()
```

并且真实请求链路应该调用：

```python
compiled.stream(...)
compiled.invoke(...)
```

当前本地生活链路更像：

```python
def run_stream(...):
    yield load_context_started
    understanding = normalize_query(...)
    slots = extract_slots(...)
    user_need = UserNeedParser.parse(...)
    route = LocalLifeQueryRouter.route(...)
    review = RouteReview.review(...)
    contract = EntityResolver().resolve(...)
    if need_clarification:
        ...
    elif execute_rag and execute_tools:
        ...
    elif execute_tools:
        ...
    elif execute_rag:
        ...
    response = build_response_bundle(...)
    yield final
```

---

## 1.3 当前状态一句话判断

```text
当前不是“没有图”，而是“图在代码逻辑里”，不是“图在 LangGraph Runtime 里”。
```

换句话说：

```text
当前有：
- 主流程
- 阶段状态
- 条件分支
- 子模块
- SSE 事件
- 部分 execution contract

但缺少：
- 显式 StateGraph
- 显式 node
- 显式 edge
- 显式 conditional edge
- compile
- checkpointer
- LangGraph 级别的可恢复执行
- LangGraph 级别的节点可观测与回放
```

---

# 2. 当前实际在线链路总图

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                              用户 / 前端 UI                                 │
│                                                                            │
│  输入示例：                                                                  │
│  - 海底捞水晶城店怎么样？                                                     │
│  - 这家有券吗？                                                              │
│  - 附近有没有推荐的餐厅？                                                      │
└────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        Java Chat Stream API                                 │
│                                                                            │
│  典型接口：                                                                  │
│  POST /api/ai/chat/stream                                                    │
│                                                                            │
│  职责：                                                                      │
│  - 接收前端请求                                                               │
│  - 构造用户消息                                                               │
│  - 调用 Python learning-agent-service                                        │
│  - 透传 SSE                                                                  │
└────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    Python learning-agent-service                            │
│                                                                            │
│  输入对象：                                                                  │
│  - ChatTurnCommand                                                           │
│  - PersistentSessionContext                                                  │
│  - GraphRuntimeMeta                                                          │
└────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                     LocalLifeSubgraph.run_stream                             │
│                                                                            │
│  当前核心编排器：                                                             │
│  - 手动构造 LocalLifeTurnState                                                │
│  - 手动执行各个阶段                                                           │
│  - 手动判断条件分支                                                           │
│  - 手动 yield SSE                                                            │
│                                                                            │
│  注意：这里叫 Subgraph，但当前实际更像“顺序工作流编排器”。                    │
└────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                              SSE Event Stream                               │
│                                                                            │
│  可能事件：                                                                  │
│  - load_context_started                                                      │
│  - load_context_done                                                         │
│  - retrieval_started                                                         │
│  - retrieval_result                                                          │
│  - tool_call                                                                 │
│  - tool_result                                                               │
│  - clarification_card                                                        │
│  - final                                                                     │
│  - error                                                                     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

# 3. 当前主编排结构 ASCII 图

```text
┌──────────────────────────────────────────────────────────────────────┐
│ START: ChatTurnCommand                                                │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 0. load_context                                                       │
│                                                                      │
│ 当前实现方式：                                                        │
│ - run_stream 内直接 yield LOAD_CONTEXT_STARTED                        │
│ - run_stream 内直接 yield LOAD_CONTEXT_DONE                           │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是独立 LangGraph node                                             │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 1. build_understanding_hint                                           │
│                                                                      │
│ 输入：                                                                │
│ - raw_query                                                           │
│ - client_context                                                      │
│ - session_context                                                     │
│                                                                      │
│ 当前实现方式：                                                        │
│ - 普通函数/方法调用                                                    │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是独立 LangGraph node                                             │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. Query Understanding                                                │
│                                                                      │
│ normalize_query                                                       │
│   ↓                                                                  │
│ extract_slots                                                         │
│   ↓                                                                  │
│ UserNeedParser.parse                                                  │
│   ↓                                                                  │
│ ContextArbitration.arbitrate                                          │
│                                                                      │
│ 当前实现方式：                                                        │
│ - run_stream 内直接顺序调用                                            │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是一组 LangGraph nodes                                            │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. Init LocalLifeTurnState                                            │
│                                                                      │
│ 创建状态对象：                                                        │
│ - trace_id                                                           │
│ - session_id                                                         │
│ - raw_query                                                          │
│ - client_context                                                     │
│ - persistent_context                                                 │
│ - understanding                                                      │
│ - slots                                                              │
│ - intent                                                             │
│ - user_need                                                          │
│ - clarification                                                      │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 有状态对象，但不是 LangGraph StateGraph 的统一 state reducer 控制     │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. Routing / RouteReview                                              │
│                                                                      │
│ LocalLifeQueryRouter.route                                            │
│   ↓                                                                  │
│ RouteReview.review                                                    │
│                                                                      │
│ 输出：                                                                │
│ - query_route                                                         │
│ - route_review                                                        │
│ - execution_requirements                                              │
│ - reviewed_clarification                                              │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是 add_conditional_edges 控制                                      │
│ - 是普通 Python if/else 分支前的 route 计算                            │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. EntityResolver / ExecutionContract                                 │
│                                                                      │
│ EntityResolver.resolve                                                │
│   ↓                                                                  │
│ execution_contract                                                    │
│   ↓                                                                  │
│ resolved_shop_ids                                                     │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是 LangGraph node                                                 │
│ - 是 run_stream 中普通模块调用                                         │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 6. Branch Gate                                                        │
│                                                                      │
│ if need_clarification:                                                │
│     clarification branch                                               │
│ elif execute_rag and execute_tools:                                    │
│     rag_plus_tool branch                                               │
│ elif execute_tools:                                                    │
│     tool branch                                                        │
│ elif execute_rag:                                                      │
│     rag branch                                                         │
│ else:                                                                 │
│     fallback/direct branch                                             │
│                                                                      │
│ LangGraph 状态：                                                      │
│ - 不是 LangGraph conditional edge                                      │
│ - 是 Python 条件分支                                                   │
└──────────────────────────────────────────────────────────────────────┘
          │                    │                     │                    │
          ▼                    ▼                     ▼                    ▼
┌────────────────┐   ┌──────────────────┐   ┌────────────────┐   ┌────────────────┐
│ Clarification  │   │ RAG + Tool        │   │ Tool Only      │   │ RAG Only       │
│ Branch         │   │ Branch            │   │ Branch         │   │ Branch         │
└────────────────┘   └──────────────────┘   └────────────────┘   └────────────────┘
          │                    │                     │                    │
          └──────────────┬─────┴─────────────┬───────┴────────────┬──────┘
                         ▼                   ▼                    ▼
                ┌────────────────────────────────────────────────────────┐
                │ 7. Answer Build / Verify / Sanitize                    │
                │                                                        │
                │ AnswerPlanner / GroundedVerifier if wired              │
                │   ↓                                                    │
                │ build_response_bundle                                  │
                │   ↓                                                    │
                │ sanitize_local_life_output                             │
                │                                                        │
                │ LangGraph 状态：                                        │
                │ - 不是独立 LangGraph nodes                              │
                │ - 是普通函数调用                                        │
                └────────────────────────────────────────────────────────┘
                         │
                         ▼
                ┌────────────────────────────────────────────────────────┐
                │ 8. Persist Context                                      │
                │                                                        │
                │ _persist_context                                       │
                │ - current_shop                                         │
                │ - selected_shop_id                                     │
                │ - last_candidates                                      │
                │ - pending_user_need                                    │
                │                                                        │
                │ LangGraph 状态：                                        │
                │ - 不是 checkpointer 管理                                │
                │ - 是业务 session 写回                                   │
                └────────────────────────────────────────────────────────┘
                         │
                         ▼
                ┌────────────────────────────────────────────────────────┐
                │ 9. Emit FINAL SSE                                       │
                └────────────────────────────────────────────────────────┘
```

---

# 4. 当前“节点感”和“LangGraph 节点”的区别

## 4.1 当前代码里的节点感

当前这些模块确实像节点：

```text
normalize_query
extract_slots
UserNeedParser
ContextArbitration
LocalLifeQueryRouter
RouteReview
EntityResolver
EvidenceScopeGuard
AnswerPlanner
GroundedVerifier
ResponseBuilder
AnswerSanitizer
PersistContext
```

它们具备“节点”的业务含义：

```text
输入状态 → 做一段处理 → 输出新的状态片段
```

但是它们多数不是 LangGraph runtime 里的 node。

---

## 4.2 真正 LangGraph 节点应该是什么样

真正 LangGraph 节点应当被显式注册：

```python
builder.add_node("understand_query", understand_query)
builder.add_node("route_review", route_review)
builder.add_node("resolve_entity", resolve_entity)
builder.add_node("execute_tools", execute_tools)
builder.add_node("retrieve_evidence", retrieve_evidence)
builder.add_node("build_response", build_response)
```

边也应该显式注册：

```python
builder.add_edge("understand_query", "route_review")
builder.add_conditional_edges("route_review", route_decider)
builder.add_edge("build_response", END)
```

最终要：

```python
graph = builder.compile()
graph.stream(input_state)
```

当前本地生活在线链路没有完全这样组织。

---

# 5. 当前子图清单

## 5.1 Query Understanding 子图

```text
raw_query
  ↓
normalize_query
  ↓
extract_slots
  ↓
UserNeedParser.parse
  ↓
ContextArbitration.arbitrate
  ↓
understanding / slots / intent / user_need / clarification
```

当前类型：

```text
函数型子图，不是 LangGraph 子图。
```

风险：

```text
1. shop_query 可能被误当成 shop_detail。
2. 当前轮显式商铺和 session 商铺的优先级需要更硬。
3. query rewrite 可能把历史商铺注入当前新商铺问题。
```

---

## 5.2 Routing / RouteReview 子图

```text
LocalLifeQueryRouter.route
  ↓
RouteReview.review
  ↓
ExecutionRequirements
  ↓
Python if/else branch gate
```

当前类型：

```text
函数型路由子图，不是 LangGraph conditional edge。
```

风险：

```text
1. execution_requirements 可以包含多个 tools，但执行层可能仍取第一个。
2. 当前更像 ExecutionRequirements，不是真正 FacetExecutionPlan。
3. 推荐类问题需要明确 recommendation_count。
```

---

## 5.3 Entity Resolution 子图

```text
EntityResolver.resolve
  ↓
ExecutionContract
  ↓
resolved_shop_ids
```

当前类型：

```text
普通模块调用，不是 LangGraph 子图。
```

推荐目标：

```text
EntityResolver
  ↓
TargetShopPolicy
  ↓
ExecutionContract
  ↓
EntityConsistency
```

目标图：

```text
┌──────────────────────────────────────────┐
│ Detect current-turn explicit entity       │
└──────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ TargetShopPolicy                          │
│ 1. current query entity                    │
│ 2. explicit candidate selection            │
│ 3. pronoun + session.current_shop          │
│ 4. session.current_shop                    │
│ 5. RAG top1 only as fallback               │
└──────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ target_shop / single_shop_mode             │
│ recommendation_mode                        │
└──────────────────────────────────────────┘
```

---

## 5.4 Clarification 子图

```text
clarification.need_clarification == true
  ↓
Emit CLARIFICATION_CARD SSE
  ↓
build_response_bundle(mode=clarify)
  ↓
sanitize_local_life_output
  ↓
Persist pending_user_need
  ↓
Emit FINAL SSE
```

当前类型：

```text
Python if 分支，不是 LangGraph branch。
```

风险：

```text
1. 商铺不明确时必须澄清，而不是 RAG top1。
2. 多家同名门店必须澄清门店，不应混用。
```

---

## 5.5 RAG + Tool 子图

```text
Build retrieval filters
  ↓
Emit RETRIEVAL_STARTED
  ↓
Choose tool = execute_tools[0]   ← 当前风险
  ↓
Determine first_shop_id          ← 当前风险：不是严格 target_shop
  ↓
Emit TOOL_CALL
  ↓
Structured Candidate Acquisition
  ↓
Candidate Filtering
  ↓
RAG Retrieve / Evidence Build
  ↓
EvidenceScopeGuard
  ↓
Fuse + Rank
  ↓
ResponseBuilder
```

当前类型：

```text
Python 分支内手动执行，不是 LangGraph 子图。
```

风险：

```text
1. 多工具计划只取 execute_tools[0]。
2. first_shop_id 不等于严格 target_shop。
3. 单店 RAG 和推荐 RAG 没有足够强的结构区分。
4. 推荐场景可能只输出 top1。
```

---

## 5.6 Tool 子图

```text
Tool Planning
  ↓
Tool Input Build
  ↓
Emit TOOL_CALL
  ↓
JavaBusinessClient / Catalog Fallback
  ↓
Tool Result Normalize
  ↓
Emit TOOL_RESULT
```

目标多工具结构：

```text
FacetExecutionPlan
  ├── coupon       → get_coupon_list   → CouponResult
  ├── open_status  → check_open_status → StatusResult
  └── distance_eta → get_distance_eta  → DistanceResult
          ↓
FacetResultBundle
```

当前类型：

```text
分支内工具调用，不是独立 LangGraph tool node。
```

---

## 5.7 RAG / Evidence 子图

当前：

```text
Retrieval Query
  ↓
Retriever / Qdrant / Catalog fallback
  ↓
Retrieval Results
  ↓
build_evidence_pack
  ↓
EvidenceScopeGuard
```

目标拆分：

```text
single_shop_rag:
  target_shop
    ↓
  shop_id 强过滤
    ↓
  只返回目标店证据

recommendation_rag:
  retrieve topK chunks
    ↓
  group by shop_id
    ↓
  aggregate per shop
    ↓
  rank shop groups
    ↓
  topN shops，默认 3 家
```

当前类型：

```text
函数型检索子图，不是独立 LangGraph 子图。
```

---

## 5.8 Fusion / Rank 子图

```text
structured_candidates
semantic_evidence
tool_results
slots
user_need
  ↓
merge_business_facts_with_semantic_evidence
  ↓
fuse_candidates
  ↓
rank_candidates
  ↓
ranked_candidates
```

风险：

```text
1. single_shop_mode 下不应该重新用 rank top1 改写目标商铺。
2. recommendation_mode 下需要按 shop_id 分组排序，而不是按 chunk 排序。
3. 推荐场景需要 topN shops，不是 top1。
```

---

## 5.9 Answer 子图

当前：

```text
AnswerPlanner
  ↓
GroundedVerifier
  ↓
build_response_bundle
  ↓
sanitize_local_life_output
```

目标：

```text
AnswerContract
  ↓
AnswerPlanner，只能规划允许的内容
  ↓
GroundedVerifier，证据不足则降级/删除/标记 missing_info
  ↓
ResponseBuilder，按不同模式输出
  ↓
Contract Validation
  ↓
AnswerSanitizer
```

推荐模式：

```text
coupon_only
open_status_only
distance_only
single_shop_review
multi_shop_recommendation
comparison
clarification
```

当前类型：

```text
函数型回答子图，不是独立 LangGraph 子图。
```

---

## 5.10 Persistence / Session 子图

```text
_persist_context
  ↓
PersistentSessionContext
  ↓
下一轮 ContextArbitration / EntityResolver / Query Rewrite
```

写入内容可能包括：

```text
current_shop
selected_shop_id
selected_shop_name
last_candidates
pending_user_need
history_summary
user preferences
```

当前类型：

```text
业务 session 写回，不是 LangGraph checkpointer。
```

风险：

```text
1. current_shop 可能污染下一轮新商铺问题。
2. 上一轮 required_facets 不应继承到下一轮。
3. 只有“这家/它/刚才那个”才应使用 current_shop。
```

---

# 6. 当前“图式编排”与“LangGraph 编排”的对照表

| 模块 | 当前是否存在 | 当前是否 LangGraph 控制 | 当前实现形态 | 建议 |
|---|---:|---:|---|---|
| load_context | 是 | 否 | run_stream 内 yield SSE | 可做 LangGraph node |
| normalize_query | 是 | 否 | 普通函数调用 | 可做 understand_query 子节点 |
| extract_slots | 是 | 否 | 普通函数调用 | 可做 understand_query 子节点 |
| UserNeedParser | 是 | 否 | 静态 parse 调用 | 可做 node |
| ContextArbitration | 是 | 否 | 普通类方法调用 | 可做 node |
| QueryRouter | 是 | 否 | 普通类方法调用 | 可做 route node |
| RouteReview | 是 | 否 | 普通类方法调用 | 可做 route_review node |
| EntityResolver | 是 | 否 | 普通类方法调用 | 可做 resolve_target node |
| Clarification Branch | 是 | 否 | Python if 分支 | 可做 conditional edge |
| Tool Branch | 是 | 否 | Python if 分支 | 可做 tool subgraph |
| RAG Branch | 是 | 否 | Python if 分支 | 可做 rag subgraph |
| RAG + Tool Branch | 是 | 否 | Python if 分支 | 可做 parallel / sequential subgraph |
| EvidenceScopeGuard | 是 | 否 | 普通函数/类调用 | 可做 evidence_guard node |
| Fusion/Rank | 是 | 否 | 普通函数调用 | 可做 rank node |
| AnswerPlanner | 是 | 部分/需确认 | 模块存在，接入程度需确认 | 可做 answer_plan node |
| GroundedVerifier | 是 | 部分/需确认 | 模块存在，接入程度需确认 | 可做 verify node |
| ResponseBuilder | 是 | 否 | 普通函数调用 | 可做 response node |
| AnswerSanitizer | 是 | 否 | 普通函数调用 | 可做 sanitize node |
| PersistContext | 是 | 否 | 业务 session 写回 | 可做 persist node / checkpointer 辅助 |

---

# 7. 当前问题对应的故障定位图

```text
Query Understanding
  │
  ├─ 风险：店名未被识别为 current_query entity
  ├─ 风险：shop_query 被误当 shop_detail
  ▼
ContextArbitration / EntityResolver
  │
  ├─ 风险：session.current_shop 覆盖当前轮新商铺
  ├─ 风险：第二个商铺被第一个商铺污染
  ├─ 风险：“这家/它”与显式新商铺没有区分
  ▼
RouteReview / ExecutionRequirements
  │
  ├─ 风险：recommendation_count 未设置
  ├─ 风险：多工具计划没有变成真正 FacetExecutionPlan
  ▼
RAG / Retriever
  │
  ├─ 风险：召回不相关商铺
  ├─ 风险：single_shop_rag 没有 shop_id 强过滤
  ├─ 风险：recommendation_rag 没有 group by shop_id
  ▼
Tool
  │
  ├─ 风险：coupon tool 未绑定 target_shop_id
  ├─ 风险：优惠券数量来自错误口径
  ├─ 风险：多工具只执行第一个
  ▼
Fusion / Rank
  │
  ├─ 风险：single_shop_mode 下 top1 改写目标店
  ├─ 风险：推荐场景只保留一个 shop
  ▼
ResponseBuilder / AnswerPlanner
  │
  ├─ 风险：问 A 答 B
  ├─ 风险：附近推荐只输出一个
  ├─ 风险：问券却输出环境/推荐
  └─ 风险：tool 返回数量和文本数量不一致
```

---

# 8. 推荐目标 LangGraph 化结构

等 P0/P1 问题稳定后，再收敛为真正 LangGraph：

```text
┌────────────────────────────────────────────────────────────────────┐
│ LocalLife StateGraph                                                │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────┐
│ START                │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│ load_context          │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│ understand_query      │
│ - normalize           │
│ - slots               │
│ - user_need           │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│ resolve_target        │
│ - target_shop         │
│ - current > session   │
│ - single/recommend    │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│ build_contracts       │
│ - ExecutionContract   │
│ - AnswerContract      │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│ route_gate            │
└──────────────────────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
│clarify │ │tool    │ │rag     │ │rag_plus_tool │
└────────┘ └────────┘ └────────┘ └──────────────┘
    │          │          │          │
    └──────────┴────┬─────┴──────────┘
                    ▼
          ┌──────────────────┐
          │ entity_consistency│
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ evidence_fusion   │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ answer_plan       │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ grounded_verify   │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ response_build    │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ sanitize          │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ persist_context   │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │ END / final_sse   │
          └──────────────────┘
```

---

# 9. 应该优先 LangGraph 化哪些节点？

不建议一次性全部 LangGraph 化。

## 第一批：最影响当前错误的节点

```text
1. understand_query
2. resolve_target
3. build_contracts
4. route_gate
5. single_shop_rag / recommendation_rag
6. response_build
```

原因：

```text
这几块直接决定：
- 问 A 是否答 A
- 第二轮是否被第一轮污染
- RAG 是否召回错店
- 推荐是否只给一个
```

## 第二批：增强可观测和可回放

```text
1. execute_tools
2. evidence_fusion
3. grounded_verify
4. sanitize
5. persist_context
```

## 第三批：优化复杂执行能力

```text
1. parallel tool execution
2. map-reduce recommendation
3. multi-shop comparison
4. human clarification resume
5. checkpoint retry
```

---

# 10. Chat 接口测试图

```text
┌────────────────────────────────────────────────────────────────────┐
│ Chat Golden Test Runner                                             │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ POST /api/ai/chat/stream                                            │
│                                                                    │
│ 输入：                                                              │
│ - sessionId                                                         │
│ - userId                                                            │
│ - message                                                           │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Parse SSE                                                           │
│                                                                    │
│ 收集：                                                              │
│ - delta                                                             │
│ - final                                                             │
│ - error                                                             │
│ - tool_call                                                         │
│ - tool_result                                                       │
│ - retrieval_result                                                  │
│ - metrics / context                                                 │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Assertions                                                          │
│                                                                    │
│ A. 单店问题：                                                        │
│ - target_shop 正确                                                   │
│ - 不出现其他商铺                                                     │
│                                                                    │
│ B. 多轮切换：                                                        │
│ - 第二轮显式商铺覆盖第一轮                                            │
│                                                                    │
│ C. RAG：                                                            │
│ - single_shop evidence.shop_id 全部一致                              │
│                                                                    │
│ D. Coupon：                                                         │
│ - 文本数量 == CouponResult.realtime_available_count                  │
│                                                                    │
│ E. Recommendation：                                                 │
│ - 默认 >= 3 个不同商铺                                                │
└────────────────────────────────────────────────────────────────────┘
```

---

# 11. 最终结论

当前诸多“节点”并不是没有价值，它们已经是比较清晰的模块化阶段。

但从 LangGraph 的角度看，当前状态是：

```text
业务节点存在
图式流程存在
状态对象存在
SSE 事件存在

但大多数节点没有被 StateGraph 显式注册
大多数边没有被 add_edge / add_conditional_edges 显式控制
分支主要由 Python if/else 控制
持久化主要是业务 session，不是 LangGraph checkpointer
```

因此，当前可以称为：

```text
Subgraph-like Sequential Workflow
```

不应称为完整的：

```text
LangGraph StateGraph Orchestration
```

后续最稳的路线是：

```text
先修 target_shop / RAG 实体过滤 / CouponResult / multi-shop recommendation
再把这些稳定模块迁移成真正 LangGraph nodes
最后加入 checkpointer、conditional edges、subgraph、interrupt/resume
```
