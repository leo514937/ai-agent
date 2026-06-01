# Day6：LangGraph conditional edges + 子图接入 + Chat 灰度切换

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
1. 让核心分支由 LangGraph conditional edges 控制。
2. 接入 clarify / tool / rag / rag_plus_tool / direct 分支。
3. Chat 接口支持 LOCAL_LIFE_USE_LANGGRAPH=true 灰度走 compiled graph。
4. 保留 fallback legacy。
5. 确保 Day1-Day4 业务问题在 LangGraph 路径不回归。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P2 | route_gate conditional edges | 从 Python if/else 迁移到 LangGraph |
| P2 | execute_tools node | 接入 Day3 多工具能力 |
| P2 | retrieve_evidence node | 接入 Day4 RAG 能力 |
| P2 | entity_consistency / fuse_and_rank / build_response | 汇合分支结果 |
| P3 | LocalLifeGraphRunner.stream | Chat 接口走 compiled graph |
| P3 | fallback legacy | 出错时可回退但必须记录 trace |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day6 聚焦部分高亮)

```text
START
  │
  ▼
[load_context] ──> [understand_query] ──> [resolve_target] ──> [build_contracts] ──> [route_review]
                                                                                          │
                                                                                          ▼
                                                                             ┌──────[route_gate]──────┐
                                                                             │   (由路由条件边控制)    │
                                                                             └────────────┬───────────┘
                                                                                          │
       ┌─────────────────────────────┬─────────────────────────────┬──────────────┼─────────────┐
       ▼                             ▼                             ▼              ▼             ▼
┌──────────────┐             ┌──────────────┐             ┌────────────────┐ ┌─────────┐   ┌─────────┐
│[execute_tools]             │[retrieve_evi]│             │[recommendation]│ │[clarify]│   │[direct] │
│(实时工具子图) │             │ (RAG检索子图) │             │ (多店推荐子图)  │ │ (澄清)  │   │(直答)   │
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘ └────┬────┘   └────┬────┘
       │                            │                             │               │             │
       ▼                            ▼                             ▼               │             │
┌──────────────┐             ┌──────────────┐             ┌────────────────┐      │             │
│[ToolResults] │             │[EvidencePack]│             │[Recommendation]│      │             │
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘      │             │
       │                            │                             │               │             │
       └──────────────┬─────────────┴──────────────┬──────────────┘               │             │
                      ▼                            ▼                              │             │
          ┌──────────────────────────┐   ┌──────────────────────────┐             │             │
          │ [entity_consistency]     │   │ [facet_result_bundle]    │             │             │
          │ (证据/工具强对齐汇合节点) │   │                          │             │             │
          └────────────┬─────────────┘   └────────────┬─────────────┘             │             │
                       │                              │                           │             │
                       └──────────────┬───────────────┘                           │             │
                                      ▼                                           ▼             ▼
                            ┌────────────────────┐                          ┌──────────────────┐
                            │ [fuse_and_rank]    │ ───────────────────────> │ [build_response] │
                            └─────────┬──────────┘                          └─────────┬────────┘
                                      │                                               │
                                      ▼                                               ▼
                            ┌────────────────────┐                          ┌──────────────────┐
                            │ [plan_answer]      │ ───> [verify_grounding] ─>│[sanitize_response│
                            └────────────────────┘                          └─────────┬────────┘
                                                                                      │
                                                                                      ▼
                                                                            ┌──────────────────┐
                                                                            │ [persist_context]│
                                                                            └─────────┬────────┘
                                                                                      │
                                                                                      ▼
                                                                                     END
```

### 3.2 当天要完成的架构链路与流转关系

在 Day6 阶段，我们将完成**整张图控制边的全量组装**。将原本在 Python 中通过 `if/else` 控制的分流路由，彻底托付给 LangGraph 的 `conditional_edges`。

当天核心打通并锁定的链路流转关系如下：
```text
【前半段执行完毕】 (route_review 结束)
        │
        ▼
【route_gate】 ==> 触发核心路由选择器 【route_decider】 ──┐
                                                       │
  ┌────────────────────────────────────────────────────┘
  ├─ 识别为澄清    ==> 路由至 [clarify] 节点          ───> 直接流入 [build_response]
  ├─ 识别为工具    ==> 路由至 [execute_tools] 节点    ───┐
  ├─ 识别为检索    ==> 路由至 [retrieve_evidence] 节点 ───┼─> 最终汇合至 [entity_consistency]
  ├─ 识别为复合    ==> 路由至 [rag_plus_tool] 混合链路  ───┤
  ├─ 识别为推荐    ==> 路由至 [recommendation] 节点   ───┘
  └─ 识别为直接    ==> 路由至 [direct] 分支           ───> 直接流入 [build_response]
        │
        ▼
【后半段汇合链条】
  [entity_consistency]  ==> 强对齐各分支产出的 shop_id
        │
  [fuse_and_rank]       ==> 执行证据打分、排序融合与候选商户筛选
        │
  [plan_answer]         ==> 触发大模型生成大纲计划
        │
  [verify_grounding]    ==> 事实性与券数量核对校验
        │
  [build_response]      ==> 最终模板拼装与多轮对话生成
        │
  [sanitize_response]   ==> 内部冗余敏感字段剥离
        │
  [persist_context]     ==> 序列化并存储至 Redis 会话层
        │
      【END】
```

> [!TIP]
> **落地折中与渐进式并行建议**：
> - 考虑到并行 `fan-out` 在 Day6 的复杂度，**当天可以先把 `rag_plus_tool` 实现为顺序串行**：先由 `execute_tools` 执行工具获取 `ToolResults` 并追加写入 state，随后无缝流入 `retrieve_evidence` 获取 `EvidencePack`。
> - 主流 Chat API 正式开启灰度测试（`LOCAL_LIFE_USE_LANGGRAPH=true`）。如果在 compiled graph 运行中发生任何未捕获异常，通过 `LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true` 机制平滑回退到 legacy 的 `run_stream` 主动容灾，防止影响前端用户体验。

---

### 3.3 路由选择器 route_decider 逻辑

```python
def route_decider(state: LocalLifeGraphState) -> str:
    if state.get("clarification", {}).get("need_clarification"):
        return "clarify"

    execution = state.get("execution_contract", {})
    execute_tools = bool(execution.get("execute_tools"))
    execute_rag = bool(execution.get("execute_rag"))
    recommendation_mode = bool(state.get("recommendation_mode"))

    if recommendation_mode:
        return "recommendation"

    if execute_tools and execute_rag:
        return "rag_plus_tool"

    if execute_tools:
        return "tool"

    if execute_rag:
        return "rag"

    return "direct"
```

---

## 4. 需要修改/新增的文件

修改/补充：

```text
learning-agent-service/src/learning_agent_service/local_life/graph/nodes.py
learning-agent-service/src/learning_agent_service/local_life/graph/edges.py
learning-agent-service/src/learning_agent_service/local_life/graph/builder.py
learning-agent-service/src/learning_agent_service/local_life/graph/runner.py
learning-agent-service/src/learning_agent_service/local_life/graph/events.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/settings.py
learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py
```

---

## 5. 详细任务

### 5.1 route_decider

```python
def route_decider(state: LocalLifeGraphState) -> str:
    if state.get("clarification", {}).get("need_clarification"):
        return "clarify"

    execution = state.get("execution_contract", {})
    execute_tools = bool(execution.get("execute_tools"))
    execute_rag = bool(execution.get("execute_rag"))
    recommendation_mode = bool(state.get("recommendation_mode"))

    if recommendation_mode:
        return "recommendation"

    if execute_tools and execute_rag:
        return "rag_plus_tool"

    if execute_tools:
        return "tool"

    if execute_rag:
        return "rag"

    return "direct"
```

### 5.2 add_conditional_edges

```python
builder.add_conditional_edges(
    "route_gate",
    route_decider,
    {
        "clarify": "clarify",
        "tool": "execute_tools",
        "rag": "retrieve_evidence",
        "rag_plus_tool": "rag_plus_tool",
        "recommendation": "recommendation",
        "direct": "build_response",
    },
)
```

### 5.3 SSE 兼容

LangGraph node 不直接 yield SSE。

推荐方式：

```text
node 内向 state["sse_events"] append event
runner 统一把 sse_events 转成 SseEnvelope
```

---

## 6. Chat/stream 验收用例

### 环境变量

```bash
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

### Case D6-1：LangGraph 单店请求

请求：

```json
{"sessionId":"day6-lg-single-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
Chat 接口走 LangGraph。
最终答案围绕目标店。
trace 中 graph_path 包含：
load_context → understand_query → resolve_target → build_contracts → route_review。
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

请求：

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

请求：

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

### 回归测试

必须运行：

```text
Day1-Day4 全部 Chat golden cases
```

并且在 LangGraph 路径下通过。

---

## 7. Day6 完成标准

```text
1. LOCAL_LIFE_USE_LANGGRAPH=true 下 Day1-Day4 全部 Chat tests 通过。
2. SSE 事件兼容旧前端。
3. conditional edges trace 可见。
4. fallback legacy 可用。
5. Chat 接口可以灰度走 LangGraph compiled graph。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / LangGraph / SSE Runner 工程实现代理。今天只做 Day6：

1. 在 builder.py 中新增 route_gate conditional edges。
2. 接入 clarify / execute_tools / retrieve_evidence / rag_plus_tool / recommendation / direct 分支。
3. 新增或完善 LocalLifeGraphRunner.stream。
4. node 内不要直接 yield SSE，统一写入 sse_events。
5. Chat 接口支持 LOCAL_LIFE_USE_LANGGRAPH=true。
6. 保留 LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true fallback。
7. 新增 test_day6_langgraph_chat_stream.py。
8. 必须在 LangGraph 路径下跑 Day1-Day4 全量回归。
```
