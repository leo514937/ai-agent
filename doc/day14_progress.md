# Day14 进展 - P1-Day1 Typed GraphState + Command API 验证完成

> 日期：2026-06-06

## 完成事项

### 1. P1-Day1 改造验证（01:00 - 01:15）

**改造内容已落地并验证通过：**

#### 1.1 `StateGraph(dict)` → `StateGraph(GraphState)` 强类型化
- [builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py) line 239: `graph = StateGraph(GraphState)`
- 所有节点函数接收和返回结构化的 `GraphState` 类型

#### 1.2 Command API 硬跳转路由
- [subgraphs.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py) 中 4 个路由节点已全部使用 `Command(update=state, goto=target)` 方式进行跳转：
  - `run_load_context_node` (line 52-55): 根据 routing_decision 跳转到 `understand_turn` 或 `compose_answer`
  - `run_understand_turn` (line 269-312): 根据意图解析结果跳转到 `plan_execute_subgraph`、`rag_subgraph`、`tool_subgraph`、`route_gate` 或 `compose_answer`
  - `route_gate` (line 58-126): 路由决策网关，根据 `route_decider()` 跳转到各能力子图
  - `run_rag_subgraph` (line 315-328): RAG 执行后根据 `route_after_rag()` 跳转到 `tool_subgraph` 或 `compose_answer`

#### 1.3 移除冗余条件边
- builder.py 中不再有 `add_conditional_edges` 调用
- 所有路由逻辑内聚在节点函数中，通过 `Command` 返回值直接控制图的跳转

#### 1.4 拓扑描述更新
- `_LANGGRAPH_TOPOLOGY` 已更新为当前 Command 流拓扑结构

### 2. 测试验证结果

| 测试套件 | 结果 | 耗时 |
|---|---|---|
| `test_workflow_runner.py` | ✅ 4 passed | 3.06s |
| `test_langgraph_checkpointing.py` | ✅ 3 passed | 6.71s |
| `test_phase1_routing.py` | ✅ 7 passed | 2.60s |
| `test_phase0_core_replay.py` | ✅ 6 passed | 3.19s |
| `test_day1_target_shop_chat.py` | ✅ 4 passed | 159.54s |

### 3. 已知遗留问题

- `test_target_shop_policy_harness.py::test_explicit_shop_beats_history_anchor` — 断言 `target_shop.resolution_source == "explicit_query"` 失败（实际值为 `None`）。此为**预存遗留问题**，与 P1-Day1 改造无关，属于 metrics 输出缺失。

---

## 当前架构状态

```
StateGraph(GraphState)                    # 强类型状态图
├── load_context → Command(goto=...)      # 硬跳转
├── understand_turn → Command(goto=...)   # 硬跳转
├── route_gate → Command(goto=...)        # 硬跳转
├── rag_subgraph → Command(goto=...)      # 硬跳转
├── recommendation_subgraph → static edge → compose_answer
├── tool_subgraph → static edge → compose_answer
├── plan_execute_subgraph → static edge → compose_answer
├── compose_answer → static edge → persist_session
├── persist_session → static edge → emit_final
└── emit_final → static edge → END
```

**设计原则：**
- 路由节点（有分支决策的）通过 `Command` 返回值控制跳转
- 叶子节点（无分支的）通过静态 `add_edge` 连接
- 不再有 `add_conditional_edges` 的字符串路由

---

## 下一步建议

1. **修复遗留 `target_shop.resolution_source` 指标缺失**：在目标商铺解析阶段增加 `resolution_source` 指标输出
2. **继续 P1.5 编排图过渡**：参考 [P1.5_orchestration_transition_plan.md](file:///d:/javacode/hm-dianping/todo/P1.5/P1.5_orchestration_transition_plan.md) 进行后续阶段改造
