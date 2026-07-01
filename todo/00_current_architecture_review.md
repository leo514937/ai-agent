# 00 当前架构审计

## 目标

基于 `toolcall` 分支当前实际代码，确认当前主链路到底做到什么程度，哪些是当前事实，哪些只是近期改造，哪些才是最终目标。

## 结论摘要

- 当前代码已经不是“LLM 直接选散工具”的最原始形态。
- 当前代码已经有完整主图，且 `Review` / `Verifier` 真实参与主链路。
- 当前代码仍然不是稳定的“能力包化 Agent”，因为 `search_shops()`、`build_evidence()`、`candidate_decision.py`、`target/reference_resolver.py` 仍然混杂着召回、补事实、决策和指代解析职责。
- 当前文档体系的核心应视为 Phase 1，也就是“单主链路能力边界收口与模块化”。
- 最终目标还需要二级 `orchestration_router` 和多 workflow 分流，但这不是第一批改造要做的事。

## 当前代码事实

### 1. 真实主链路已经存在

主链路从 `local_life_agent/app.py:chat_stream()` 进入，经 `_stream_chat_events()`、`run_agent_graph()`、`build_graph()`，依次走过：

- `intake_guard_router`
- `merge_clarification`
- `understanding_subgraph`
- `planning_subgraph`
- `execution_review_subgraph`
- `response_subgraph`
- `state_update_plan`

`merge_clarification` 位于 `intake_guard_router` 和 `understanding_subgraph` 之间，属于当前真实主链路的一部分，不是 future workflow。

### 2. 顶层一级路由已经存在

当前一级路由是 `top_intent_router`，位置在 `intake_guard_router` 内部，负责：

- `chat`
- `capability`
- `local_life`
- `unsafe`
- `out_of_scope`
- `invalid`

### 3. Review / Verifier 已经在主链路

当前代码里：

- `review_candidate_set()` 会决定是否澄清、是否完成、是否支持继续。
- `review_evidence()` 会判断证据是否足够。
- `review_decision()` 会判断最终决策是否可答。
- `answer/verifier.py:verify_answer()` 会校验回答与 evidence / decision 的一致性。

### 4. 当前仍有职责混杂

已确认的混杂点：

- `search_shops()` 仍承担召回 + 排序 + 截断。
- `build_evidence()` 仍承担补事实 + 推荐候选合并/排序。
- `candidate_decision.py` 仍依赖上游 rank 和上游证据形态。
- `target/reference_resolver.py` 是当前指代解析和比较目标解析的主要实现位置。
- 其他模块中仍存在与引用解析相关的规划启发、上下文恢复、观测推断或 trace 派生字段，因此当前问题不是 `observability/trace.py` 也在做真正解析，而是“解析结果、规划启发和观测推断之间的职责边界仍需进一步收口”。
- `observability/trace.py` 更多是在围绕 `reference_resolution_source` 等字段做观测、派生和追踪，而不是实现真实的引用解析。

### 5. 主链路仍有静态默认值污染

当前 `MOCK_LOCATION` 仍被 `input/receiver.py` 和 `engine/_compat.py` 作为默认位置注入运行时上下文，这不应继续作为主链路事实。

## 近期改造，而不是最终目标

以下内容属于当前最应该优先做的 Phase 1 收口：

- 收口 `search_shops`
- 收口 `build_evidence`
- 收口 `CandidateDecision`
- 抽公共 `ReferenceResolution`
- 补齐 `SessionState`
- 去掉主链路默认 `MOCK_LOCATION`
- 强化 `Review` / `Verifier`

这些改造可以在不改变外层图的情况下完成。

## 最终目标，不是当前事实

最终目标还需要：

- 二级 `orchestration_router`
- `workflow_runner`
- 多 workflow 分流
- `DiscoveryDecisionWorkflow`
- `DeterministicToolWorkflow`
- `DirectResponseWorkflow`
- `ClarificationFallbackWorkflow`
- `ExplorationPlanningWorkflow`

但这些属于后续阶段，第一批改造不要直接动外层图。

## 为什么当前文档应视为 Phase 1

因为当前最紧迫的问题不是 workflow 过多，而是：

1. 召回和决策边界混在一起。
2. 证据和排序混在一起。
3. 指代解析散落在多个模块。
4. 会话状态不完整。
5. 主链路仍有 mock 默认位置污染。

所以第一阶段应先做能力边界收口和模块化，而不是先引入新的 orchestration 层。

## 可执行建议

1. 把当前架构审计当成基线，不要把未来 workflow 写成既成事实。
2. 所有文档都明确区分“当前事实 / 近期改造 / 最终目标 / future work”。
3. 第一批改造只做 Phase 1，不改外层图。

## 可执行版补充

### 当前事实核验清单

| 核验项 | 当前事实 | 验证方式 | 说明 |
| --- | --- | --- | --- |
| 主链路存在 | 是 | `app.py -> run_agent_graph -> build_graph` | 不是单文件 toy flow |
| 顶层一级路由存在 | 是 | `intake_guard_router` / `top_intent_router` | 只做粗路由 |
| Review / Verifier 在主链路 | 是 | `review_candidate_set` / `review_evidence` / `review_decision` / `verify_answer` | 已参与当前执行链 |
| 职责混杂仍存在 | 是 | `search_shops` / `build_evidence` | 需要 Phase 1 收口 |
| `MOCK_LOCATION` 污染 | 是 | `config.py` 默认位置 | 需要去默认注入 |

### 当前阶段验收

- 当前事实只能用来指导 Phase 1 收口。
- 不能把 future workflow 写成现在已落地的事实。
- 不能把 reviewer / verifier 的存在误写成已经完成模块化。
- 不能用“最终目标”覆盖“当前事实”。
