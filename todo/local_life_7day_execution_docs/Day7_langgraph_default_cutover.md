# Day7：默认切换 LangGraph compiled graph + 完整验收

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
1. Chat 接口默认走 LangGraph compiled graph。
2. LocalLifeSubgraph.run_stream 降级为 fallback。
3. 全量 golden cases 通过。
4. 复杂单店请求和复杂多店推荐请求通过。
5. 导出图结构，更新 README / ARCHITECTURE。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P3 | LOCAL_LIFE_USE_LANGGRAPH 默认 true | 完成主入口切换 |
| P3 | legacy run_stream fallback | 保留应急路径 |
| P3 | graph smoke test | 证明节点/边可导出 |
| P2 | 全量 golden cases | 确保业务不回归 |
| P2 | 复杂单店/多店推荐验收 | 验证 fan-out/join 效果 |
| P3 | README / ARCHITECTURE 更新 | 让后续维护有依据 |

---

## 3. 最终参考架构

### 3.1 改造后最终建议总图 (Day7 运行态完全就绪)

```text
=============================【Day7 全量合流！LangGraph 100% 生产态图结构】=============================
START
  │
  ▼
┌────────────────────────┐
│ [load_context]         │ (从会话恢复 client_context 及 persistent_context 状态字典)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [understand_query]     │ (完成 normalized_query 语义清洗与 Slot 槽位抽取)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [resolve_target]       │ (触发 TargetShopPolicy 绑定并锁定当前轮 target_shop)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [build_contracts]      │ (生成允许最终暴露的事实契约限制 AnswerContract)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│ [route_review]         │ (流式网关判定，确定 execution_contract 方案)
└──────────┬─────────────┘
           │
           ▼
     ┌───────────┐
     │route_gate │ ───────────────────────────────────────┐
     └─────┬─────┘                                        │
           │ (由 route_decider 动态进行分流)                │
           ├──────────────────────┬──────────────────────┐│
           ▼                      ▼                      ▼│
     ┌───────────┐          ┌───────────┐          ┌───────────┐│
     │ no_rag    │          │ single_rag│          │ reco_rag  ││
     └─────┬─────┘          └─────┬─────┘          └─────┬─────┘│
           │                      │                      │      │
           │ (直接答)              │ (单店强过滤过滤)        │(多店) │      │
           ▼                      ▼                      ▼      ▼
     ┌───────────┐          ┌───────────┐          ┌───────────┐┌───────┐
     │  直答处理  │          │EvidencePack│          │多店候选集  ││ 澄清  │
     └─────┬─────┘          └─────┬─────┘          └─────┬─────┘└─┬─────┘
           │                      └──────────┬───────────┘        │
           ▼                                 ▼                    │
     ┌───────────┐                 ┌────────────────────┐         │
     │ 拼装回答  │ ────────────────> │ EntityConsistency  │         │
     └─────┬─────┘                 │ (证据与候选店强对齐)│         │
           │                       └─────────┬──────────┘         │
           │                                 ▼                    │
           │                       ┌────────────────────┐         │
           │                       │  [Fusion / Rank]   │         │
           │                       │  (打分/推荐排名)    │         │
           │                       └─────────┬──────────┘         │
           │                                 ▼                    │
           │                       ┌────────────────────┐         │
           │                       │   AnswerContract   │         │
           │                       │  (允许输出契约控制)  │         │
           │                       └─────────┬──────────┘         │
           ▼                                 ▼                    ▼
     ┌───────────────────────────────────────┴────────────────────┐
     │                       [ResponseBuilder]                    │ 
     │                     (围绕允许事实输出最终文本)                     │
     └───────────────────────────────────────┬────────────────────┘
                                             │
                                             ▼
                                   ┌────────────────────┐
                                   │ [sanitize_response]│ (剔除调试敏感字段)
                                   └─────────┬──────────┘
                                             │
                                             ▼
                                   ┌────────────────────┐
                                   │ [persist_context]  │ (瘦身写入 Redis 并更新 current_shop)
                                   └─────────┬──────────┘
                                             │
                                             ▼
                                            END
```

### 3.2 高级流转关系：Fan-out / Join 并行并行流转

Day7 支持在 execution 层面，根据 `FacetExecutionPlan` 将请求并行流式调度入子图，并在末端由汇合节点强对齐：
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
│ (实时工具)    │             │ (RAG 检索)   │             │ (多店推荐)      │
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
          │ shop_id 物理强对齐        │   │ 汇总工具/证据数据包       │
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

### 3.3 当天要完成的架构链路与流转关系

在 Day7 阶段，我们要执行**全量切流（Cutover）与生产发布**。废弃 legacy 入口，让本地生活智能体工作流默认 100% 流经由 `LangGraph` 控制的 compiled graph 容器。

当天核心打通并锁定的链路流转关系如下：
```text
【流式 Chat 网关触发】 /api/ai/chat/stream
         │
         ▼
【切流决策】 LOCAL_LIFE_USE_LANGGRAPH=true ───┐
                                              │
  ┌───────────────────────────────────────────┘
  ├─ 默认状态：由 LocalLifeGraphRunner.stream() 接管 ──> 调用 compiled_graph.astream(...)
  │                                                      │
  │     ┌────────────────────────────────────────────────┘
  │     ▼
  │  【全量 LangGraph 内部骨架流转连通】 ──> 输出 delta 流式打字机事件
  │                                    ──> 最终产生 final_answer 存回 state["final_answer"]
  │
  └─ 容灾异常兜底：若 Graph 抛出严重未捕获异常
         │
         ▼
     LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true ──> 降级转入 legacy LocalLifeSubgraph.run_stream(...)
```

> [!IMPORTANT]
> **生产标准与完工定义**：
> 1. **全量 golden 绿灯**：所有 Day1-Day6 累积的 golden cases（包括问A答B、券数、营业推荐）必须在切流状态下 100% 绿灯通过，不得存在任何退化。
> 2. **不可静默退避**：一旦在旁路中触发了 fallback 应急链路，系统必须在 Trace/Metrics 中显式写入 `fallback = legacy`，杜绝一切静默故障被掩盖的隐患。
> 3. **架构大一统**：大计划中设计的 *“主图强控制 + 契约限制 + 标准化 CouponResult / EvidencePack”* 的大一统架构，在 Day7 日终宣告全面落地！

---

## 4. 需要修改/新增的文件

修改：

```text
learning-agent-service/src/learning_agent_service/settings.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/local_life/graph/runner.py
learning-agent-service/src/learning_agent_service/local_life/graph/builder.py
README.md
ARCHITECTURE.md 或 docs/local_life_architecture.md
```

新增/补充测试：

```text
learning-agent-service/tests/local_life/test_day7_langgraph_default_chat.py
learning-agent-service/tests/local_life/test_chat_contract_cases.py
learning-agent-service/tests/local_life/test_langgraph_smoke.py
```

---

## 5. 详细任务

### 5.1 默认切换配置

```text
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
```

Chat 入口逻辑：

```python
if settings.local_life_use_langgraph:
    try:
        yield from LocalLifeGraphRunner.stream(...)
    except Exception:
        if settings.local_life_langgraph_fallback_legacy:
            yield from LocalLifeSubgraph.run_stream(...)
        else:
            raise
else:
    yield from LocalLifeSubgraph.run_stream(...)
```

必须记录：

```text
graph_runtime = langgraph
fallback = none / legacy
```

### 5.2 图结构导出

测试中必须能确认：

```text
load_context
understand_query
resolve_target
route_gate
build_response
persist_context
```

这些节点存在。

---

## 6. Chat/stream 验收用例

### 环境变量

```bash
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY=true
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
不得悄悄 fallback 到 legacy。
```

断言：

```python
assert_all_golden_cases_pass()
assert_trace_value(result, "graph_runtime", "langgraph")
assert_trace_not_contains(result, "fallback", "legacy")
```

### Case D7-2：复杂单店复合请求

请求：

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

请求：

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
每家店尽量包含：
- 推荐理由
- 是否适合约会
- 是否有券或券查询结果
- 是否营业或营业状态
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

---

## 7. Day7 完成标准

```text
1. Chat 接口默认走 LangGraph compiled graph。
2. 全量 golden cases 通过。
3. 复杂单店请求通过。
4. 复杂多店推荐请求通过。
5. 图结构 smoke test 通过。
6. legacy run_stream 仅作为 fallback。
7. README / ARCHITECTURE 已更新。
8. trace 中 graph_runtime = langgraph。
9. 未异常时不得 fallback legacy。
```

---

## 8. 最终完成定义

业务正确性：

```text
- 问 A 店只答 A 店。
- 第二轮显式新商铺覆盖第一轮。
- 单店 RAG 只用目标店证据。
- 优惠券数量只来自实时 CouponResult。
- 附近推荐默认输出 3 家不同商铺。
- 问券不答环境，问营业不答推荐。
```

架构正确性：

```text
- 主流程由 LangGraph StateGraph 构建。
- 节点通过 add_node 注册。
- 边通过 add_edge 注册。
- 分支通过 add_conditional_edges 控制。
- compiled graph 是 Chat 主路径。
- legacy run_stream 只是 fallback。
```

测试正确性：

```text
- 所有关键用例从 /api/ai/chat/stream 触发。
- 解析 SSE final/delta/tool_call/tool_result/retrieval_result。
- 测试最终用户可见文本。
- 测试 trace 中 target_shop / answer_contract / execution_contract / evidence / coupon_result。
```

---

## 9. 当天 Codex 执行提示词

```text
你是资深 Python / LangGraph / FastAPI / Agent 架构迁移工程实现代理。今天只做 Day7：

1. 将 LOCAL_LIFE_USE_LANGGRAPH 默认设置为 true。
2. Chat 接口默认走 LocalLifeGraphRunner.stream。
3. LocalLifeSubgraph.run_stream 只作为 fallback。
4. fallback 必须写 trace，不能静默发生。
5. 新增 test_day7_langgraph_default_chat.py。
6. 新增 graph smoke test，检查节点和边存在。
7. 全量执行 Day1-Day6 golden cases。
8. 验证复杂单店请求和复杂多店推荐请求。
9. 更新 README / ARCHITECTURE。
10. 完成后输出：graph_runtime、节点列表、边列表、Chat 测试结果、剩余风险。
```
