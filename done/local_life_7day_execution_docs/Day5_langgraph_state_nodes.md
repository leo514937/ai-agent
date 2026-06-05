# Day5：LangGraph State / Node 化，不改变业务行为

> 来源：根据上传的 `local_life_agent_langgraph_7day_refactor_plan_v2_with_chat_stream_acceptance(1).md` 拆分整理。
>
> 总原则：
>
> - 每天都必须有 `/api/ai/chat/stream` 用户视角验收。
> - 每天都必须写清楚：参考架构、修改优先级、改动范围、验收输入、预期输出、完成标准。
> - Day1-Day4 先把业务不变量做硬；Day5-Day7 再把稳定节点迁移进 LangGraph。
> - 不允许只做单元测试；单元测试只能辅助，最终验收看 Chat 接口最终用户可见结果。


---

## 1. 当天目标

```text
1. 新建 local_life/graph/ 目录。
2. 定义 LocalLifeGraphState。
3. 把 Day1-Day4 已稳定的业务函数包装成 LangGraph nodes。
4. 第一版 graph skeleton 能 compile。
5. 不改变 Chat 行为，不默认切换主链路。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P2 | LocalLifeGraphState | 迁移 LangGraph 的状态基础 |
| P2 | graph/builder.py | StateGraph 构建入口 |
| P2 | graph/nodes.py | 包装稳定业务节点 |
| P2 | graph/runner.py 草案 | 后续 Day6 接 Chat |
| P1 | Day1-Day4 回归测试 | 防止图壳影响业务 |
| P3 | graph smoke test | 验证节点存在和 compile |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day5 聚焦部分高亮)

```text
=======================【Day5 已注册并完全接管的前半段图结构】=======================
START
  │
  ▼
┌────────────────────────┐
│ [load_context]         │ ==> [Day5 新建节点] 加载会话和 client 上下文
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [understand_query]     │ ==> [Day5 新建节点] 语义理解与 Slot 槽位抽取
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [resolve_target]       │ ==> [Day5 新建节点] 实体绑定并锁定 target_shop
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [build_contracts]      │ ==> [Day5 新建节点] 生成执行与回答契约 (AnswerContract)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [route_review]         │ ==> [Day5 新建节点] 分流决策复核
└────────────────────────┘
           │
===========【Day5 尚未接入的后半段业务与汇合链路（仍走 Legacy 或单元仿真模拟）】===========
           ▼
     ┌───────────┐
     │route_gate │
     └─────┬─────┘
           ├──────────────────────┬──────────────────────┐
           ▼                      ▼                      ▼
     ┌───────────┐          ┌───────────┐          ┌───────────┐
     │ no_rag    │          │ single_rag│          │ reco_rag  │
     └─────┬─────┘          └─────┬─────┘          └─────┬─────┘
           └──────────────────────┼──────────────────────┘
                                  ▼
                    ┌──────────────────────────┐
                    │ EntityConsistency 对齐   │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ ResponseBuilder 强输出    │
                    └──────────────────────────┘
```

### 3.2 当天要完成的架构链路与流转关系

在 Day5 阶段，我们开启了**核心图框架编排的迁移**。我们专注于将 Day1-Day4 已沉淀、且历经测试检验的稳定业务函数，以完美的无副作用（不破坏原 Chat API）方式迁入到真正的 `LangGraph` Node 与 Edge 结构中。

当天核心打通并锁定的链路流转关系如下：
```text
【START】
   │
   ▼
[load_context]        ==> 输入: GraphState, 输出: {"persistent_context": ..., "client_context": ...}
   │
   ▼
[understand_query]    ==> 调用原有语义分析，往 State 写入 {"understanding": ..., "slots": ..., "user_need": ...}
   │
   ▼
[resolve_target]      ==> 触发 Day1 核心策略，产出并写入 {"target_shop": ..., "single_shop_mode": ...}
   │
   ▼
[build_contracts]     ==> 触发 Day2-Day3 核心契约，产出并写入 {"answer_contract": ..., "execution_contract": ...}
   │
   ▼
[route_review]        ==> 完成路由判断决策。
   │
   ▼
【compile & invoke】 ==> 验证整段图结构前半段 100% 连通，Graph 内部状态传递完美无损。
```

> [!IMPORTANT]
> **切流控制与安全隔离**：
> - 此时主 Chat API 接口仍默认关闭 LangGraph 切流标志（`LOCAL_LIFE_USE_LANGGRAPH=false`），保证线上业务没有任何变更风险。
> - 在旁路中，我们新增 `test_day5_langgraph_skeleton_chat.py` 进行 `graph.invoke` 的单元集成和状态验证。
> - 在本阶段，我们将 `GraphState`（面向 LangGraph 编排的 TypedDict 数据字典）与 `Pydantic`（面向业务强校验的实体契约）进行了完美解耦绑定：**“LangGraph 管图流转，Pydantic 管业务契约”**。

---

## 4. 需要修改/新增的文件

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/graph/__init__.py
learning-agent-service/src/learning_agent_service/local_life/graph/state.py
learning-agent-service/src/learning_agent_service/local_life/graph/nodes.py
learning-agent-service/src/learning_agent_service/local_life/graph/edges.py
learning-agent-service/src/learning_agent_service/local_life/graph/builder.py
learning-agent-service/src/learning_agent_service/local_life/graph/runner.py
learning-agent-service/src/learning_agent_service/local_life/graph/events.py
learning-agent-service/src/learning_agent_service/local_life/graph/adapters.py
learning-agent-service/tests/local_life/test_day5_langgraph_skeleton_chat.py
```

修改：

```text
learning-agent-service/src/learning_agent_service/settings.py
```

新增配置：

```text
LOCAL_LIFE_USE_LANGGRAPH=false
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

---

## 5. 详细任务

### 5.1 定义 LocalLifeGraphState

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

### 5.2 第一批节点

```text
load_context
understand_query
resolve_target
build_contracts
route_review
```

每个 node 原则：

```text
复用 Day1-Day4 已稳定函数。
不重写业务逻辑。
不改变 Chat 行为。
```

### 5.3 builder.py

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

---

## 6. Chat/stream 验收用例

### Case D5-1：legacy 路径无回归

环境变量：

```bash
LOCAL_LIFE_USE_LANGGRAPH=false
```

请求：

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

请求：

```json
{"sessionId":"day5-chat-regression-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
仍默认推荐 3 家。
说明 Day5 的 LangGraph skeleton 没破坏旧路径。
```

断言：

```python
assert_recommendation_default_count(answer, result, expected=3)
```

---

## 7. Day5 完成标准

```text
1. LangGraph builder 可 compile。
2. graph.invoke 单测通过。
3. LOCAL_LIFE_USE_LANGGRAPH=false 时 Day1-Day4 Chat 测试无回归。
4. 新 graph 目录存在，并且节点边界清晰。
5. Chat 默认仍走 legacy，避免提前引入线上风险。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / LangGraph 工程实现代理。今天只做 Day5：

1. 新增 local_life/graph/ 目录。
2. 定义 LocalLifeGraphState。
3. 新增 nodes.py，先包装 load_context / understand_query / resolve_target / build_contracts / route_review。
4. 新增 builder.py，构建 StateGraph 并 compile。
5. 新增 LOCAL_LIFE_USE_LANGGRAPH=false 配置。
6. 不改变 Chat 默认路径。
7. 新增 test_day5_langgraph_skeleton_chat.py。
8. 必须跑 Day1-Day4 回归测试。
```
