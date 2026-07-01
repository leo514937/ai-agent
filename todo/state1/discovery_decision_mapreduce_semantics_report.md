# Discovery Decision MapReduce Semantics Report

## 1. Conclusion

明确结论：

- 当前 `discovery_decision` 有 `MapReduce-style` 的执行思想。
- 当前不是 `LangGraph-native` 的 `MapReduce`。
- 当前并发发生在 `tool gateway / execution core` 层，不是在 LangGraph graph fan-out 层。
- 当前 reduce 发生在业务聚合层，例如 `tool_result_set -> evidence_pack -> decision_plan`，不是 LangGraph reducer 聚合业务 state。

本轮核对中，未发现 `Send(...)`、dynamic fan-out node、per-tool map node、per-candidate map node，或针对 `tool_results` / `tool_result_set` / `evidence_pack` 的 LangGraph reducer 写法。

## 2. Current Actual Flow

真实链路更接近下面这条受控 workflow：

```text
planning_subgraph
  -> evidence_planner
  -> plan_validator
  -> execution_review_subgraph
      -> tool_execute
      -> evidence_build
      -> evidence_review
      -> decision_planner
      -> decision_review
  -> response_subgraph
```

职责拆分如下：

- `planning_subgraph`
  - 负责 goal planning、target resolve、clarify decision、evidence planning、plan validation。
  - 参考实现位于 [`local_life_agent/engine/subgraphs/planning_subgraph.py`](../local_life_agent/engine/subgraphs/planning_subgraph.py)。

- `execution_review_subgraph`
  - 负责工具执行、证据构建、证据审查、决策规划、决策审查。
  - 参考实现位于 [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)。

- `tool_execute`
  - 读取 `validated_plan` / `execution_plan` 中的一批 `tool_calls`。
  - 通过 `ExecutionCore.execute_batch(...)` 和 `BatchToolExecutor` 做批量并发调用。

- `evidence_build`
  - 将 `tool_result_set`、`resolved_target`、`validated_plan`、候选列表、comparison targets 聚合成 `EvidencePack`。

- `evidence_review`
  - 做证据充分性检查，决定是否继续、重试、澄清或 fallback。

- `decision_planner`
  - 基于 `EvidencePack` 组装 `DecisionPlan`，输出 claims、winner、evidence references 等结构化决策。

- `decision_review`
  - 对 `DecisionPlan` 做充分性与一致性检查，决定 finish / replan / clarify / fallback。

值得注意的是，当前 `discovery_decision` 的具体路由并不是一个独立的 `discovery_decision_workflow.py` 文件实现，而是由 orchestration router + workflow registry 把 `discovery_decision` 映射到现有受限工作流与子图执行链路中。

## 3. Where the Map Semantics Exist

Map 语义的实际位置是业务执行层，而不是图层 fan-out：

- `ExecutionPlan.tool_calls` 表示一批工具调用计划。
- `ExecutionCore.execute_batch(...)` 是批量执行入口。
  - 文件：[`local_life_agent/core/execution_core.py`](../local_life_agent/core/execution_core.py)
  - 函数：`ExecutionCore.execute_batch`
- `BatchToolExecutor` 是真正的批量并发执行器。
  - 文件：[`local_life_agent/tools/gateway.py`](../local_life_agent/tools/gateway.py)
  - 类：`BatchToolExecutor`
- `asyncio.gather(...)` 出现在 `BatchToolExecutor.execute(...)` 中，说明并发是 Python 执行器层实现的。
  - 文件：[`local_life_agent/tools/gateway.py`](../local_life_agent/tools/gateway.py)
  - 函数：`BatchToolExecutor.execute`
- `tool_execute` 对 `search_shops` 与后续 resolved calls 做了批处理执行。
  - 文件：[`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)
  - 函数：`_h_tool_execute`

因此，这里的 map 更准确地说是 **logical map / batch-concurrent map**，不是 LangGraph `Send` 驱动的 graph-level map。

## 4. Where the Reduce Semantics Exist

Reduce 语义主要出现在业务聚合层：

- 多个 tool result 会被合并成 `tool_result_set`。
  - 定义位置：[`local_life_agent/domain/graph_state.py`](../local_life_agent/domain/graph_state.py)
- `evidence_build` 会把 `tool_result_set`、候选集、comparison targets、resolved target 等聚合成 `EvidencePack`。
  - 参考实现：[`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)
  - 聚合器：[`local_life_agent/planning/evidence/evidence_builder.py`](../local_life_agent/planning/evidence/evidence_builder.py)
- `decision_planner` 会把 `EvidencePack` 进一步归并成 claims、winner、decision trace、claim bindings。
  - 参考实现：[`local_life_agent/planning/decision/decision_planner.py`](../local_life_agent/planning/decision/decision_planner.py)
- `decision_review` 再对 decision 进行充分性和一致性校验。
  - 参考实现：[`local_life_agent/planning/decision/decision_review.py`](../local_life_agent/planning/decision/decision_review.py)

这属于 **business-level reduce**，不是 LangGraph reducer。

## 5. What It Is Not

当前没有证据表明 `discovery_decision` 使用了 LangGraph 原生 `MapReduce` 机制。

本轮未发现：

- `Send(...)`
- dynamic fan-out node
- per-tool map node
- per-candidate map node
- business-state reducer for `tool_results` / `tool_result_set` / `evidence_pack`
- 多个 LangGraph 并行节点写同一个业务 state key 后自动聚合

此外，`GraphState` 中的 `Annotated[list, add]` 仅用于 `event_log` / `trace_spans` 这类观测字段，不是用于 `tool_result_set` 或 `evidence_pack` 的 reducer 聚合。

## 6. Recommended Naming

建议统一命名：

- `batch tool execution`
- `MapReduce-style tool execution`
- `evidence aggregation`
- `business-level reduce`
- `bounded workflow`
- `not LangGraph-native MapReduce`

避免使用：

- `LangGraph MapReduce`
- `native MapReduce graph`
- `Send/reducer MapReduce`
- `parallel graph fan-out`

除非未来真的实现了 `Send + reducer`。

## 7. Suggested Future Evolution

如果未来要升级为真正的 LangGraph MapReduce，需要：

- 使用 `Send` 对 tool call / candidate / subgoal fan-out；
- 为业务 state key 设计 reducer；
- 增加 map node 和 reduce node；
- 处理 timeout、partial failure、trace、顺序不稳定、结果去重；
- 增加对应测试。

但本轮不做这个改造。

## 8. Final Verdict

`discovery_decision` 当前是 bounded workflow 内部的 MapReduce-style batch tool execution and evidence aggregation，不是 LangGraph-native Send/reducer MapReduce graph。

