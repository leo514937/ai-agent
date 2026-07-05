# LangGraph Workflow Control Flow Audit Report

## 1. 结论

**总体判断：PASS**

当前仓库的 LangGraph 外层编排主骨架是成立的：

- `StateGraph(GraphState)` 存在
- 外层节点、条件边、workflow registry、workflow runner 都能对应到代码
- 顶层 workflow 白名单保持收敛，没有看到新增 workflow 扩大面

前一轮核查时确实存在两个真实控制流问题，但本轮已完成收口：

1. `local_life_agent/agent.py` 的 `run_agent_graph()` 已兼容 `trace_id` / `turn_id` 透传，`local_life_agent/app.py` 的 streaming 入口不再触发 `TypeError`
2. `local_life_agent/engine/workflows/exploration_planning_workflow.py` 已改为本地构造 clarification / fallback 同形状 patch，不再直接跨工作流调用 `run_clarification_fallback_workflow(...)`

因此当前可判定外层 LangGraph 控制流与 workflow handler 控制流已收口通过。

## 2. 核查范围

实际检查的文件：

- [`D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`](D:\javacode\hm-dianping\local_life_agent\engine\_routes.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflows\direct_response_workflow.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflows\direct_response_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\agent.py`](D:\javacode\hm-dianping\local_life_agent\agent.py)
- [`D:\javacode\hm-dianping\local_life_agent\app.py`](D:\javacode\hm-dianping\local_life_agent\app.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_runner.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_runner.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_registry.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_registry.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_deterministic_tool_workflow.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_deterministic_tool_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_comprehensive_graph_e2e.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_comprehensive_graph_e2e.py)
- [`D:\javacode\hm-dianping\local_life_agent\tests\test_app_streaming.py`](D:\javacode\hm-dianping\local_life_agent\tests\test_app_streaming.py)

## 3. 外层 LangGraph 编排事实

### 3.1 `StateGraph(GraphState)` 是否存在

存在。

- [`local_life_agent/engine/graph_builder.py:306`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py) 明确构造了 `StateGraph(GraphState)`

### 3.2 外层节点是否齐全

`graph_builder.py` 中的外层节点保持为：

- `intake_guard_router`
- `merge_clarification`
- `understanding_subgraph`
- `orchestration_router_shadow`
- `workflow_runner`
- `planning_subgraph`
- `execution_review_subgraph`
- `response_subgraph`
- `state_update_plan`

### 3.3 条件边是否由 `_routes.py` 和 `add_conditional_edges` 控制

是。

- [`local_life_agent/engine/graph_builder.py:319`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:324`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:329`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:335`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:340`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:345`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)
- [`local_life_agent/engine/graph_builder.py:350`](D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py)

这些条件边分别连接到：

- `_route_intake_guard`
- `_route_merge_clarification`
- `_route_understanding_subgraph`
- `_route_workflow_runner`
- `_route_planning_subgraph`
- `_route_execution_review_subgraph`
- `_route_response_subgraph`

### 3.4 主路由是否仍是单主线

是。

当前可确认的主线仍然是单条主链路，没有看到 workflow fan-out 或多 workflow 并行抢答的生产路径。

## 4. Workflow Registry 与 Runner

### 4.1 registry 是否保持白名单

是。

[`local_life_agent/engine/workflow_registry.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py) 里的 `LEGAL_WORKFLOW_NAMES` 仍保持为：

- `direct_response`
- `deterministic_tool`
- `discovery_decision`
- `exploration_planning`
- `clarification_fallback`

### 4.2 runner 是否还是单 workflow dispatch

是。

[`local_life_agent/engine/workflow_runner.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py) 仍然是：

- 读取 `orchestration_decision`
- 单值 lookup
- 单个 handler dispatch
- 失败时走 runner 自己的 fallback patch

没有看到 `workflow_names`、`final_responses`、`state_update_plans` 这类多路 merge 生产路径。

### 4.3 workflow handler 是否是黑盒

是，但这是“边界上的黑盒”，不等于错误。

- `direct_response`
- `clarification_fallback`
- `deterministic_tool`
- `exploration_planning`

都以普通函数形式挂在 registry 上，不是嵌入式 LangGraph 子图。

其中 `deterministic_tool` 和 `exploration_planning` 的内部控制流更复杂，`exploration_planning` 的黑盒程度最高。

## 5. 发现的真实问题

本轮复查后，前述两项真实问题均已修复：

### 5.1 HTTP / streaming 路径参数不兼容

已修复。

- [`local_life_agent/app.py:101`](D:\javacode\hm-dianping\local_life_agent\app.py) 仍然传递 `trace_id` / `turn_id`
- [`local_life_agent/agent.py`](D:\javacode\hm-dianping\local_life_agent\agent.py) 的 `run_agent_graph()` 已兼容这两个参数
- 直接调用 `run_agent_graph('hi', session_id='s1', trace_id='t1', turn_id='u1')` 已成功返回结果

### 5.2 `exploration_planning_workflow` 直接 bypass 路由

已修复。

- [`local_life_agent/engine/workflows/exploration_planning_workflow.py`](D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py) 已移除直接 `return run_clarification_fallback_workflow(...)`
- 现在由本地 helper 构造 clarification / fallback 同形状 patch
- `_routes.py` 的 outer 路由仍保持完整可见

## 6. 其他命中是否 harmless

### 6.1 `workflow_names` / `final_responses` / `state_update_plans`

命中主要来自测试和审计断言，不是生产路径。

### 6.2 `MapReduce / map_reduce / map-reduce`

命中主要来自：

- `local_life_agent/core/execution_core.py` 的执行层说明
- `tools/gateway.py` 的批处理说明

这里更像执行层并行聚合，而不是 workflow-level MapReduce 主编排。

### 6.3 `ReAct / RAG / transaction / booking / payment`

命中主要来自：

- 明确拒绝提示
- 任务能力审查
- 测试覆盖

没有发现新增的生产主路径能力。

## 7. 测试结果

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_exploration_planning_workflow.py local_life_agent/tests/test_app_streaming.py -q`
- 结果：`23 passed, 1 warning`

另外，已直接复现入口级调用成功：

- `run_agent_graph('hi', session_id='s1', trace_id='t1', turn_id='u1')` 成功返回

## 8. 最终判断

### 8.1 仍然成立的部分

- 外层 LangGraph 编排存在且清晰
- workflow registry 是白名单
- workflow runner 是单 workflow dispatch
- 没有看到生产路径上的多 workflow merge / fan-out
- `deterministic_tool`、`direct_response`、`clarification_fallback` 的边界仍可接受

### 8.2 仍然阻塞通过的部分

已收口：

- HTTP / streaming 入口的 `run_agent_graph` 签名已兼容
- `exploration_planning_workflow` 已不再直接调用 fallback workflow 绕过 `_routes.py`

## 9. 建议修复方向

1. 当前两个控制流 blocker 已收口，不需要再为本次审计追加修复
2. 后续只需把这两条路径继续纳入常规回归，防止回退：
   - `test_app_streaming.py`
   - `test_workflow_runner.py`
   - `test_workflow_registry.py`
   - `test_exploration_planning_workflow.py`

## 10. 最终结论

- `LANGGRAPH_OUTER_CONTROL_FLOW_AUDIT = PASS`
- `APP_RUN_AGENT_GRAPH_SIGNATURE_OK = true`
- `EXPLORATION_PLANNING_NO_ROUTE_BYPASS = true`

外层编排与 workflow handler 控制流已完成收口，可以判定为稳定通过。
