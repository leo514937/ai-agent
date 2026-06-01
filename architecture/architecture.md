当前总架构

START
  │
  ▼
┌──────────────────────┐
│ 1. load_context       │
│                      │
│ 读 session / memory   │
│ 读 client_context     │
│ 初始化 trace_id       │
└──────────────────────┘
  │
  ▼
┌──────────────────────┐
│ 2. understand_query   │
│                      │
│ normalize_query       │
│ extract_slots         │
│ UserNeedParser        │
│ ContextArbitration    │
└──────────────────────┘
  │
  ▼
┌──────────────────────┐
│ 3. resolve_target     │
│                      │
│ TargetShopPolicy      │
│ current_query >       │
│ session.current_shop  │
│                      │
│ 输出：                │
│ target_shop           │
│ single_shop_mode      │
│ recommendation_mode   │
└──────────────────────┘
  │
  ▼
┌──────────────────────┐
│ 4. build_contracts    │
│                      │
│ ExecutionContract     │
│ AnswerContract        │
│ FacetExecutionPlan    │
└──────────────────────┘
  │
  ▼
┌──────────────────────┐
│ 5. route_review       │
│                      │
│ RouteReview           │
│ 校验是否需要澄清       │
│ 校验是否 RAG / Tool   │
│ 校验是否多分支执行     │
└──────────────────────┘
  │
  ▼
┌──────────────────────┐
│ 6. route_gate         │
│ conditional edges     │
└──────────────────────┘
  │
  ├───────────────────────────────┐
  │                               │
  ▼                               ▼
┌──────────────┐          ┌────────────────────┐
│ clarify      │          │ execute_plan_gate   │
│ 子图          │          │ 复杂任务分发器       │
└──────────────┘          └────────────────────┘
  │                               │
  │                               ├──────────────┬──────────────┬──────────────┐
  │                               │              │              │              │
  │                               ▼              ▼              ▼              ▼
  │                     ┌────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐
  │                     │ tool_subgraph  │ │ rag_subgraph │ │ recommend_   │ │ direct_answer  │
  │                     │                │ │              │ │ subgraph     │ │ subgraph       │
  │                     └────────────────┘ └──────────────┘ └──────────────┘ └────────────────┘
  │                               │              │              │              │
  │                               └──────┬───────┴──────┬───────┴──────┬───────┘
  │                                      ▼              ▼              ▼
  │                          ┌────────────────────────────────────────────────┐
  │                          │ 7. entity_consistency / result_join             │
  │                          │                                                │
  │                          │ 对齐：                                          │
  │                          │ - target_shop                                   │
  │                          │ - tool_result.shop_id                           │
  │                          │ - evidence.shop_id                              │
  │                          │ - recommendation candidate shop_id              │
  │                          └────────────────────────────────────────────────┘
  │                                      │
  └──────────────────────────────┬───────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ 8. fuse_and_rank          │
                    │                          │
                    │ 单店：锁死 target_shop    │
                    │ 推荐：按 shop_id 分组排序 │
                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 9. plan_answer            │
                    │                          │
                    │ AnswerPlanner             │
                    │ 只能规划 contract 允许内容│
                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 10. verify_grounding      │
                    │                          │
                    │ GroundedVerifier          │
                    │ 校验证据 / 券数量 / 店铺   │
                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 11. build_response        │
                    │                          │
                    │ ResponseBuilder           │
                    │ coupon_only               │
                    │ open_status_only          │
                    │ single_shop_review        │
                    │ multi_shop_recommendation │
                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 12. sanitize_response     │
                    │                          │
                    │ 清理 shop:5 / shop_id     │
                    │ open/closed/unknown 中文化│
                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 13. persist_context       │
                    │                          │
                    │ 更新 current_shop         │
                    │ 更新 last_candidates      │
                    │ 保存 pending_clarification│
                    └──────────────────────────┘
                                 │
                                 ▼
                               END


分支一：澄清子图 clarify_subgraph
clarify_subgraph
  │
  ▼
┌────────────────────────┐
│ build_clarification    │
│ 生成澄清问题             │
└────────────────────────┘
  │
  ▼
┌────────────────────────┐
│ emit_clarification_card│
│ SSE: clarification_card │
└────────────────────────┘
  │
  ▼
┌────────────────────────┐
│ persist_pending_need    │
│ 保存 pending_user_need  │
└────────────────────────┘
  │
  ▼
END

分支二：工具子图 tool_subgraph

tool_subgraph
  │
  ▼
┌──────────────────────────────┐
│ read FacetExecutionPlan       │
└──────────────────────────────┘
  │
  ├─────────────────────┬──────────────────────┬──────────────────────┐
  │                     │                      │                      │
  ▼                     ▼                      ▼                      ▼
┌──────────────┐ ┌──────────────┐      ┌────────────────┐      ┌────────────────┐
│ coupon_tool  │ │ status_tool  │      │ distance_tool  │      │ detail_tool    │
└──────────────┘ └──────────────┘      └────────────────┘      └────────────────┘
  │                     │                      │                      │
  ▼                     ▼                      ▼                      ▼
┌──────────────┐ ┌──────────────┐      ┌────────────────┐      ┌────────────────┐
│ CouponResult │ │ StatusResult │      │ DistanceResult │      │ ShopDetailResult│
└──────────────┘ └──────────────┘      └────────────────┘      └────────────────┘
  │                     │                      │                      │
  └──────────────┬──────┴──────────────┬───────┴──────────────┬───────┘
                 ▼                     ▼                      ▼
          ┌────────────────────────────────────────────────────────┐
          │ FacetResultBundle                                       │
          │                                                        │
          │ coupon       → CouponResult                             │
          │ open_status  → StatusResult                             │
          │ distance_eta → DistanceResult                           │
          │ shop_detail  → ShopDetailResult                         │
          └────────────────────────────────────────────────────────┘


分支三：RAG 子图 rag_subgraph


1 single_shop_rag


single_shop_rag
  │
  ▼
┌──────────────────────────────┐
│ require target_shop           │
│ single_shop_mode = true       │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ build facet query             │
│ environment / scene / review  │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ Qdrant / Retriever filter     │
│ MUST shop_id = target_shop.id │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ retrieve evidence             │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ EvidenceScopeGuard            │
│ 丢弃非 target_shop 证据        │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ EvidencePack                  │
│ 全部证据属于 target_shop       │
└──────────────────────────────┘


2 recommendation_rag

recommendation_rag
  │
  ▼
┌──────────────────────────────┐
│ recommendation_mode = true    │
│ recommendation_count = 3 / 5  │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ retrieve topK chunks          │
│ topK = 30 / 50                │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ group by shop_id              │
│ 防止 topK 都来自同一家店       │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ aggregate evidence per shop   │
│ 每家店聚合环境/口味/价格/券     │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ rank shop groups              │
│ 输出 topN different shops     │
└──────────────────────────────┘
  │
  ▼
┌──────────────────────────────┐
│ RecommendationResult           │
│ 默认 3 家，不是 1 家            │
└──────────────────────────────┘

分支四：推荐子图 recommendation_subgraph

recommendation_subgraph
  │
  ▼
┌──────────────────────────────┐
│ parse recommendation_count    │
│ 默认 3                        │
│ “一家” → 1                    │
│ “多几家” → 5                  │
└──────────────────────────────┘
  │
  ├──────────────────────────┬──────────────────────────┬──────────────────────────┐
  │                          │                          │                          │
  ▼                          ▼                          ▼                          ▼
┌────────────────┐   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ nearby_tool    │   │ recommendation_rag │   │ distance_tool       │   │ coupon_tool optional│
│ 找候选商铺      │   │ 找语义推荐理由       │   │ 算距离/耗时          │   │ 查券                 │
└────────────────┘   └────────────────────┘   └────────────────────┘   └────────────────────┘
  │                          │                          │                          │
  └──────────────┬───────────┴──────────────┬───────────┴──────────────┬───────────┘
                 ▼                          ▼                          ▼
        ┌────────────────────────────────────────────────────────────────┐
        │ merge recommendation candidates                                 │
        │                                                                │
        │ 按 shop_id 合并：                                                │
        │ - nearby candidate                                               │
        │ - RAG evidence                                                   │
        │ - distance                                                       │
        │ - coupon                                                         │
        └────────────────────────────────────────────────────────────────┘
                 │
                 ▼
        ┌────────────────────────────────────────────────────────────────┐
        │ rank topN shops                                                 │
        │                                                                │
        │ 默认输出 3 家                                                     │
        └────────────────────────────────────────────────────────────────┘



**最终建议的 RAG 图**
                      ┌──────────────────────┐
                      │    route_gate         │
                      └──────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────────┐
     │ no_rag         │ │ single_shop_rag│ │ recommendation_rag │
     │ tool/direct    │ │ 单店证据检索     │ │ 多店推荐检索         │
     └────────────────┘ └───────┬────────┘ └─────────┬──────────┘
                                │                    │
                                ▼                    ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │ shop_id hard filter  │  │ retrieve topK chunks  │
                  │ target_shop only     │  │ group by shop_id      │
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             ▼                        ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │ EvidencePack          │  │ ShopGroupEvidence     │
                  │ 单店证据包             │  │ 多店证据组             │
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             └──────────┬─────────────┘
                                        ▼
                         ┌──────────────────────────┐
                         │ EntityConsistency         │
                         │ 证据/工具/候选店对齐       │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ Fusion / Rank             │
                         │ 单店锁死 target_shop       │
                         │ 推荐输出 topN shops        │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ AnswerContract            │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ ResponseBuilder           │
                         └──────────────────────────┘


下面这版是**当前最终建议架构**，不是当前现状。
核心思想是：

```text
LangGraph MainGraph 强控制
  +
Pydantic 业务契约
  +
FacetExecutionPlan 分发子图
  +
RAG / Tool / Recommendation 可并行
  +
统一 EntityConsistency / GroundedVerifier / ResponseBuilder 汇合
```

Day7 默认切流之后，chat 主入口优先走 compiled graph，legacy `LocalLifeSubgraph.run_stream()` 只保留 fallback。运行态在最终 metrics 中会回填 `graph_runtime` 和 `graph_fallback`，图结构导出可以直接调用 `describe_langgraph_topology()` / `export_langgraph_mermaid()`。

---

# 1. 最终建议总架构图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              用户 / 前端 Chat UI                              │
│                                                                              │
│  示例：                                                                       │
│  - 海底捞水晶城店怎么样？                                                       │
│  - 这家有券吗，现在营业吗，环境怎么样？                                          │
│  - 附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。                         │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Java Chat Stream API                                  │
│                                                                              │
│  POST /api/ai/chat/stream                                                     │
│                                                                              │
│  职责：                                                                        │
│  - 接收用户输入                                                                 │
│  - 透传 session_id / user_id / client_context                                  │
│  - 转发 Python Agent Service                                                   │
│  - 向前端输出 SSE                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Python learning-agent-service                             │
│                                                                              │
│  LocalLifeGraphRunner.stream()                                                │
│                                                                              │
│  默认入口：                                                                    │
│  - compiled_graph.astream(...)                                                 │
│  - compiled_graph.stream(...)                                                  │
│                                                                              │
│  legacy：                                                                      │
│  - LocalLifeSubgraph.run_stream() 只保留 fallback                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           LangGraph StateGraph                                │
│                                                                              │
│  State: LocalLifeGraphState                                                    │
│                                                                              │
│  由 LangGraph 控制：                                                           │
│  - add_node                                                                    │
│  - add_edge                                                                    │
│  - add_conditional_edges                                                       │
│  - compile                                                                     │
│  - checkpoint / trace / replay                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

# 2. MainGraph 主图结构

```text
                                ┌──────────────────────┐
                                │        START         │
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  1. load_context      │
                                │                      │
                                │  读取：               │
                                │  - session            │
                                │  - current_shop       │
                                │  - last_candidates    │
                                │  - user_location      │
                                │  - pending_clarify    │
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  2. understand_query  │
                                │                      │
                                │  - normalize_query    │
                                │  - extract_slots      │
                                │  - UserNeedParser     │
                                │  - ContextArbitration │
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  3. resolve_target    │
                                │                      │
                                │  TargetShopPolicy     │
                                │                      │
                                │  当前轮实体 >          │
                                │  session.current_shop │
                                │                      │
                                │  输出：               │
                                │  - target_shop        │
                                │  - single_shop_mode   │
                                │  - recommendation_mode│
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  4. build_contracts   │
                                │                      │
                                │  - ExecutionContract  │
                                │  - AnswerContract     │
                                │  - FacetExecutionPlan │
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  5. route_review      │
                                │                      │
                                │  复核：               │
                                │  - 是否澄清            │
                                │  - 是否 Tool           │
                                │  - 是否 RAG            │
                                │  - 是否 Recommendation │
                                │  - 是否复合请求         │
                                └───────────┬──────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  6. route_gate        │
                                │                      │
                                │  conditional_edges    │
                                └───────────┬──────────┘
                                            │
        ┌───────────────────────┬───────────┼───────────┬───────────────────────┐
        │                       │           │           │                       │
        ▼                       ▼           ▼           ▼                       ▼
┌──────────────┐      ┌────────────────┐ ┌────────────┐ ┌────────────────┐ ┌──────────────┐
│ clarify      │      │ tool_subgraph  │ │ rag_subgraph│ │ recommendation │ │ direct_answer│
│ subgraph     │      │                │ │             │ │ subgraph       │ │ subgraph     │
└──────┬───────┘      └───────┬────────┘ └──────┬──────┘ └───────┬────────┘ └──────┬───────┘
       │                      │                 │                │                 │
       │                      └────────┬────────┴────────┬───────┘                 │
       │                               │                 │                         │
       │                               ▼                 ▼                         │
       │                    ┌────────────────────────────────────┐                  │
       │                    │  7. result_join / entity_consistency│                  │
       │                    │                                    │                  │
       │                    │  对齐：                             │                  │
       │                    │  - target_shop.shop_id              │                  │
       │                    │  - tool_result.shop_id              │                  │
       │                    │  - evidence.shop_id                 │                  │
       │                    │  - candidate.shop_id                │                  │
       │                    └─────────────────┬──────────────────┘                  │
       │                                      │                                     │
       └──────────────────────┬───────────────┴─────────────────────┬──────────────┘
                              ▼                                     ▼
                  ┌──────────────────────────┐          ┌──────────────────────────┐
                  │  8. fuse_and_rank         │          │ clarify_response_direct  │
                  │                          │          │                          │
                  │  单店：锁死 target_shop    │          │ 澄清卡片直接进入回答       │
                  │  推荐：按 shop_id 分组排序 │          └────────────┬─────────────┘
                  └────────────┬─────────────┘                       │
                               │                                     │
                               ▼                                     │
                  ┌──────────────────────────┐                       │
                  │  9. plan_answer           │                       │
                  │                          │                       │
                  │  AnswerPlanner            │                       │
                  │  只能规划 contract 允许项 │                       │
                  └────────────┬─────────────┘                       │
                               │                                     │
                               ▼                                     │
                  ┌──────────────────────────┐                       │
                  │ 10. verify_grounding      │                       │
                  │                          │                       │
                  │ GroundedVerifier          │                       │
                  │ - 证据校验                 │                       │
                  │ - 券数量校验               │                       │
                  │ - 商铺一致性校验            │                       │
                  └────────────┬─────────────┘                       │
                               │                                     │
                               ▼                                     │
                  ┌──────────────────────────┐                       │
                  │ 11. build_response        │◄──────────────────────┘
                  │                          │
                  │ ResponseBuilder           │
                  │ - coupon_only             │
                  │ - open_status_only        │
                  │ - single_shop_review      │
                  │ - multi_shop_recommend    │
                  │ - clarification           │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ 12. sanitize_response     │
                  │                          │
                  │ 清理：                    │
                  │ - shop:5                  │
                  │ - shop_id                 │
                  │ - open/closed/unknown     │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ 13. persist_context       │
                  │                          │
                  │ 写回：                    │
                  │ - current_shop            │
                  │ - last_candidates         │
                  │ - pending_clarification   │
                  └────────────┬─────────────┘
                               │
                               ▼
                         ┌────────────┐
                         │    END     │
                         └────────────┘
```

---

# 3. GraphState 结构

```text
LocalLifeGraphState
│
├── request
│   ├── raw_query
│   ├── session_id
│   ├── user_id
│   └── client_context
│
├── context
│   ├── persistent_context
│   ├── session.current_shop
│   ├── session.last_candidates
│   ├── user_location
│   └── pending_clarification
│
├── understanding
│   ├── normalized_query
│   ├── semantic_query
│   ├── keyword_query
│   ├── slots
│   └── user_need
│
├── target
│   ├── target_shop
│   ├── target_shop.source
│   ├── single_shop_mode
│   ├── recommendation_mode
│   └── recommendation_count
│
├── contracts
│   ├── execution_contract
│   ├── answer_contract
│   └── facet_execution_plan
│
├── branch_results
│   ├── tool_results
│   ├── rag_results
│   ├── recommendation_results
│   └── facet_result_bundle
│
├── evidence
│   ├── evidence_pack
│   ├── entity_consistency_report
│   └── ranked_candidates
│
├── answer
│   ├── answer_plan
│   ├── verification_result
│   ├── response_bundle
│   └── final_answer
│
└── runtime
    ├── sse_events
    ├── metrics
    ├── errors
    └── trace
```

推荐做法：

```text
GraphState 用 TypedDict
业务对象用 Pydantic
```

也就是：

```text
LangGraph 管流程
Pydantic 管契约
```

---

# 4. 子图一：understand_query

```text
┌────────────────────────────────────────────────────────────┐
│                    understand_query 子图                    │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ raw_query                                                   │
│                                                            │
│ 例：                                                        │
│ - 海底捞水晶城店怎么样？                                     │
│ - 这家有券吗？                                               │
│ - 附近有没有推荐的餐厅？                                     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ normalize_query                                             │
│                                                            │
│ 输出：                                                      │
│ - normalized_query                                          │
│ - semantic_query                                            │
│ - keyword_query                                             │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ extract_slots                                               │
│                                                            │
│ 输出：                                                      │
│ - city                                                      │
│ - location                                                  │
│ - category                                                  │
│ - scene                                                     │
│ - shop_query                                                │
│ - shop_ids                                                  │
│ - user preferences                                          │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ UserNeedParser                                              │
│                                                            │
│ 输出：                                                      │
│ - required_facets                                           │
│ - optional_facets                                           │
│ - forbidden_facets                                          │
│ - constraints                                               │
│                                                            │
│ 注意：                                                      │
│ shop_query 只代表实体，不自动等于 shop_detail                │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ ContextArbitration                                          │
│                                                            │
│ 只补充：                                                    │
│ - 指代实体                                                   │
│ - 用户位置                                                   │
│ - pending clarification                                     │
│                                                            │
│ 禁止：                                                      │
│ - 把上一轮 facet 继承到本轮                                  │
│ - 把上一轮商铺覆盖当前轮显式商铺                              │
└────────────────────────────────────────────────────────────┘
```

---

# 5. 子图二：resolve_target

这是解决你当前“问 A 答 B”“第二个商铺被第一个污染”的关键子图。

```text
┌────────────────────────────────────────────────────────────┐
│                    resolve_target 子图                      │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ detect_current_turn_entity                                  │
│                                                            │
│ 判断当前轮是否显式出现新商铺：                                │
│ - 海底捞水晶城店怎么样？                                      │
│ - 巴奴毛肚火锅有券吗？                                        │
│ - 凑凑火锅现在营业吗？                                        │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ TargetShopPolicy                                            │
│                                                            │
│ 优先级：                                                    │
│ 1. 当前轮显式商铺                                            │
│ 2. 用户选择的候选序号，如“第二家”                              │
│ 3. 指代词 + session.current_shop                              │
│ 4. session.current_shop                                      │
│ 5. RAG top1，仅限 fallback，不得覆盖显式商铺                    │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ mode decision                                                │
│                                                            │
│ if target_shop exists:                                      │
│   single_shop_mode = true                                   │
│                                                            │
│ if required_facets contains recommendation:                 │
│   recommendation_mode = true                                │
│   recommendation_count = 3 / 5 / 1                           │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ output                                                       │
│                                                            │
│ - target_shop                                                │
│ - single_shop_mode                                           │
│ - recommendation_mode                                        │
│ - recommendation_count                                       │
└────────────────────────────────────────────────────────────┘
```

硬规则：

```text
当前轮显式商铺 > session.current_shop > RAG top1
```

---

# 6. 子图三：build_contracts

```text
┌────────────────────────────────────────────────────────────┐
│                    build_contracts 子图                     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ input                                                       │
│                                                            │
│ - user_need.required_facets                                 │
│ - target_shop                                               │
│ - single_shop_mode                                          │
│ - recommendation_mode                                       │
│ - slots                                                     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ ExecutionContract                                           │
│                                                            │
│ 决定怎么执行：                                                │
│ - execute_tools                                              │
│ - execute_rag                                                │
│ - execution_items                                            │
│ - target_shop_id                                             │
│ - recommendation_count                                       │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ FacetExecutionPlan                                          │
│                                                            │
│ coupon       → tool:get_coupon_list                         │
│ open_status  → tool:check_open_status                       │
│ distance_eta → tool:get_distance_eta                        │
│ environment  → rag:single_shop_rag                          │
│ scene_fit    → rag:single_shop_rag                          │
│ recommendation → recommendation_subgraph                    │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ AnswerContract                                              │
│                                                            │
│ 决定最终能答什么：                                            │
│ - allowed_facets                                             │
│ - forbidden_facets                                           │
│ - required_sections                                          │
│ - forbidden_sections                                         │
│ - answer_style                                               │
│                                                            │
│ 例：                                                        │
│ 有券吗？                                                     │
│ allowed = coupon                                             │
│ forbidden = environment / service / recommendation           │
└────────────────────────────────────────────────────────────┘
```

---

# 7. 子图四：tool_subgraph

```text
┌────────────────────────────────────────────────────────────┐
│                     tool_subgraph                           │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ read FacetExecutionPlan                                     │
│                                                            │
│ 可能包含：                                                   │
│ - coupon                                                     │
│ - open_status                                                │
│ - distance_eta                                               │
│ - shop_detail                                                │
└────────────────────────────────────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┬──────────────────────┐
       │                      │                      │                      │
       ▼                      ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌────────────────┐     ┌────────────────┐
│ coupon_tool  │       │ status_tool  │       │ distance_tool  │     │ detail_tool    │
└──────┬───────┘       └──────┬───────┘       └───────┬────────┘     └───────┬────────┘
       │                      │                       │                      │
       ▼                      ▼                       ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌────────────────┐     ┌────────────────┐
│ CouponResult │       │ StatusResult │       │ DistanceResult │     │ DetailResult   │
│              │       │              │       │                │     │                │
│ count 只来自  │       │ 营业中/休息   │       │ 距离/时间       │     │ 基础门店信息    │
│ realtime_tool│       │              │       │                │     │                │
└──────┬───────┘       └──────┬───────┘       └───────┬────────┘     └───────┬────────┘
       │                      │                       │                      │
       └──────────────┬───────┴───────────────┬───────┴──────────────┬───────┘
                      ▼                       ▼                      ▼
              ┌────────────────────────────────────────────────────────┐
              │ FacetResultBundle                                       │
              │                                                        │
              │ results = {                                             │
              │   coupon: CouponResult,                                 │
              │   open_status: StatusResult,                            │
              │   distance_eta: DistanceResult,                         │
              │   shop_detail: DetailResult                             │
              │ }                                                       │
              └────────────────────────────────────────────────────────┘
```

这里可以并行：

```text
coupon_tool
open_status_tool
distance_tool
```

但必须汇合到 `FacetResultBundle`。

---

# 8. 子图五：rag_subgraph

最终建议不要只有一个 RAG，而是拆成：

```text
single_shop_rag
recommendation_rag
```

## 8.1 single_shop_rag

```text
┌────────────────────────────────────────────────────────────┐
│                    single_shop_rag                          │
│                                                            │
│ 用于：                                                      │
│ - 这家怎么样？                                               │
│ - 海底捞水晶城店环境怎么样？                                  │
│ - 它适合约会吗？                                             │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ require target_shop                                         │
│                                                            │
│ single_shop_mode = true                                     │
│ target_shop.shop_id must exist                              │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ build facet query                                           │
│                                                            │
│ environment → 环境 / 氛围 / 安静                              │
│ scene_fit   → 约会 / 聚餐 / 带娃                              │
│ review      → 口味 / 服务 / 总评                              │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ retriever filter                                            │
│                                                            │
│ MUST:                                                       │
│ shop_id == target_shop.shop_id                              │
│                                                            │
│ SHOULD:                                                     │
│ facet == required_facet                                     │
│ chunk_type matched                                          │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ retrieve evidence                                           │
│                                                            │
│ 只允许目标店证据                                              │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ EvidenceScopeGuard                                          │
│                                                            │
│ 再次过滤：                                                   │
│ evidence.shop_id == target_shop.shop_id                     │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ EvidencePack                                                │
│                                                            │
│ 全部证据属于 target_shop                                     │
└────────────────────────────────────────────────────────────┘
```

如果没证据：

```text
说该店信息不足
禁止换另一家店回答
```

---

## 8.2 recommendation_rag

```text
┌────────────────────────────────────────────────────────────┐
│                  recommendation_rag                         │
│                                                            │
│ 用于：                                                      │
│ - 附近有没有推荐的餐厅？                                      │
│ - 附近推荐几家火锅                                           │
│ - 多推荐几家适合约会的店                                      │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ recommendation_mode = true                                  │
│ recommendation_count = 3 / 5 / 1                             │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ build recommendation query                                  │
│                                                            │
│ category = 餐厅 / 火锅                                       │
│ scene = 约会 / 聚餐                                          │
│ location = 附近 / 商圈                                       │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ retrieve topK chunks                                        │
│                                                            │
│ topK = 30 / 50                                              │
│ 不能只取 top3 chunk                                          │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ group by shop_id                                            │
│                                                            │
│ shop A: evidence list                                       │
│ shop B: evidence list                                       │
│ shop C: evidence list                                       │
│                                                            │
│ 防止 topK 都来自同一家店                                      │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ aggregate evidence per shop                                 │
│                                                            │
│ 每家店聚合：                                                 │
│ - 推荐理由                                                   │
│ - 环境                                                       │
│ - 口味                                                       │
│ - 价格                                                       │
│ - 场景适配                                                   │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ rank shop groups                                            │
│                                                            │
│ 输出 topN different shops                                   │
│ 默认 N = 3                                                  │
└────────────────────────────────────────────────────────────┘
```

---

# 9. 子图六：recommendation_subgraph

推荐不是单纯 RAG，它通常会并行走多个来源：

```text
nearby_tool
catalog_search
recommendation_rag
distance_tool
coupon_tool optional
open_status_tool optional
```

```text
┌────────────────────────────────────────────────────────────┐
│                recommendation_subgraph                      │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ parse recommendation_count                                  │
│                                                            │
│ 附近有没有推荐？ → 3 家                                      │
│ 推荐一家       → 1 家                                        │
│ 多推荐几家     → 5 家                                        │
└────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼──────────────────────┬──────────────────────┐
        │                     │                      │                      │
        ▼                     ▼                      ▼                      ▼
┌────────────────┐   ┌────────────────────┐   ┌────────────────┐   ┌────────────────┐
│ nearby_tool    │   │ recommendation_rag │   │ distance_tool  │   │ coupon/status  │
│ 找候选店         │   │ 找推荐证据           │   │ 算距离/耗时      │   │ 可选增强         │
└───────┬────────┘   └─────────┬──────────┘   └───────┬────────┘   └───────┬────────┘
        │                      │                      │                    │
        └──────────────┬───────┴──────────────┬───────┴────────────┬──────┘
                       ▼                      ▼                    ▼
             ┌────────────────────────────────────────────────────────┐
             │ merge by shop_id                                        │
             │                                                        │
             │ 每个 shop 聚合：                                        │
             │ - 基础信息                                               │
             │ - 推荐证据                                               │
             │ - 距离                                                   │
             │ - 券                                                     │
             │ - 营业状态                                               │
             └────────────────────────────────────────────────────────┘
                       │
                       ▼
             ┌────────────────────────────────────────────────────────┐
             │ rank topN shops                                         │
             │                                                        │
             │ 默认返回 3 家                                            │
             └────────────────────────────────────────────────────────┘
```

---

# 10. 复杂请求的并行流转

## 10.1 复杂单店请求

用户：

```text
海底捞水晶城店有券吗，现在营业吗，环境怎么样，适合约会吗？
```

解析：

```text
target_shop = 海底捞水晶城店
single_shop_mode = true

required_facets:
- coupon
- open_status
- environment
- scene_fit
```

流转：

```text
route_gate = rag_plus_tool
  │
  ├────────────── tool_subgraph ──────────────┐
  │                                           │
  │   coupon_tool                             │
  │   open_status_tool                        │
  │                                           │
  ├────────────── single_shop_rag ────────────┤
  │                                           │
  │   environment evidence                    │
  │   scene_fit evidence                      │
  │   filter shop_id = target_shop            │
  │                                           │
  └────────────────── join ───────────────────┘
                      │
                      ▼
              entity_consistency
                      │
                      ▼
              FacetResultBundle
                      │
                      ▼
              AnswerContract
                      │
                      ▼
              ResponseBuilder
```

最终回答结构：

```text
1. 券：……
2. 营业状态：……
3. 环境：……
4. 是否适合约会：……
```

---

## 10.2 复杂多店推荐请求

用户：

```text
附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。
```

解析：

```text
recommendation_mode = true
recommendation_count = 3

required_facets:
- recommendation
- scene_fit
- coupon
- open_status
- distance_eta
```

流转：

```text
route_gate = recommendation
  │
  ▼
recommendation_subgraph
  │
  ├──────── nearby_tool
  │
  ├──────── recommendation_rag
  │          ├─ retrieve topK
  │          ├─ group by shop_id
  │          └─ scene_fit evidence
  │
  ├──────── coupon_tool per candidate
  │
  ├──────── open_status_tool per candidate
  │
  └──────── distance_tool per candidate
  │
  ▼
merge by shop_id
  │
  ▼
rank top3 shops
  │
  ▼
multi_shop_recommendation answer
```

最终回答结构：

```text
附近可以优先看这 3 家：

1. A 店
   - 推荐理由
   - 是否营业
   - 是否有券
   - 为什么适合约会

2. B 店
   ...

3. C 店
   ...
```

---

# 11. Fan-out / Join 并行结构

```text
                         ┌──────────────────────┐
                         │   FacetExecutionPlan  │
                         └───────────┬──────────┘
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       │                             │                             │
       ▼                             ▼                             ▼
┌──────────────┐             ┌──────────────┐             ┌────────────────┐
│ tool branch  │             │ rag branch   │             │ recommend branch│
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘
       │                            │                             │
       ▼                            ▼                             ▼
┌──────────────┐             ┌──────────────┐             ┌────────────────┐
│ ToolResults  │             │ EvidencePack │             │ Recommendation │
│              │             │              │             │ Results        │
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘
       │                            │                             │
       └──────────────┬─────────────┴──────────────┬──────────────┘
                      ▼                            ▼
          ┌──────────────────────────┐   ┌──────────────────────────┐
          │ EntityConsistency         │   │ FacetResultBundle         │
          │                          │   │                          │
          │ shop_id 对齐              │   │ coupon/status/rag/reco    │
          └────────────┬─────────────┘   └────────────┬─────────────┘
                       │                              │
                       └──────────────┬───────────────┘
                                      ▼
                            ┌────────────────────┐
                            │ fuse_and_rank       │
                            └─────────┬──────────┘
                                      ▼
                            ┌────────────────────┐
                            │ verify_grounding    │
                            └─────────┬──────────┘
                                      ▼
                            ┌────────────────────┐
                            │ build_response      │
                            └────────────────────┘
```

---

# 12. 最终推荐的节点注册结构

```text
StateGraph(LocalLifeGraphState)
│
├── load_context
├── understand_query
├── resolve_target
├── build_contracts
├── route_review
├── route_gate
│
├── clarify_subgraph
├── tool_subgraph
├── rag_subgraph
├── recommendation_subgraph
├── direct_answer_subgraph
│
├── entity_consistency
├── fuse_and_rank
├── plan_answer
├── verify_grounding
├── build_response
├── sanitize_response
└── persist_context
```

边：

```text
START
  ↓
load_context
  ↓
understand_query
  ↓
resolve_target
  ↓
build_contracts
  ↓
route_review
  ↓
route_gate
```

conditional edges：

```text
route_gate:
  clarify        → clarify_subgraph
  tool           → tool_subgraph
  rag            → rag_subgraph
  rag_plus_tool  → tool_subgraph + rag_subgraph
  recommendation → recommendation_subgraph
  direct         → direct_answer_subgraph
```

汇合：

```text
clarify_subgraph         → build_response
tool_subgraph            → entity_consistency
rag_subgraph             → entity_consistency
recommendation_subgraph  → entity_consistency
direct_answer_subgraph   → build_response

entity_consistency       → fuse_and_rank
fuse_and_rank            → plan_answer
plan_answer              → verify_grounding
verify_grounding         → build_response
build_response           → sanitize_response
sanitize_response        → persist_context
persist_context          → END
```

---

# 13. 最终一句话架构

```text
用户请求
  ↓
LangGraph MainGraph
  ↓
理解 query，识别 facets
  ↓
锁定 target_shop / recommendation_mode
  ↓
生成 ExecutionContract + AnswerContract
  ↓
按 facets 并行调度 Tool / RAG / Recommendation 子图
  ↓
统一做 entity consistency
  ↓
统一做 evidence fusion / rank
  ↓
GroundedVerifier 校验证据和券数量
  ↓
ResponseBuilder 按 AnswerContract 生成最终回答
  ↓
Sanitizer 清理内部信息
  ↓
PersistContext 写回会话
  ↓
SSE final 返回用户
```

这个就是当前最终建议的架构。
它不是“多个自由 Agent 各自回答”，而是：

```text
一个 LangGraph 主图强控制
多个受控子图并行取证
最终统一汇合生成一个答案
```

