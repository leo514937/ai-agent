是的，你要从 **“route-first 流程”** 改成 **“context / need / plan-first 流程”**。

你现在不要先纠结“是不是多 agent”“是不是 LangGraph”，更核心的是把本地生活项目改成下面这种稳定链路：

```text
用户问题
  ↓
InputQualityCheck
  ↓
ContextAssembler
  ↓
UserNeedParser
  ↓
RequiredFacets
  ↓
RouteReview
  ↓
TaskPlanBuilder
  ↓
RAG Plan + Tool Plan + Memory Plan
  ↓
Execute: RAG / Tool / Business API
  ↓
EntityJoin
  ↓
EvidenceCoverage
  ↓
AnswerContract
  ↓
AnswerComposer
  ↓
AnswerVerifier
  ↓
Final / Partial Answer / Clarify
```

你的项目现在已经有不少能力：README 里写了本地生活、RAG、Toolcall、Memory/Session/Feedback、Java/Python 链路都已经打通；也有四层记忆、父子 RAG、ToolPlanner → ToolExecutor → ToolResultNormalizer 这些基础设施。问题不是“没有能力”，而是这些能力之间缺少强约束对象把它们串起来。([GitHub][1]) ([GitHub][1]) ([GitHub][1]) ([GitHub][1])

---

# 1. 让整个流程更合理：把 route 从“入口决策”降级为“计划复核”

你现在的问题可以概括为：

```text
现在：先 route，再找证据
应该：先理解用户需要哪些 facet，再决定每个 facet 走什么路径
```

本地生活场景里，用户的问题经常是多条件组合，例如：

```text
附近有没有适合约会、现在营业、最好有券的火锅？
```

这个问题不能只 route 成一个 `nearby_recommend` 或 `rag_plus_tool`。它实际包含：

```text
location       -> client_context / business API
category       -> slot / business API
scene_fit      -> RAG
open_status    -> tool / business API
coupon         -> tool / business API
price          -> business API
recommend_reason -> RAG + business facts
```

所以 route 不能太早做最终裁决。你应该改成：

```text
route 不再回答：这轮走 RAG 还是 Tool？
route 只回答：这些 required_facets 分别由什么数据源负责？
```

你仓库里的改进文档其实已经指向这个方向：目标不是推翻 routing、RAG、toolcall、memory、compose_answer，而是在它们之间补上 `UserNeed`、`RequiredFacets`、`TaskPlan`、`EntityJoinResult`、`AnswerContract`、`AnswerVerifier`。([GitHub][2])

## 推荐的新主流程

```text
+----------------------+
| raw user query        |
+----------+-----------+
           |
           v
+----------------------+
| InputQualityCheck     |
| 是否太短/乱码/缺核心槽 |
+----------+-----------+
           |
           v
+----------------------+
| ContextAssembler      |
| 当前 query + client   |
| + session + recent    |
| + profile             |
+----------+-----------+
           |
           v
+----------------------+
| UserNeedParser        |
| 解析 intent / slots   |
| constraints / facets  |
+----------+-----------+
           |
           v
+----------------------+
| RouteReview           |
| 防止 direct/clarify   |
| tool/rag 过早短路     |
+----------+-----------+
           |
           v
+----------------------+
| TaskPlanBuilder       |
| facet -> data source  |
+----------+-----------+
           |
           +--------------------+
           |                    |
           v                    v
+----------------------+  +----------------------+
| RAG Plan              |  | Tool Plan             |
| scene/review/risk     |  | coupon/open/price     |
+----------+-----------+  +----------+-----------+
           |                    |
           +---------+----------+
                     v
+----------------------+
| EntityJoin            |
| 按 shop_id 合并证据    |
+----------+-----------+
           |
           v
+----------------------+
| EvidenceCoverage      |
| 每个 facet 是否有证据  |
+----------+-----------+
           |
           v
+----------------------+
| AnswerContract        |
| 允许说什么/禁止说什么 |
+----------+-----------+
           |
           v
+----------------------+
| AnswerVerifier        |
| 漏答/编造/跨实体检查   |
+----------+-----------+
           |
           v
+----------------------+
| final / partial / clarify |
+----------------------+
```

你当前 `LocalLifeSubgraph.run_stream` 里已经有 `client_context`、`session_context`、`normalize_query`、`extract_slots` 这些步骤，说明入口已经具备上下文准备雏形。([GitHub][3]) 但它现在还不够，因为后面 Qdrant 召回仍然受 `query_route.use_qdrant`、`candidate_shop_ids`、`slots.category`、`city` 等早期结果影响。([GitHub][3])

所以要补的是 **RouteReview + TaskPlanBuilder**。

---

## 你应该新增 4 个核心对象

### A. `UserNeed`

```python
class UserNeed(BaseModel):
    intent: str
    raw_query: str
    resolved_query: str
    slots: LocalLifeSlots
    constraints: dict[str, Any]
    required_facets: list[RequiredFacet]
    optional_facets: list[RequiredFacet]
    missing_slots: list[str]
    context_refs: list[ContextRef]
```

作用：把用户到底要什么表达清楚。

---

### B. `RequiredFacet`

```python
class RequiredFacet(BaseModel):
    name: str
    required: bool
    data_source: Literal[
        "slot",
        "static_rag",
        "dynamic_tool",
        "business_api",
        "memory",
        "client_context",
        "mixed",
    ]
    freshness: Literal["static_ok", "near_realtime_required"]
    entity_keys: list[str]
    missing_policy: Literal[
        "partial_grounded",
        "ask_clarification",
        "no_answer",
    ]
```

例如：

```json
{
  "name": "coupon",
  "required": true,
  "data_source": "dynamic_tool",
  "freshness": "near_realtime_required",
  "entity_keys": ["shop_id", "coupon_id"],
  "missing_policy": "partial_grounded"
}
```

你仓库计划文档里也建议 `required_facets` 不只表示要回答哪些方面，还要声明数据源、是否需要动态工具、是否允许静态 RAG 部分回答。([GitHub][2])

---

### C. `TaskPlan`

```python
class TaskPlan(BaseModel):
    intent: str
    rag_tasks: list[RagTask]
    tool_tasks: list[ToolTask]
    business_tasks: list[BusinessTask]
    memory_tasks: list[MemoryTask]
    clarify_task: ClarifyTask | None
    expected_facets: list[str]
```

作用：让系统不要粗暴地说“走 RAG”或“走 Tool”，而是：

```text
scene_fit -> RAG
open_status -> Tool
coupon -> Tool
distance -> Business API
recent_shop_reference -> Memory
```

---

### D. `AnswerContract`

```python
class AnswerContract(BaseModel):
    user_need: UserNeed
    selected_entities: list[str]
    facet_evidence_map: dict[str, list[Evidence]]
    allowed_unknowns: list[str]
    forbidden_claims: list[str]
    answer_style: str
```

你当前 `build_response_bundle` 已经接收 `slots`、`ranked_candidates`、`evidence_claims`、`route_decision`、`route_reason` 等信息。([GitHub][3]) 但诊断文档指出，compose 层缺少一个明确的 `AnswerContract`，因此容易变成“根据当前结果类型套模板”，而不是检查是否真正回答了原问题。([GitHub][4])

---

# 2. Context harness 怎么做得更好

你的 context harness 目标不是“把所有记忆都塞进 prompt”，而是：

```text
只把当前问题真正需要的上下文，按优先级、证据来源、覆盖范围注入。
```

## 当前 query 必须高于历史 memory

你需要明确上下文优先级：

```text
P0 当前 query 显式约束
P1 client_context：位置、城市、页面、商家 id、套餐 id
P2 本轮解析出的 slots / constraints
P3 recent_entities：最近提到的店、券、套餐
P4 session memory：当前会话偏好
P5 long-term profile：长期偏好
P6 历史对话摘要
```

规则是：

```text
当前 query 明确说了“咖啡店”，历史里哪怕有“海底捞”，也不能把用户带回海底捞。
只有当前 query 出现“它 / 这家 / 刚才那个 / 这个套餐”时，recent_entities 才强参与。
```

你仓库诊断文档也明确写了：memory 可以参与 route review，帮助解决“它 / 这家 / 那个套餐”等指代，但必须经过 `MemoryRelevanceGate`；当前 query 的显式约束优先于历史记忆，新 query 与旧 memory 主题冲突时应降低 memory 权重。([GitHub][4])

## Context harness 应该分成 5 个节点

```text
ContextAssembler
  ↓
ReferenceResolver
  ↓
MemoryRelevanceGate
  ↓
ContextCompressor
  ↓
ContextInjectionPlan
```

### A. `ContextAssembler`

只负责收集，不做判断：

```python
class ContextBundle(BaseModel):
    raw_query: str
    client_context: dict
    session_context: dict
    recent_entities: list[EntityRef]
    user_profile: dict
    history_summary: str | None
```

---

### B. `ReferenceResolver`

专门解决：

```text
它是谁？
这家是哪家？
这个套餐是哪一个？
刚才那个券是哪一个？
附近是哪个位置？
```

输出：

```python
class ReferenceResolution(BaseModel):
    resolved: bool
    refs: list[ResolvedRef]
    missing_refs: list[str]
    confidence: float
```

示例：

```text
用户：那它现在有券吗？
resolved_ref:
  type: shop
  shop_id: 123
  shop_name: 海底捞
  source: recent_entities
  confidence: 0.92
```

---

### C. `MemoryRelevanceGate`

这个节点非常关键。它决定哪些 memory 能进入当前 turn。

```python
class MemoryRelevanceDecision(BaseModel):
    memory_id: str
    relevance_score: float
    use_for: Literal["reference", "preference", "constraint", "ignore"]
    reason: str
    can_override_current_query: bool = False
```

硬规则：

```text
1. memory 不能覆盖当前 query 显式 slot。
2. memory 只能补 missing slot。
3. 如果 current_query 与 memory 的 entity/category/scene 冲突，memory 降权。
4. 指代型 query 才强依赖 recent_entities。
5. 长期偏好只能作为 soft preference，不能替代动态工具结果。
```

你的 README 中已经有冲突规则：session 约束优先于 current profile，current profile 优先于历史长期记忆；旧记忆 supersede 后要避免继续影响召回。([GitHub][1]) 所以你不是从零开始，而是要把这些规则真正接入 route review 和 answer contract。

---

### D. `ContextCompressor`

不要把所有历史塞进模型，压成：

```text
当前任务上下文：
- 用户显式需求：...
- 已解析实体：...
- 已解析位置：...
- 可用偏好：...
- 不可使用历史：...
- 缺失信息：...
```

示例：

```text
Context Summary:
用户当前要找：附近适合约会的火锅店。
显式约束：category=火锅，scene=约会，coupon=希望有券，open_status=现在营业。
位置来源：client_context.city=北京，area=朝阳。
相关历史：用户上轮提到“海底捞”，但当前 query 是泛推荐，不锁定该店。
禁止注入：不要默认围绕海底捞回答。
```

---

### E. `ContextInjectionPlan`

每个上下文片段必须声明用途：

```python
class ContextInjectionItem(BaseModel):
    key: str
    value: str
    source: Literal["query", "client_context", "session", "memory", "profile"]
    use_for: Literal["slot_fill", "reference", "ranking", "answer_style", "do_not_use"]
    priority: int
```

最终 prompt 不是随便拼，而是分区：

```text
[User Explicit Need]
[Resolved References]
[Allowed Memory]
[Business Facts]
[RAG Evidence]
[Unknown / Missing Facets]
[Answer Rules]
```

---

# 3. RAG harness 怎么做得更好

你的 RAG harness 目标不是“召回更多”，而是：

```text
按 facet 召回，按实体聚合，按证据覆盖度验证。
```

你现在已经有父子 RAG：README 里写了 `local_life_hybrid_chunks` 和 `local_life_parent_child_chunks`，父 chunk 是商家/品类/平台规则摘要，child chunk 是检索用证据点，并且 payload 里有 `shop_id`、`category`、`city`、`area`、`is_active`、`is_latest` 等可过滤字段。([GitHub][1]) 这说明底层数据结构方向是对的。

但你的 RAG harness 应该从：

```text
query -> retrieve_local_life_evidence -> merge claims
```

升级成：

```text
RequiredFacets
  -> RetrievalPlan
  -> MultiQuery
  -> Dense / Sparse / Metadata / ParentChild
  -> Fusion
  -> Entity Grouping
  -> Evidence Coverage
  -> Evidence Pack
```

Qdrant 官方文档也建议 hybrid retrieval 可用 dense、sparse、多阶段查询，并通过 RRF/DBSF 进行融合；在没有强评估集和分数先验时，RRF 是更安全的默认方案。([Qdrant][5]) Qdrant 的课程也强调 dense 和 sparse 结果集可能不同，二者分数体系不兼容，需要用 RRF/DBSF 这类融合方式，并且生产系统需要 ground truth、precision/recall/NDCG、用户反馈和 A/B 测试。([Qdrant][6])

---

## RAG harness 的新链路

```text
UserNeed / RequiredFacets
  ↓
RetrievalPlanBuilder
  ↓
QueryRewrite by facet
  ↓
Hybrid Retrieve
  ├─ dense semantic
  ├─ sparse keyword
  ├─ metadata filter
  └─ parent-child expansion
  ↓
RRF / rerank
  ↓
Entity Grouping by shop_id
  ↓
Facet Coverage
  ↓
EvidencePack
```

## `RetrievalPlan` 必须按 facet 生成

```python
class RetrievalPlan(BaseModel):
    semantic_query: str
    keyword_query: str
    facet_queries: list[FacetQuery]
    filters: dict[str, Any]
    candidate_shop_ids: list[int] | None
    retrieval_routes: list[Literal[
        "dense",
        "sparse",
        "metadata",
        "parent_child",
    ]]
    top_k: dict[str, int]
```

示例：

```json
{
  "semantic_query": "适合情侣约会的火锅店 环境 氛围 服务 排队",
  "keyword_query": "约会 火锅 环境 安静 有券 营业",
  "facet_queries": [
    {
      "facet": "scene_fit",
      "query": "适合约会 环境 氛围 情侣 安静"
    },
    {
      "facet": "risk",
      "query": "排队 吵 服务差 踩雷 等位"
    },
    {
      "facet": "recommendation_reason",
      "query": "推荐理由 口碑 菜品 环境 服务"
    }
  ],
  "filters": {
    "city": "北京",
    "category": "火锅",
    "is_active": true,
    "is_latest": true
  }
}
```

---

## 不要只用一个 query 召回所有东西

本地生活不同 facet 应该分别召回：

```text
scene_fit:
  query = "适合约会 环境 氛围 情侣 安静"

risk:
  query = "排队 久等 吵 踩雷 服务差"

family_fit:
  query = "带娃 家庭聚餐 包间 停车"

study_fit:
  query = "安静 插座 WiFi 适合学习"

coupon_value:
  不能只靠 RAG，需要 tool / business API
```

也就是说：

```text
RAG 负责静态体验类证据：
- 环境
- 口碑
- 探店笔记
- 场景适配
- 风险
- 推荐理由

Tool / Business API 负责动态事实：
- 是否营业
- 是否有券
- 券是否可用
- 库存
- 距离
- 排队状态
- 实时价格
```

计划文档也强调，动态 facet 不能只靠静态 RAG 给确定结论；如果 required facet 缺证据，答案必须显式标注边界。([GitHub][2])

---

## RAG 结果必须按 `shop_id` 聚合

你现在最容易出错的地方是跨实体拼接：

```text
A 店的环境
B 店的券
C 店的营业状态
最后合成一个推荐
```

所以 RAG harness 必须增加 `EntityJoinResult`：

```python
class EntityJoinResult(BaseModel):
    shop_id: int
    shop_name: str
    business_facts: list[BusinessFact]
    rag_evidence: list[Evidence]
    tool_results: list[ToolResult]
    covered_facets: list[str]
    missing_facets: list[str]
    entity_consistency_passed: bool
```

硬规则：

```text
1. 最终推荐的每个商家必须有统一 shop_id。
2. RAG evidence、tool result、business facts 必须能 join 到同一个 shop_id。
3. 没有 shop_id 的证据只能作为泛化背景，不能支撑具体商家结论。
4. 动态信息没有 tool result，不允许说死。
```

---

## EvidencePack 要有覆盖度，而不是只有证据列表

```python
class EvidenceCoverage(BaseModel):
    facet: str
    status: Literal["covered", "partial", "missing"]
    source: Literal["rag", "tool", "business_api", "memory", "client_context"]
    evidence_ids: list[str]
    confidence: float
    reason: str
```

示例：

```json
[
  {
    "facet": "scene_fit",
    "status": "covered",
    "source": "rag",
    "confidence": 0.82
  },
  {
    "facet": "coupon",
    "status": "covered",
    "source": "business_api",
    "confidence": 0.95
  },
  {
    "facet": "open_status",
    "status": "missing",
    "source": "tool",
    "confidence": 0.0
  }
]
```

最终回答就可以稳定变成：

```text
可以确定：这家适合约会，因为环境/氛围证据支持。
可以确定：当前查到有券。
暂时不能确定：实时营业状态未成功查询，所以不建议我直接说“现在营业”。
```

这比现在“要么答非所问，要么泛泛澄清”稳定很多。

---

# 4. 三个 harness 的落地优先级

## P0：先修 route 过早问题

新增：

```text
UserNeedParser
RequiredFacets
RouteReview
```

最小改法：

```text
normalize_query / extract_slots 后，不要马上决定最终 route。
先生成 UserNeed，再进行 route_review。
```

RouteReview 只拦截高风险场景：

```text
1. 用户问题包含多个 facet，但 route 只识别出一个 action。
2. 用户问动态信息，但 route 只走 RAG。
3. 用户有“它/这家/这个套餐”，但没有 reference_resolution。
4. 用户明确换主题，但 memory 还在旧实体上。
5. direct_answer 被触发，但 required_facets 没覆盖。
```

---

## P1：补 context harness

新增：

```text
ContextBundle
ReferenceResolution
MemoryRelevanceGate
ContextInjectionPlan
```

验收用例：

```text
第一轮：海底捞怎么样？
第二轮：那它现在有券吗？
期望：识别“它”=海底捞，调用券工具，不回答成整体评价。
```

你的计划文档里也把这个作为上下文指代测试：第二轮“那它现在有券吗？”应识别“它”指代海底捞，并调用券工具。([GitHub][2])

---

## P2：补 RAG harness

新增：

```text
RetrievalPlanBuilder
FacetQuery
EntityJoinResult
EvidenceCoverage
```

验收用例：

```text
用户：附近有没有适合约会、现在营业、最好有券的火锅？
期望：
- scene_fit 走 RAG
- open_status 走 tool
- coupon 走 tool
- category/location 走 slot/client/business API
- 最终答案按 shop_id 聚合
```

你的计划文档中也有类似测试集，并要求解析出 `location / category / scene_fit / open_status / coupon / recommendation_reason`。([GitHub][2])

---

## P3：补 AnswerContract + AnswerVerifier

新增：

```text
AnswerContract
AnswerVerifier
```

Verifier 第一版用规则就行：

```text
1. required_facets 是否覆盖？
2. 动态 facet 是否来自 tool/business API？
3. 是否跨实体拼接？
4. 是否把 missing facet 编成确定事实？
5. 是否用了被 MemoryRelevanceGate 禁止的历史上下文？
6. 是否泛澄清，而不是最小澄清？
```

你的计划文档也列了这些质量指标：是否覆盖 `required_facets`、是否跨实体拼接、动态信息是否来自 tool result、是否把动态 facet 当成静态证据回答、是否触发实体一致性拦截等。([GitHub][2])

---

# 5. 是否要改成 LangGraph？

可以，但不是第一优先级。

你现在真正缺的是状态契约，不是单纯缺 graph 框架。LangGraph 的价值在于显式状态、节点、checkpoint、trace 和恢复。官方文档说明，Graph API 适合用图结构定义 workflow，并且能可视化，方便调试和共享；Persistence 会在每一步保存 checkpoint，用于 memory、time travel debugging、fault tolerance。([LangChain文档][7]) ([LangChain文档][8])

所以我的建议是：

```text
第一步：先在现有 LocalLifeSubgraph 里补状态对象和阶段。
第二步：等 UserNeed / TaskPlan / EntityJoin / AnswerContract 稳定后，再迁移成 LangGraph StateGraph。
```

不要一上来重构成大图，否则你会把“业务理解问题”和“框架迁移问题”混在一起。

---

# 6. 最终建议：你应该按这个阶段改

```text
阶段 1：流程止血
- normalize_query 后新增 UserNeedParser
- route 前新增 RouteReview
- 不允许 route 过早 direct / clarify / only_rag / only_tool
- required_facets 成为后续所有模块输入

阶段 2：Context harness
- 新增 ContextBundle
- 新增 ReferenceResolver
- 新增 MemoryRelevanceGate
- 当前 query 显式约束 > client_context > session > profile > history

阶段 3：RAG harness
- 新增 RetrievalPlanBuilder
- 按 facet 生成 query
- dense + sparse + metadata + parent-child
- 按 shop_id 聚合证据
- 输出 EvidenceCoverage

阶段 4：Answer harness
- 新增 AnswerContract
- response_builder 只能基于 contract 生成
- AnswerVerifier 做规则校验
- 不通过则 partial answer / clarify / no_answer

阶段 5：可观测与测试
- 每轮记录 UserNeed
- 每轮记录 required_facets
- 每个 facet 记录 data_source / freshness / missing_policy
- 记录 route_review 前后变化
- 记录 memory 注入原因
- 记录 retrieval/tool 失败原因
- 记录 verifier 结果
```

你的核心改造方向就是这一句：

```text
不要让 route 决定答案路径；
让 UserNeed + RequiredFacets 决定路径，
让 TaskPlan 执行路径，
让 EvidenceCoverage 判断是否足够，
让 AnswerContract 约束最终回答。
```

这样改完后，本地生活项目会从：

```text
模块都能跑，但结果靠碰运气
```

变成：

```text
每一步都知道自己服务哪个用户需求，最终答案有证据、有边界、可追踪。
```

