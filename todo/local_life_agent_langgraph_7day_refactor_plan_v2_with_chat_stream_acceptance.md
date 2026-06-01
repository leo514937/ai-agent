# 本地生活 Agent 完整改造计划：问题修复 + LangGraph 图结构迁移 Day0-Day7

> 目标：结合当前两个设计文档与代码仓库现状，给出一版可直接交给 Codex / Claude Code 执行的完整改动方案。
>
> 核心目标：
>
> 1. 每天都有可验证进展。
> 2. 每天任务完成后，都能通过真实 Chat 接口证明修复效果。
> 3. 先彻底解决当前 5 个真实问题。
> 4. 再逐步把当前 `LocalLifeSubgraph.run_stream()` 的顺序工作流，迁移为真正由 LangGraph `StateGraph` 控制的图结构。
> 5. 最终达到：核心节点由 LangGraph 注册、边由 LangGraph 控制、分支由 conditional edges 控制、状态由统一 GraphState 管理、Chat 接口走 compiled graph。

---

## 0. 当前判断

当前本地生活 Agent 的状态可以概括为：

```text
有图式编排思想，但不是完整 LangGraph 编排。
```

当前代码已经有很多“节点感”模块：

```text
normalize_query
extract_slots
UserNeedParser
ContextArbitration
LocalLifeQueryRouter
RouteReview
EntityResolver
RAG
Tool
EvidenceScopeGuard
Fusion / Rank
AnswerPlanner
GroundedVerifier
ResponseBuilder
AnswerSanitizer
PersistContext
```

但当前很多模块不是通过：

```text
StateGraph(...)
add_node(...)
add_edge(...)
add_conditional_edges(...)
compile(...)
```

注册和运行，而是由：

```text
LocalLifeSubgraph.run_stream()
```

手动顺序调用、手动维护状态、手动 if/else 分支、手动 yield SSE。

因此，当前架构应称为：

```text
Subgraph-like Sequential Workflow
```

而不是：

```text
LangGraph StateGraph Orchestration
```

---

## 1. 当前必须解决的 5 个真实问题

当前真实问题是：

```text
1. 用户提供一个商铺，问这个商铺怎么样，系统没有识别到目标商铺，却回答了另一个商铺。
2. 用户先提供一个商铺，再提供第二个商铺，询问第二个商铺的信息，系统却沿用了第一个商铺的信息。
3. RAG 召回总是召回不相关商铺。
4. 优惠券查询数量一直出问题。
5. 回答过于谨慎。用户问附近有没有推荐的餐厅，只推荐一个，而且只有一个商铺的信息。
```

这 5 个问题不是单纯 prompt 问题，而是下面这条链路没有做硬：

```text
current_query_entity
  ↓
target_shop
  ↓
single_shop_mode / recommendation_mode
  ↓
entity-aware RAG / tool query
  ↓
FacetResultBundle
  ↓
AnswerContract
  ↓
ResponseBuilder
```

---

## 2. 总体改造路线

不能直接 Day0 就把所有逻辑重写成 LangGraph，否则很容易：

```text
旧问题没修完
新图结构又引入新 bug
Chat 接口不可用
SSE 事件不兼容
```

正确路线是：

```text
阶段一：先修业务正确性
阶段二：把业务节点稳定成函数式 node
阶段三：用 LangGraph 包装这些稳定 node
阶段四：切换 Chat 接口到 compiled graph
阶段五：删除旧的手写 run_stream 主路径
```

整体路线：

```text
Day0：基线冻结 + Chat E2E 测试框架
Day1：target_shop + 当前轮实体覆盖历史实体
Day2：AnswerContract + ResponseBuilder 强约束
Day3：多工具执行 + CouponResult 标准化
Day4：single_shop_rag / recommendation_rag + 多商铺推荐
Day5：LangGraph State / Node 化，不改变业务行为
Day6：LangGraph conditional edges + 子图接入，Chat 接口灰度切换
Day7：默认走 LangGraph compiled graph，旧 run_stream 降级为 fallback
```

---

## 3. 优先级总表：P0 / P1 / P2 / P3

| 优先级 | 目标 | 解决问题 | 完成标志 |
|---|---|---|---|
| P0 | 目标商铺锁定、上下文覆盖、回答契约、Chat 测试 | 问 A 答 B、第二个商铺被第一个污染、问券答环境 | Chat 接口单店、多轮、券、营业测试通过 |
| P1 | 多工具、CouponResult、RAG 实体过滤、多商铺推荐 | RAG 召回错店、券数量错、附近推荐只给一个 | Chat 接口 RAG、Coupon、Recommendation 测试通过 |
| P2 | LangGraph State / Node / Edge 化 | 当前不是 LangGraph 控制 | compiled graph 能跑通全部 golden cases |
| P3 | 默认切换到 LangGraph，旧链路 fallback，checkpointer/trace | 完整迁移 | Chat 接口默认走 LangGraph，旧 run_stream 不再是主路径 |

---

# 4. P0：必须先修的内容

## 4.1 P0-1：TargetShopPolicy

### 涉及文件

```text
learning-agent-service/src/learning_agent_service/local_life/user_need_parser.py
learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
```

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/target_shop_policy.py
```

### 目标

新增 `TargetShop` 概念：

```python
class TargetShop(BaseModel):
    shop_id: int | None = None
    shop_name: str | None = None
    raw_mention: str | None = None
    source: Literal[
        "current_query",
        "pronoun_session",
        "candidate_selection",
        "session",
        "rag_fallback"
    ]
    confidence: float = 0.0
    is_explicit_in_current_turn: bool = False
    candidate_shop_ids: list[int] = []
```

### 硬规则

```text
当前轮显式商铺 > 用户选择序号 > 指代词 + session > session.current_shop > RAG top1
```

禁止：

```text
RAG top1 覆盖当前轮显式商铺
session.current_shop 覆盖当前轮显式商铺
ranked_candidates[0] 覆盖 target_shop
```

### 直接修复的问题

```text
问题 1：问 A 店却答 B 店
问题 2：第二个商铺被第一个商铺污染
```

---

## 4.2 P0-2：UserNeedParser 修复 shop_detail 误触发

### 当前错误

当前逻辑中存在类似风险：

```python
has_detail_query = any(k in normalized_query for k in DETAIL_KEYWORDS) \
    or slots.shop_query is not None \
    or len(slots.shop_ids) > 0
```

这会把：

```text
海底捞有券吗？
```

误解析成：

```text
coupon + shop_detail
```

### 修改要求

改成：

```python
has_explicit_entity = slots.shop_query is not None or len(slots.shop_ids) > 0

if has_explicit_entity:
    entity_refs.append(...)

has_detail_query = any(k in normalized_query for k in DETAIL_KEYWORDS)
if has_detail_query:
    required_facets.append("shop_detail")
```

### 验收

```text
海底捞有券吗？
required_facets = ["coupon"]
不能包含 shop_detail
```

---

## 4.3 P0-3：AnswerContract

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/answer_contract.py
```

核心结构：

```python
class AnswerContract(BaseModel):
    allowed_facets: list[str]
    forbidden_facets: list[str]
    required_sections: list[str]
    forbidden_sections: list[str] = []
    allowed_cards: list[str] = []
    forbidden_cards: list[str] = []
    answer_style: Literal[
        "coupon_only",
        "open_status_only",
        "distance_only",
        "single_shop_review",
        "multi_shop_recommendation",
        "comparison",
        "clarification"
    ]
    missing_info_policy: Literal[
        "say_unknown",
        "ask_clarify",
        "partial_answer"
    ]
```

### 规则

```text
coupon-only：
  只允许 coupon
  禁止 environment / taste / service / recommendation / scene_fit

open-status-only：
  只允许 open_status
  禁止推荐、环境、口味

single-shop-review：
  允许 general_review / taste / environment / service / price

multi-shop-recommendation：
  默认允许输出 3 个不同商铺
```

---

## 4.4 P0-4：ResponseBuilder 强约束

修改：

```text
response_builder.py
```

要求：

```text
所有输出必须受 AnswerContract 控制。
所有 fallback 也必须受 AnswerContract 控制。
最终文本输出前必须做 contract validation。
```

新增专用模板：

```text
build_coupon_only_answer
build_open_status_only_answer
build_distance_only_answer
build_single_shop_review_answer
build_multi_shop_recommendation_answer
build_clarification_answer
```

---

## 4.5 P0-5：Chat 接口 Golden Test

新增：

```text
learning-agent-service/tests/local_life/test_chat_contract_cases.py
learning-agent-service/tests/local_life/chat_test_client.py
learning-agent-service/tests/local_life/golden_cases/local_life_chat_cases.yaml
```

必须通过：

```text
POST /api/ai/chat/stream
```

而不是只测 Python 函数。

---

# 5. P1：RAG / Tool / Coupon / 推荐修复

## 5.1 P1-1：FacetExecutionPlan + 多工具执行

当前 `RouteReview` 可以生成多个工具，但执行层容易只执行第一个：

```python
tool_name = execution_requirements.execute_tools[0]
```

必须改为：

```python
for item in execution_contract.execution_items:
    execute tool by facet
```

新增：

```python
class FacetExecutionItem(BaseModel):
    facet: str
    source: Literal["tool", "rag", "tool_plus_rag", "context"]
    tool_name: str | None = None
    retrieval_mode: str | None = None
    required: bool = True


class FacetResultBundle(BaseModel):
    results: dict[str, FacetResult]
```

---

## 5.2 P1-2：CouponResult 标准化

新增：

```python
class CouponResult(BaseModel):
    shop_id: int
    realtime_available_count: int
    realtime_total_count: int
    items: list[CouponItem]
    query_success: bool
    source: Literal["realtime_tool", "fallback", "rag_history"]
```

规则：

```text
最终答案中的券数量只能来自 realtime_available_count。
RAG 历史套餐不能计入实时券数量。
无 target_shop 时必须澄清。
```

---

## 5.3 P1-3：single_shop_rag

单店问题必须：

```text
RAG filter: shop_id == target_shop.shop_id
```

如果没有目标店证据：

```text
回答该店信息不足
不得换另一家店回答
```

---

## 5.4 P1-4：recommendation_rag

推荐问题必须：

```text
retrieve topK chunks
  ↓
group by shop_id
  ↓
rank shop groups
  ↓
返回 topN shops
```

默认：

```text
附近有没有推荐的餐厅？ → 3 家
附近推荐一家餐厅 → 1 家
附近多推荐几家餐厅 → 5 家
```

---

# 6. P2：LangGraph 化第一阶段

P2 的目标不是马上删除旧逻辑，而是把稳定业务节点包装为 LangGraph nodes。

## 6.1 新增文件结构

建议新增目录：

```text
learning-agent-service/src/learning_agent_service/local_life/graph/
```

新增文件：

```text
graph/state.py
graph/nodes.py
graph/edges.py
graph/builder.py
graph/runner.py
graph/events.py
graph/adapters.py
```

---

## 6.2 GraphState

```python
class LocalLifeGraphState(TypedDict, total=False):
    command: ChatTurnCommand
    persistent_context: dict
    client_context: dict

    raw_query: str
    understanding: dict
    slots: dict
    user_need: dict
    clarification: dict

    target_shop: dict
    single_shop_mode: bool
    recommendation_mode: bool
    recommendation_count: int

    execution_contract: dict
    answer_contract: dict

    facet_results: dict
    evidence_pack: dict
    ranked_candidates: list

    answer_plan: dict
    verification_result: dict
    response_bundle: dict

    sse_events: list[dict]
    metrics: dict
    errors: list[dict]
```

---

## 6.3 LangGraph 节点

第一批节点：

```text
load_context
understand_query
resolve_target
build_contracts
route_gate
clarify
execute_tools
retrieve_evidence
entity_consistency
fuse_and_rank
plan_answer
verify_grounding
build_response
sanitize_response
persist_context
finalize
```

每个 node 必须是：

```python
def node_name(state: LocalLifeGraphState) -> Partial[LocalLifeGraphState]:
    ...
```

---

## 6.4 Conditional Edges

```text
route_gate
  ├── clarify
  ├── execute_tools
  ├── retrieve_evidence
  ├── rag_plus_tool
  └── build_response
```

条件函数：

```python
def route_decider(state: LocalLifeGraphState) -> str:
    if state["clarification"]["need_clarification"]:
        return "clarify"
    if execute_tools and execute_rag:
        return "rag_plus_tool"
    if execute_tools:
        return "execute_tools"
    if execute_rag:
        return "retrieve_evidence"
    return "build_response"
```

---

## 6.5 SSE 兼容

LangGraph node 内不要直接 yield SSE。

建议做法：

```text
node 返回 sse_events append
runner 统一把 sse_events 转成 SseEnvelope yield
```

这样可以兼容旧前端。

---

# 7. P3：LangGraph 完整切换

P3 目标：

```text
Chat 接口默认走 compiled graph。
旧 LocalLifeSubgraph.run_stream 只作为 fallback。
```

新增 feature flag：

```text
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

切换逻辑：

```python
if settings.local_life_use_langgraph:
    yield from LocalLifeGraphRunner.stream(...)
else:
    yield from LocalLifeSubgraph.run_stream(...)
```

最终 Day7 后目标：

```text
local_life_use_langgraph 默认 true
legacy run_stream 仅用于 emergency fallback
```

---

# 8. Day0-Day7 每日计划

---

## Day0：基线冻结 + Chat E2E 测试框架

### 目标

先不大改业务逻辑，建立测试基线。

### 任务

```text
1. 新增 chat_test_client.py，支持调用 /api/ai/chat/stream。
2. 新增 SSE parser，能解析 delta / final / error / tool_call / tool_result。
3. 新增 golden_cases.yaml。
4. 增加当前 5 个问题的 failing tests。
5. 记录当前失败快照。
```

### 文件

```text
learning-agent-service/tests/local_life/chat_test_client.py
learning-agent-service/tests/local_life/test_chat_contract_cases.py
learning-agent-service/tests/local_life/golden_cases/local_life_chat_cases.yaml
```

### 必须包含的测试

```text
A1 海底捞水晶城店怎么样？不得答其他店
B1 海底捞后问巴奴，第二轮不得答海底捞
C1 单店 RAG evidence shop_id 必须一致
D1 这家有几张券？数量必须来自 tool
E1 附近有没有推荐的餐厅？默认至少 3 家
```

### Day0 完成标准

```text
测试框架可运行。
当前问题有可复现失败用例。
不要求全部通过。
```

---

## Day1：target_shop 锁定 + 当前轮实体覆盖历史实体

### 目标

彻底解决：

```text
问题 1：问 A 店却答 B 店
问题 2：第二个商铺被第一个污染
```

### 任务

```text
1. 新增 target_shop_policy.py。
2. EntityResolver 输出 target_shop。
3. 当前轮显式实体优先于 session.current_shop。
4. 只有“这家/它/刚才那个”才继承 session.current_shop。
5. ResponseBuilder 的回答主体改为 target_shop。
6. PersistContext 中 current_shop 只在 target_shop 明确时更新。
```

### 涉及文件

```text
user_need_parser.py
entity_resolver.py
target_shop_policy.py
subgraph.py
response_builder.py
```

### Chat 验收

```text
海底捞水晶城店怎么样？ → 只能答海底捞水晶城店
海底捞后问巴奴 → 第二轮必须答巴奴
海底捞后问“它有券吗？” → 可以继承海底捞，但只答券
```

### Day1 完成标准

```text
A 组、B 组 Chat 测试通过。
target_shop trace 可见。
single_shop_mode trace 可见。
```

---

## Day2：AnswerContract + ResponseBuilder 强约束

### 目标

彻底解决：

```text
问券答环境
问营业答推荐
上下文 facet 泄漏
```

### 任务

```text
1. 新增 answer_contract.py。
2. 根据 user_need + target_shop + route 生成 AnswerContract。
3. ResponseBuilder 所有入口接收 answer_contract。
4. coupon_only / open_status_only / distance_only / single_shop_review / recommendation 拆模板。
5. 增加 contract validation。
6. AnswerPlanner prompt 也必须接收 contract。
```

### 涉及文件

```text
answer_contract.py
response_builder.py
answer_planner.py
subgraph.py
```

### Chat 验收

```text
有券吗？不得出现环境/口味/服务/推荐
这家营业吗？不得出现推荐/口味/环境
这家怎么样？允许综合评价
第一轮问环境，第二轮问有券吗，第二轮只答券
```

### Day2 完成标准

```text
P0 Chat contract tests 全部通过。
```

---

## Day3：多工具执行 + CouponResult 标准化

### 目标

彻底解决：

```text
问题 4：优惠券查询数量错误
多 facet 只执行一个工具
```

### 任务

```text
1. ExecutionContract 升级为 FacetExecutionPlan。
2. subgraph 执行层从 execute_tools[0] 改为遍历 execution_items。
3. 新增 FacetResultBundle。
4. 新增 CouponResult / CouponItem。
5. ResponseBuilder 券数量只读 CouponResult.realtime_available_count。
6. GroundedVerifier 校验回答中的券数量。
```

### 涉及文件

```text
execution_contract.py
route_review.py
subgraph.py
coupon_result.py
grounded_verifier.py
response_builder.py
```

### Chat 验收

```text
这家有券吗，现在营业吗？ → 同时执行 coupon/open_status
这家有几张券？ → 数量等于 CouponResult.realtime_available_count
实时无券但 RAG 有套餐 → 说实时未查到，不报券数量
无 target_shop 问“有券吗？” → 澄清是哪家
```

### Day3 完成标准

```text
D 组 Coupon 测试通过。
multi-dynamic 工具测试通过。
```

---

## Day4：single_shop_rag + recommendation_rag

### 目标

彻底解决：

```text
问题 3：RAG 召回不相关商铺
问题 5：附近推荐只给一个
```

### 任务

```text
1. RAG 分为 single_shop_rag 和 recommendation_rag。
2. single_shop_rag 必须按 shop_id 强过滤。
3. EvidenceScopeGuard 单店模式下丢弃非 target_shop 证据。
4. recommendation_rag topK 后按 shop_id 分组。
5. recommendation_count 默认 3。
6. ResponseBuilder 推荐类输出 topN 商铺列表。
```

### 涉及文件

```text
subgraph.py
evidence_scope_guard.py
fusion.py
ranker.py
response_builder.py
route_review.py
user_need_parser.py
```

### Chat 验收

```text
海底捞水晶城店环境怎么样？ → evidence 全部属于 target_shop
巴奴毛肚火锅有啥特色？ → 不混入海底捞
附近有没有推荐的餐厅？ → 默认至少 3 家不同商铺
附近推荐一家餐厅 → 只推荐 1 家
附近多推荐几家餐厅 → 推荐约 5 家
```

### Day4 完成标准

```text
C 组 RAG 测试通过。
E 组 Recommendation 测试通过。
5 个真实问题全部从 Chat 接口验证通过。
```

---

## Day5：LangGraph State / Node 化，不改变业务行为

### 目标

开始真正迁移 LangGraph，但不改变业务结果。

### 任务

新增：

```text
local_life/graph/state.py
local_life/graph/nodes.py
local_life/graph/edges.py
local_life/graph/builder.py
local_life/graph/runner.py
local_life/graph/events.py
```

实现第一版节点：

```text
load_context
understand_query
resolve_target
build_contracts
route_review
```

要求：

```text
1. 这些 node 内部先复用 Day1-Day4 已稳定函数。
2. 不重写业务逻辑。
3. 新增 feature flag：LOCAL_LIFE_USE_LANGGRAPH=false。
4. 新增 graph.invoke 单元测试。
```

### LangGraph 结构

```python
builder = StateGraph(LocalLifeGraphState)

builder.add_node("load_context", load_context)
builder.add_node("understand_query", understand_query)
builder.add_node("resolve_target", resolve_target)
builder.add_node("build_contracts", build_contracts)
builder.add_node("route_review", route_review)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "understand_query")
builder.add_edge("understand_query", "resolve_target")
builder.add_edge("resolve_target", "build_contracts")
builder.add_edge("build_contracts", "route_review")
```

### Chat 验收

```text
LOCAL_LIFE_USE_LANGGRAPH=false 时，所有 Day0-Day4 测试仍通过。
graph.invoke 单测能产生 target_shop / answer_contract / execution_contract。
```

### Day5 完成标准

```text
LangGraph skeleton 可 compile。
前半段节点由 LangGraph 控制。
旧 Chat 行为无回归。
```

---

## Day6：LangGraph conditional edges + 子图接入，Chat 灰度切换

### 目标

让核心分支由 LangGraph 控制。

### 任务

接入节点：

```text
clarify
execute_tools
retrieve_evidence
rag_plus_tool
entity_consistency
fuse_and_rank
plan_answer
verify_grounding
build_response
sanitize_response
persist_context
finalize
```

新增 conditional edge：

```python
builder.add_conditional_edges(
    "route_review",
    route_decider,
    {
        "clarify": "clarify",
        "tool": "execute_tools",
        "rag": "retrieve_evidence",
        "rag_plus_tool": "rag_plus_tool",
        "direct": "build_response",
    },
)
```

新增 feature flag：

```text
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

Chat 接口：

```python
if settings.local_life_use_langgraph:
    yield from LocalLifeGraphRunner.stream(...)
else:
    yield from LocalLifeSubgraph.run_stream(...)
```

### SSE 兼容

LangGraph node 不直接 yield SSE，而是往 state 写：

```python
state["sse_events"].append(...)
```

Runner 统一转成 `SseEnvelope`。

### Chat 验收

```text
开启 LOCAL_LIFE_USE_LANGGRAPH=true 后：
A/B/C/D/E 全部 Chat tests 通过。
SSE 事件仍包含 final / tool_call / retrieval_started。
出错时 fallback legacy。
```

### Day6 完成标准

```text
Chat 接口可以灰度走 LangGraph compiled graph。
核心 branch 由 conditional edges 控制。
```

---

## Day7：默认切换 LangGraph，旧 run_stream 降级 fallback

### 目标

彻底过渡为 LangGraph 控制的图结构。

### 任务

```text
1. LOCAL_LIFE_USE_LANGGRAPH 默认 true。
2. LocalLifeSubgraph.run_stream 不再作为主路径。
3. 保留 legacy fallback，但所有新增测试必须走 LangGraph。
4. 补充 graph 可视化 / Mermaid / ASCII 输出。
5. 补充 README / ARCHITECTURE 说明。
6. 增加 LangGraph compiled graph smoke tests。
7. 增加 Chat E2E CI 脚本。
```

### 完整目标图

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
  ├── clarify
  ├── execute_tools
  ├── retrieve_evidence
  └── rag_plus_tool
        ↓
entity_consistency
  ↓
fuse_and_rank
  ↓
plan_answer
  ↓
verify_grounding
  ↓
build_response
  ↓
sanitize_response
  ↓
persist_context
  ↓
END
```

### Day7 完成标准

```text
1. Chat 接口默认走 LangGraph。
2. A/B/C/D/E 全部 golden tests 通过。
3. P0/P1/P2/P3 smoke tests 通过。
4. run_stream legacy 只作为 fallback。
5. graph.get_graph 或等价导出可展示节点/边。
6. 文档明确：当前已由 LangGraph StateGraph 控制主流程。
```

---

# 9. 每天验收矩阵

| Day | 主要目标 | 必须通过的测试 | 是否解决当前问题 |
|---|---|---|---|
| Day0 | 建立测试基线 | 测试能跑，失败可复现 | 尚未解决，但可度量 |
| Day1 | target_shop / 多轮实体覆盖 | A/B 组通过 | 解决问题 1、2 |
| Day2 | AnswerContract / ResponseBuilder | coupon/open/status/context tests 通过 | 解决问券答环境、问营业答推荐 |
| Day3 | 多工具 / CouponResult | D 组通过 | 解决问题 4 |
| Day4 | RAG 实体过滤 / 多店推荐 | C/E 组通过 | 解决问题 3、5；五大问题全部解决 |
| Day5 | LangGraph 前半段 node 化 | graph compile + legacy tests 通过 | 开始迁移 |
| Day6 | LangGraph 分支和核心子图接入 | LangGraph Chat tests 全部通过 | 大部分由 LangGraph 控制 |
| Day7 | 默认切换 LangGraph | 全量 Chat + graph smoke 通过 | 完成架构迁移 |

---

# 10. 最终完成定义

完成 Day7 后，必须满足：

```text
业务正确性：
- 问 A 店只答 A 店。
- 第二轮显式新商铺覆盖第一轮。
- 单店 RAG 只用目标店证据。
- 优惠券数量只来自实时 CouponResult。
- 附近推荐默认输出 3 家不同商铺。
- 问券不答环境，问营业不答推荐。

架构正确性：
- 主流程由 LangGraph StateGraph 构建。
- 节点通过 add_node 注册。
- 边通过 add_edge 注册。
- 分支通过 add_conditional_edges 控制。
- compiled graph 是 Chat 主路径。
- legacy run_stream 只是 fallback。

测试正确性：
- 所有关键用例从 /api/ai/chat/stream 触发。
- 解析 SSE final/delta。
- 测试最终用户可见文本。
- 测试 trace 中 target_shop / answer_contract / execution_contract / evidence / coupon_result。
```

---

# 11. 给 Codex / Claude Code 的总执行提示词

```text
你是资深 Python / FastAPI / LangGraph / RAG / Agent Workflow 工程实现代理。请按本计划对本地生活 Agent 做 7 天式分阶段改造。要求如下：

1. 不要只写计划，必须实际修改代码。
2. 每一天必须有可运行、可验收的改动。
3. 所有关键问题必须通过真实 Chat 接口 /api/ai/chat/stream 测试，不允许只做单元测试。
4. Day0 先建立 Chat E2E 测试框架和 failing golden cases。
5. Day1 必须实现 target_shop，当前轮显式商铺必须覆盖 session.current_shop 和 RAG top1。
6. Day2 必须实现 AnswerContract，ResponseBuilder 所有输出必须受 contract 控制。
7. Day3 必须实现 FacetExecutionPlan、多工具执行和 CouponResult 标准化。
8. Day4 必须实现 single_shop_rag / recommendation_rag，推荐默认返回 3 家不同商铺。
9. Day5 开始 LangGraph 迁移，先把稳定业务函数包装成 StateGraph node，不改变行为。
10. Day6 用 conditional edges 接入 clarify/tool/rag/rag_plus_tool 分支，并让 Chat 接口可灰度走 compiled graph。
11. Day7 默认切换到 LangGraph compiled graph，legacy run_stream 只保留 fallback。
12. 修改完成后每天输出：
    - 改动文件列表
    - 已完成节点
    - Chat 测试结果
    - 未完成风险
    - 下一天任务
13. 最终必须保证：五个真实问题全部解决，并且本地生活主流程由 LangGraph StateGraph 控制。
```

---

# 12. 风险和注意事项

## 12.1 不要 Day0 直接重写成 LangGraph

原因：

```text
当前最大风险是业务正确性，不是图形式。
如果 target_shop、CouponResult、RAG filter 没修，迁移到 LangGraph 后还是会错。
```

## 12.2 LangGraph 迁移必须复用稳定函数

不要在 Day5 重写业务逻辑。

正确做法：

```text
Day1-Day4 修业务函数
Day5-Day7 把这些函数包成 LangGraph node
```

## 12.3 Chat 接口测试必须作为唯一最终验收

单元测试可以辅助，但不能代替：

```text
POST /api/ai/chat/stream
```

最终验收看用户可见答案。

---

# 13. 最终结论

这次改造的核心不是“把代码形式上塞进 LangGraph”，而是：

```text
先把 target_shop / AnswerContract / RAG filter / CouponResult / multi-shop recommendation 做硬，
再把稳定节点迁移进 LangGraph StateGraph。
```

最终目标：

```text
业务上：
  彻底解决当前 5 个真实问题。

架构上：
  从 LocalLifeSubgraph.run_stream 手写顺序工作流，
  迁移为 LangGraph StateGraph 控制的显式图结构。

测试上：
  每天都有 Chat 接口可验证进展。
```

---

# 14. 同步新增：改动量评估与最终建议架构落地策略

> 本章节把“改成最终建议 LangGraph 架构图，改动到底大不大、怎么落地”同步进本文档。
>
> 结论：这是一次 **中大型改造**，但不是推倒重写。业务模块可以大量复用，主要改动集中在编排层、状态流转、RAG/Tool/Response 边界、Chat 接口验收测试。

---

## 14.1 改动量总体判断

如果只是把当前流程“画成 LangGraph 图”，改动不大；但如果要真正达到下面效果，改动较大：

```text
主流程由 LangGraph StateGraph 控制
节点通过 add_node 注册
边通过 add_edge 注册
分支通过 add_conditional_edges 控制
复杂请求可按 facet 分发到 Tool / RAG / Recommendation 子图
所有分支结果统一汇合到 EntityConsistency / GroundedVerifier / ResponseBuilder
Chat 接口默认走 compiled graph
旧 LocalLifeSubgraph.run_stream 只保留 fallback
```

改造性质：

```text
业务代码：复用 60% - 70%
编排层：重构 70% - 80%
状态流转：重构 50% - 60%
测试体系：需要大补
```

---

## 14.2 最大改动点一：subgraph.py 主编排职责拆分

当前：

```text
LocalLifeSubgraph.run_stream()
  ├── load_context
  ├── normalize_query
  ├── extract_slots
  ├── UserNeedParser
  ├── RouteReview
  ├── EntityResolver
  ├── if/elif route branch
  ├── RAG / Tool
  ├── ResponseBuilder
  ├── sanitize
  └── yield SSE
```

目标：

```text
local_life/graph/
  ├── state.py
  ├── nodes.py
  ├── edges.py
  ├── builder.py
  ├── runner.py
  ├── events.py
  └── adapters.py
```

职责拆分：

```text
builder.py
  构建 StateGraph，注册 add_node / add_edge / add_conditional_edges / compile

nodes.py
  包装现有业务模块为 LangGraph node

runner.py
  执行 compiled_graph.stream / astream，并转换为 SSE

events.py
  统一 SSE event envelope

adapters.py
  负责 Pydantic 业务对象与 GraphState dict 互转
```

---

## 14.3 最大改动点二：状态从 TurnState 过渡到 GraphState

当前更像：

```text
Pydantic LocalLifeTurnState
  被 run_stream 手动创建
  被 run_stream 手动修改
  不是 LangGraph StateGraph 管理的统一 state
```

目标新增：

```python
class LocalLifeGraphState(TypedDict, total=False):
    raw_query: str
    session_id: str
    user_id: str
    client_context: dict
    persistent_context: dict

    understanding: dict
    slots: dict
    user_need: dict
    clarification: dict

    target_shop: dict
    single_shop_mode: bool
    recommendation_mode: bool
    recommendation_count: int

    execution_contract: dict
    answer_contract: dict
    facet_execution_plan: dict

    tool_results: dict
    rag_results: dict
    recommendation_results: dict
    facet_result_bundle: dict

    evidence_pack: dict
    entity_consistency_report: dict
    ranked_candidates: list

    answer_plan: dict
    verification_result: dict
    response_bundle: dict
    final_answer: str

    sse_events: list[dict]
    metrics: dict
    errors: list[dict]
```

推荐原则：

```text
GraphState 用 TypedDict 做图状态骨架
业务对象继续用 Pydantic 做强校验
```

也就是：

```text
LangGraph 管流程
Pydantic 管契约
```

---

## 14.4 最大改动点三：路由从 Python if/elif 改成 conditional edges

当前：

```python
if need_clarification:
    ...
elif execute_rag and execute_tools:
    ...
elif execute_tools:
    ...
elif execute_rag:
    ...
else:
    ...
```

目标：

```python
builder.add_conditional_edges(
    "route_gate",
    route_decider,
    {
        "clarify": "clarify_subgraph",
        "tool": "tool_subgraph",
        "rag": "rag_subgraph",
        "rag_plus_tool": "rag_plus_tool_subgraph",
        "recommendation": "recommendation_subgraph",
        "direct": "direct_answer_subgraph",
    },
)
```

Day6 如果难以实现真正并行，`rag_plus_tool` 可以先做顺序子图：

```text
rag_plus_tool_subgraph:
  execute_tools
  retrieve_evidence
  result_join
```

Day7 以后再优化成更细粒度 fan-out / join。

---

## 14.5 可以复用的模块

下面模块不建议重写，应先包装成 LangGraph node：

```text
normalize_query
extract_slots
UserNeedParser
ContextArbitration
RouteReview
EntityResolver
EvidenceScopeGuard
fusion
ranker
AnswerPlanner
GroundedVerifier
ResponseBuilder
AnswerSanitizer
```

包装方式：

```python
def understand_query_node(state: LocalLifeGraphState) -> dict:
    understanding = normalize_query(...)
    slots = extract_slots(...)
    user_need = UserNeedParser.parse(...)
    return {
        "understanding": understanding.model_dump(),
        "slots": slots.model_dump(),
        "user_need": user_need.model_dump(),
    }
```

---

## 14.6 必须新增或重构的模块

必须新增：

```text
target_shop_policy.py
answer_contract.py
coupon_result.py
facet_execution_plan.py
entity_consistency.py
local_life/graph/state.py
local_life/graph/nodes.py
local_life/graph/edges.py
local_life/graph/builder.py
local_life/graph/runner.py
local_life/graph/events.py
local_life/graph/adapters.py
```

必须重构：

```text
subgraph.py
response_builder.py
route_review.py
entity_resolver.py
evidence_scope_guard.py
fusion.py
ranker.py
grounded_verifier.py
```

---

## 14.7 推荐分阶段落地

```text
阶段一：业务正确性先做硬
  target_shop / AnswerContract / CouponResult / single_shop_rag / recommendation_rag / multi_tool_execution

阶段二：节点包装
  把稳定函数包装为 LangGraph node，不重写业务逻辑，不改变 Chat 输出

阶段三：分支接管
  route_gate 改为 conditional_edges，tool / rag / recommendation 分支由 LangGraph 控制

阶段四：主入口切换
  /api/ai/chat/stream 默认走 compiled_graph，LocalLifeSubgraph.run_stream 只保留 fallback
```

---

# 15. 每日 /api/ai/chat/stream 验收测试用例与预期结果

> 所有关键改动都必须通过真实接口验收：
>
> ```text
> POST /api/ai/chat/stream
> ```
>
> 不允许只测单元函数。测试必须解析 SSE 中的 `delta / final / error / tool_call / tool_result / retrieval_started / retrieval_result / state_update 或 metrics`。

---

## 15.1 通用 Chat 测试客户端要求

建议新增：

```text
learning-agent-service/tests/local_life/chat_test_client.py
```

最小能力：

```python
class ChatStreamTestClient:
    def post_message(
        self,
        message: str,
        session_id: str,
        user_id: str = "test-user",
        extra_payload: dict | None = None,
    ) -> ChatStreamResult:
        ...

class ChatStreamResult(BaseModel):
    final_answer: str
    delta_text: str
    events: list[dict]
    tool_calls: list[dict]
    tool_results: list[dict]
    retrieval_events: list[dict]
    metrics: dict
    error_events: list[dict]
```

所有测试通用断言：

```python
assert result.error_events == []
assert result.final_answer.strip()
assert "Traceback" not in result.final_answer
assert "shop:" not in result.final_answer
assert "shop_id" not in result.final_answer
assert "execution_contract" not in result.final_answer
assert "rag_plus_tool" not in result.final_answer
```

---

## 15.2 Day0：建立失败基线

### 测试文件

```text
learning-agent-service/tests/local_life/test_day0_chat_baseline.py
```

### 目标

Day0 不要求全部通过，但必须能稳定复现当前 5 个问题，并输出失败快照。

### Case D0-1：单店识别基线

请求：

```bash
curl -N -X POST "http://localhost:8080/api/ai/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"day0-single-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}'
```

预期：

```text
当前可能失败，但测试必须能捕获：
- 如果回答主体不是海底捞水晶城店，记录失败。
- 如果出现其他商铺名称，记录失败。
```

断言：

```python
assert "海底捞" in answer or "水晶城" in answer
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
```

### Case D0-2：多轮商铺污染基线

第一轮：

```json
{"sessionId":"day0-switch-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

第二轮：

```json
{"sessionId":"day0-switch-shop-001","userId":"test-user","message":"巴奴毛肚火锅怎么样？"}
```

预期：

```text
当前可能失败；如果第二轮继续回答海底捞，测试必须标记失败。
```

断言：

```python
assert "巴奴" in answer2
assert "海底捞水晶城" not in answer2
```

### Case D0-3：RAG 错店基线

```json
{"sessionId":"day0-rag-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

预期：

```text
记录 retrieval_result 中 evidence.shop_id 是否全部属于目标店。
最终答案不得混入其他店。
```

### Case D0-4：优惠券数量基线

```json
{"sessionId":"day0-coupon-001","userId":"test-user","message":"海底捞水晶城店有几张券？"}
```

预期：

```text
记录 tool_result 中券数量与 final_answer 中提到的券数量，两者不一致则失败。
```

### Case D0-5：附近推荐基线

```json
{"sessionId":"day0-reco-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
记录最终答案中的不同商铺数量。如果少于 3 家，标记为当前待修复问题。
```

### Day0 完成标准

```text
1. Chat E2E 测试框架可运行。
2. 5 个问题至少有 failing case 或 baseline snapshot。
3. 每个失败都打印 session_id、message、final_answer、SSE events、tool_calls、tool_results、retrieval_results、metrics/trace。
```

---

## 15.3 Day1：target_shop 与多轮实体覆盖

### 测试文件

```text
learning-agent-service/tests/local_life/test_day1_target_shop_chat.py
```

### Case D1-1：显式单店评价

```json
{"sessionId":"day1-single-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
最终答案围绕海底捞水晶城店，不得把其他店作为主体。
如果证据不足，必须说该店信息不足，不得换店。
trace 中 target_shop.source = current_query，single_shop_mode = true。
```

断言：

```python
assert "海底捞" in answer or "水晶城" in answer
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
assert_trace_value(result, "target_shop.source", "current_query")
assert_trace_value(result, "single_shop_mode", True)
```

### Case D1-2：多轮显式新商铺覆盖旧商铺

第一轮：

```json
{"sessionId":"day1-switch-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

第二轮：

```json
{"sessionId":"day1-switch-shop-001","userId":"test-user","message":"巴奴毛肚火锅怎么样？"}
```

预期：

```text
第二轮必须围绕巴奴毛肚火锅，不得继续回答海底捞。
trace 中 target_shop.source = current_query。
```

断言：

```python
assert "巴奴" in answer2
assert "海底捞水晶城" not in answer2
assert_trace_value(result2, "target_shop.source", "current_query")
```

### Case D1-3：指代词可以继承旧商铺

第一轮：

```json
{"sessionId":"day1-pronoun-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

第二轮：

```json
{"sessionId":"day1-pronoun-001","userId":"test-user","message":"它有券吗？"}
```

预期：

```text
第二轮可以继承海底捞水晶城店，但 required_facets 必须是 coupon。
不得继续回答环境/综合评价。
```

断言：

```python
assert "券" in answer2 or "优惠" in answer2
assert "环境" not in answer2
assert "口味" not in answer2
assert "服务" not in answer2
assert_trace_value(result2, "target_shop.source", "pronoun_session")
```

### Day1 完成标准

```text
D1-1 / D1-2 / D1-3 全部通过。
target_shop trace 可见。
single_shop_mode trace 可见。
```

---

## 15.4 Day2：AnswerContract 与 ResponseBuilder

### 测试文件

```text
learning-agent-service/tests/local_life/test_day2_answer_contract_chat.py
```

### Case D2-1：coupon-only 不得答环境

```json
{"sessionId":"day2-coupon-only-001","userId":"test-user","message":"海底捞水晶城店有券吗？"}
```

预期：

```text
只回答券/优惠相关信息。
不得出现环境、氛围、口味、服务、推荐、适合聚餐等内容。
```

断言：

```python
assert_any_in(answer, ["券", "优惠", "暂无", "实时"])
assert_all_not_in(answer, ["环境", "氛围", "口味", "服务", "推荐", "适合"])
assert_trace_contains(result, "answer_contract.allowed_facets", "coupon")
assert_trace_contains(result, "answer_contract.forbidden_facets", "environment")
```

### Case D2-2：open-status-only 不得答推荐

```json
{"sessionId":"day2-open-001","userId":"test-user","message":"海底捞水晶城店现在营业吗？"}
```

预期：

```text
只回答营业状态或无法确认，不主动补口味、环境、推荐理由。
```

断言：

```python
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
assert_all_not_in(answer, ["环境", "口味", "服务", "推荐", "适合"])
```

### Case D2-3：general-review 可以综合回答

```json
{"sessionId":"day2-review-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
可以综合回答口味、环境、服务、价格等，但必须围绕目标店。
```

断言：

```python
assert_any_in(answer, ["整体", "评价", "环境", "口味", "服务", "价格"])
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
```

### Case D2-4：多轮上下文只继承实体，不继承 facet

第一轮：

```json
{"sessionId":"day2-context-facet-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

第二轮：

```json
{"sessionId":"day2-context-facet-001","userId":"test-user","message":"有券吗？"}
```

预期：

```text
第二轮继承目标店，但只回答券，不继续回答环境。
```

断言：

```python
assert_any_in(answer2, ["券", "优惠", "暂无", "实时"])
assert_all_not_in(answer2, ["环境", "氛围", "口味", "服务", "适合"])
```

### Day2 完成标准

```text
D2-1 / D2-2 / D2-3 / D2-4 全部通过。
answer_contract trace 可见。
ResponseBuilder 不再绕过 contract。
```

---

## 15.5 Day3：多工具执行与 CouponResult

### 测试文件

```text
learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py
```

### Case D3-1：coupon + open_status 双工具执行

```json
{"sessionId":"day3-multi-tool-001","userId":"test-user","message":"海底捞水晶城店有券吗，现在营业吗？"}
```

预期：

```text
至少执行 coupon_tool 和 open_status_tool。
最终答案同时回答券和营业状态。
```

断言：

```python
assert_tool_called(result, "coupon")
assert_tool_called(result, "open_status")
assert_any_in(answer, ["券", "优惠", "暂无"])
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
```

### Case D3-2：券数量一致

```json
{"sessionId":"day3-coupon-count-001","userId":"test-user","message":"海底捞水晶城店有几张券？"}
```

预期：

```text
如果最终答案提到具体数量，该数量必须等于 CouponResult.realtime_available_count。
```

断言：

```python
coupon_count = extract_coupon_result_count(result)
mentioned_count = extract_mentioned_coupon_count(answer)
if mentioned_count is not None:
    assert mentioned_count == coupon_count
```

### Case D3-3：实时无券但 RAG 有历史套餐

```json
{"sessionId":"day3-coupon-history-001","userId":"test-user","message":"海底捞水晶城店有没有可用优惠券？"}
```

预期：

```text
如果 realtime_available_count = 0：
回答“实时接口未查到当前可用券”。
如果 RAG 有历史套餐，只能说“历史描述需以实时接口为准”。
不得把历史套餐算成实时券数量。
```

断言：

```python
if extract_coupon_result_count(result) == 0:
    assert_any_in(answer, ["实时", "未查到", "暂无"])
    assert "有 1 张" not in answer
    assert "有 2 张" not in answer
```

### Case D3-4：无 target_shop 时问券必须澄清

```json
{"sessionId":"day3-no-target-coupon-001","userId":"test-user","message":"有券吗？"}
```

预期：

```text
如果 session 无 current_shop，必须澄清是哪家店，不得随机查询某个店。
```

断言：

```python
assert_any_in(answer, ["哪家", "哪一家", "具体门店", "想查"])
assert_tool_not_called(result, "coupon")
```

### Day3 完成标准

```text
D3-1 / D3-2 / D3-3 / D3-4 全部通过。
FacetResultBundle trace 可见。
CouponResult trace 可见。
```

---

## 15.6 Day4：single_shop_rag / recommendation_rag

### 测试文件

```text
learning-agent-service/tests/local_life/test_day4_rag_recommendation_chat.py
```

### Case D4-1：single_shop_rag evidence 全部属于目标店

```json
{"sessionId":"day4-single-rag-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

预期：

```text
RAG evidence 必须全部属于目标店。
最终答案不得混入其他商铺。
```

断言：

```python
assert_trace_value(result, "single_shop_mode", True)
assert_all_evidence_shop_id_equals_target(result)
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
```

### Case D4-2：第二家店 RAG 不混入第一家店

第一轮：

```json
{"sessionId":"day4-rag-switch-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

第二轮：

```json
{"sessionId":"day4-rag-switch-001","userId":"test-user","message":"巴奴毛肚火锅有啥特色？"}
```

预期：

```text
第二轮 RAG evidence 不得混入海底捞。
最终答案围绕巴奴。
```

断言：

```python
assert "巴奴" in answer2
assert "海底捞水晶城" not in answer2
assert_all_evidence_not_shop_name(result2, "海底捞")
```

### Case D4-3：附近推荐默认 3 家

```json
{"sessionId":"day4-reco-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
默认推荐至少 3 家不同商铺。
如果数据不足，trace 必须显示 candidate_count < 3。
```

断言：

```python
shop_names = extract_shop_names(answer)
if len(shop_names) < 3:
    assert_trace_less_than(result, "recommendation.candidate_count", 3)
else:
    assert len(set(shop_names)) >= 3
```

### Case D4-4：用户明确推荐一家

```json
{"sessionId":"day4-reco-one-001","userId":"test-user","message":"附近推荐一家餐厅"}
```

预期：

```text
可以只推荐 1 家，但必须有推荐理由。
```

断言：

```python
shop_names = extract_shop_names(answer)
assert len(set(shop_names)) == 1
assert_any_in(answer, ["推荐理由", "因为", "适合", "优点"])
```

### Case D4-5：多推荐几家

```json
{"sessionId":"day4-reco-many-001","userId":"test-user","message":"附近多推荐几家餐厅"}
```

预期：

```text
推荐 5 家左右。
如果数据不足，trace 必须说明 candidate_count。
```

断言：

```python
shop_names = extract_shop_names(answer)
if len(shop_names) < 5:
    assert_trace_less_than(result, "recommendation.candidate_count", 5)
else:
    assert len(set(shop_names)) >= 5
```

### Day4 完成标准

```text
D4-1 / D4-2 / D4-3 / D4-4 / D4-5 全部通过。
5 个真实业务问题全部通过 Chat 接口验证。
```

---

## 15.7 Day5：LangGraph State / Node 化但不改变行为

### 测试文件

```text
learning-agent-service/tests/local_life/test_day5_langgraph_skeleton_chat.py
```

### 环境变量

```bash
LOCAL_LIFE_USE_LANGGRAPH=false
```

### Case D5-1：legacy 路径无回归

```json
{"sessionId":"day5-legacy-regression-001","userId":"test-user","message":"海底捞水晶城店有券吗，现在营业吗？"}
```

预期：

```text
在 LOCAL_LIFE_USE_LANGGRAPH=false 下，Day1-Day4 所有 Chat 测试仍通过。
```

断言：

```python
assert_day1_to_day4_suite_passes()
```

### Case D5-2：graph.invoke 产生关键状态

直接调用 graph 单测，不替代 Chat 测试：

```python
state = graph.invoke({
    "raw_query": "海底捞水晶城店有券吗？",
    "session_id": "day5-graph-state-001",
    "user_id": "test-user",
})
```

预期：

```text
能产生 user_need、target_shop、answer_contract、execution_contract。
```

断言：

```python
assert state["target_shop"]["source"] == "current_query"
assert "coupon" in state["user_need"]["required_facets"]
assert "coupon" in state["answer_contract"]["allowed_facets"]
```

### Case D5-3：Chat 输出和 Day4 行为一致

```json
{"sessionId":"day5-chat-regression-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
仍默认推荐 3 家，说明 Day5 的 LangGraph skeleton 没破坏旧路径。
```

断言：

```python
assert_recommendation_default_count(answer, result, expected=3)
```

### Day5 完成标准

```text
1. LangGraph builder 可 compile。
2. graph.invoke 单测通过。
3. LOCAL_LIFE_USE_LANGGRAPH=false 时 Day1-Day4 Chat 测试无回归。
```

---

## 15.8 Day6：LangGraph conditional edges + 灰度切换

### 测试文件

```text
learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py
```

### 环境变量

```bash
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

### Case D6-1：LangGraph 单店请求

```json
{"sessionId":"day6-lg-single-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
Chat 接口走 LangGraph。
最终答案围绕目标店。
trace 中 graph_path 包含 load_context → understand_query → resolve_target → build_contracts → route_review → rag_subgraph → entity_consistency → build_response。
```

断言：

```python
assert_trace_contains_path(result, [
    "load_context",
    "understand_query",
    "resolve_target",
    "build_contracts",
    "route_review",
])
assert "海底捞" in answer or "水晶城" in answer
```

### Case D6-2：LangGraph tool 分支

```json
{"sessionId":"day6-lg-tool-001","userId":"test-user","message":"海底捞水晶城店有券吗，现在营业吗？"}
```

预期：

```text
route_gate 进入 tool 或 rag_plus_tool 分支。
SSE 仍输出 tool_call/tool_result。
最终答案同时包含券和营业状态。
```

断言：

```python
assert_tool_called(result, "coupon")
assert_tool_called(result, "open_status")
assert_any_in(answer, ["券", "优惠", "暂无"])
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
```

### Case D6-3：LangGraph recommendation 分支

```json
{"sessionId":"day6-lg-reco-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
route_gate 进入 recommendation_subgraph。
默认推荐 3 家。
```

断言：

```python
assert_trace_contains(result, "route_decision", "recommendation")
assert_recommendation_default_count(answer, result, expected=3)
```

### Case D6-4：fallback legacy 可用

测试配置：

```bash
LOCAL_LIFE_FORCE_GRAPH_ERROR=true
```

请求：

```json
{"sessionId":"day6-lg-fallback-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
Graph 出错时 fallback legacy。
用户仍能获得 final answer 或可理解错误。
不得直接 Traceback。
```

断言：

```python
assert "Traceback" not in answer
assert result.final_answer or assert_user_friendly_error(result)
assert_trace_contains(result, "fallback", "legacy")
```

### Day6 完成标准

```text
1. LOCAL_LIFE_USE_LANGGRAPH=true 下 A/B/C/D/E 全部 Chat tests 通过。
2. SSE 事件兼容旧前端。
3. conditional edges trace 可见。
4. fallback legacy 可用。
```

---

## 15.9 Day7：默认切换 LangGraph compiled graph

### 测试文件

```text
learning-agent-service/tests/local_life/test_day7_langgraph_default_chat.py
```

### 环境变量

```bash
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

并且默认配置：

```text
LOCAL_LIFE_USE_LANGGRAPH 默认 true
```

### Case D7-1：全量 golden cases 默认走 LangGraph

执行：

```bash
pytest learning-agent-service/tests/local_life/test_chat_contract_cases.py
```

预期：

```text
所有 Day1-Day6 Chat golden cases 通过。
trace 中 graph_runtime = langgraph。
```

断言：

```python
assert_all_golden_cases_pass()
assert_trace_value(result, "graph_runtime", "langgraph")
```

### Case D7-2：复杂单店复合请求

```json
{
  "sessionId": "day7-complex-single-001",
  "userId": "test-user",
  "message": "海底捞水晶城店有券吗，现在营业吗，环境怎么样，适合约会吗？"
}
```

预期：

```text
同时回答：
- 券
- 营业状态
- 环境
- 是否适合约会

Tool 分支处理券/营业。
single_shop_rag 处理环境/场景。
所有 evidence/tool_result 必须属于 target_shop。
```

断言：

```python
assert_tool_called(result, "coupon")
assert_tool_called(result, "open_status")
assert_trace_contains(result, "single_shop_mode", True)
assert_all_evidence_shop_id_equals_target(result)

assert_any_in(answer, ["券", "优惠", "暂无"])
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
assert_any_in(answer, ["环境", "氛围", "安静", "空间"])
assert_any_in(answer, ["约会", "适合", "不太适合"])
```

### Case D7-3：复杂多店推荐请求

```json
{
  "sessionId": "day7-complex-reco-001",
  "userId": "test-user",
  "message": "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
}
```

预期：

```text
进入 recommendation_subgraph。
默认推荐 3 家不同商铺。
每家店尽量包含推荐理由、是否适合约会、是否有券或券查询结果、是否营业或营业状态。
```

断言：

```python
assert_trace_contains(result, "recommendation_mode", True)
assert_recommendation_default_count(answer, result, expected=3)
assert_any_in(answer, ["约会", "适合"])
assert_any_in(answer, ["券", "优惠", "暂无", "实时"])
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
```

### Case D7-4：图结构 smoke test

测试代码：

```python
graph = build_local_life_graph()
compiled = graph.compile()
graph_repr = compiled.get_graph()

assert graph_repr is not None
assert_node_exists(graph_repr, "load_context")
assert_node_exists(graph_repr, "understand_query")
assert_node_exists(graph_repr, "resolve_target")
assert_node_exists(graph_repr, "route_gate")
assert_node_exists(graph_repr, "build_response")
```

预期：

```text
可以导出或打印图结构。
文档中能展示节点和边。
```

### Day7 完成标准

```text
1. Chat 接口默认走 LangGraph compiled graph。
2. 全量 golden cases 通过。
3. 复杂单店请求通过。
4. 复杂多店推荐请求通过。
5. 图结构 smoke test 通过。
6. legacy run_stream 仅作为 fallback。
7. README / ARCHITECTURE 已更新。
```

---

# 16. 每天验收测试总表

| Day | 必须新增/运行的 Chat 测试文件 | 关键用例 | 预期结果 |
|---|---|---|---|
| Day0 | test_day0_chat_baseline.py | A/B/C/D/E baseline | 能复现当前失败 |
| Day1 | test_day1_target_shop_chat.py | 单店、多轮切换、指代继承 | target_shop 正确 |
| Day2 | test_day2_answer_contract_chat.py | coupon-only、open-only、review、多轮 facet | 回答受 AnswerContract 控制 |
| Day3 | test_day3_tools_coupon_chat.py | 多工具、券数量、无 target_shop 澄清 | FacetResultBundle / CouponResult 正确 |
| Day4 | test_day4_rag_recommendation_chat.py | single_shop_rag、recommendation_rag | RAG 不错店，推荐多家 |
| Day5 | test_day5_langgraph_skeleton_chat.py | legacy regression + graph.invoke | Graph skeleton 可编译，无回归 |
| Day6 | test_day6_langgraph_chat_stream.py | LangGraph 单店/tool/reco/fallback | conditional edges 可用 |
| Day7 | test_day7_langgraph_default_chat.py | 全量 golden + 复杂请求 + graph smoke | 默认走 LangGraph |

---

# 17. Codex / Claude Code 增补执行提示词

```text
请在现有 local_life_agent_langgraph_7day_refactor_plan.md 基础上同步补充改动量评估和每天 Chat 接口验收测试。

额外硬性要求：
1. 每一天都必须新增或更新 /api/ai/chat/stream 端到端测试。
2. 每一天都必须写清楚输入 message、session_id、预期 final_answer、预期 trace/metrics。
3. 不允许只写单元测试。
4. Day0 必须建立 failing baseline。
5. Day1 必须验证 target_shop 和多轮商铺覆盖。
6. Day2 必须验证 AnswerContract 限制最终回答。
7. Day3 必须验证多工具执行和 CouponResult 数量一致。
8. Day4 必须验证 single_shop_rag 强过滤和 recommendation_rag 默认 3 家。
9. Day5 必须验证 LangGraph skeleton compile，同时旧 Chat 行为无回归。
10. Day6 必须验证 LOCAL_LIFE_USE_LANGGRAPH=true 后 Chat 接口走 compiled graph，并保留 fallback。
11. Day7 必须验证默认走 LangGraph，复杂单店请求和复杂多店推荐请求都通过。
12. 每个测试失败时必须打印：
    - session_id
    - message
    - final_answer
    - all SSE events
    - tool_calls
    - tool_results
    - retrieval_results
    - trace / metrics
```

---

# 18. 最终补充结论

改成最终建议架构，改动是中大型，但不是推倒重写。

最稳路线是：

```text
Day0：先把 Chat 测试建起来
Day1-Day4：先把业务不变量做硬
Day5-Day7：再把稳定节点迁移到 LangGraph StateGraph
```

最终必须同时满足：

```text
业务正确：
  不错店、不串上下文、不乱召回、不数错券、不只推荐一家。

架构正确：
  主流程由 LangGraph StateGraph 控制。

测试正确：
  每天都有真实 /api/ai/chat/stream 验收测试和预期结果。
```


预期架构：
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

