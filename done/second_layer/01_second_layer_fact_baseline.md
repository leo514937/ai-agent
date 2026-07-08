# 第二层事实基线

## 调研范围

本次只基于当前仓库真实代码扫描第二层相关实现与直接依赖：

- `local_life_agent/engine/subgraphs/planning_subgraph.py`
- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/engine/workflows/deterministic_tool_workflow.py`
- `local_life_agent/engine/workflows/exploration_planning_workflow.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/planning/evidence/evidence_planner.py`
- `local_life_agent/planning/evidence/facet_budget.py`
- `local_life_agent/planning/evidence/evidence_cache.py`
- `local_life_agent/planning/evidence/evidence_builder.py`
- `local_life_agent/planning/plans/execution_plan_builder.py`
- `local_life_agent/planning/plans/plan_validator.py`
- `local_life_agent/planning/budget/budget_context.py`
- `local_life_agent/tools/gateway.py`
- `local_life_agent/core/execution_core.py`
- `local_life_agent/planning/evidence/tool_batch_executor.py`
- `local_life_agent/domain/schemas.py`
- `local_life_agent/domain/decision.py`
- 相关测试：`test_goal_planner.py`、`test_evidence_planner.py`、`test_execution_plan_validator.py`、`test_planning_execution_boundary.py`、`test_deterministic_tool_workflow.py`、`test_workflow_runner.py`、`test_phase2_routing_authority.py`、`test_p9_evidence_planner_capability_budget.py`、`test_p10_experience_performance.py`、`test_p12_deadline_budget_freshness_ttl.py`

## 第二层真实调用链

### 1. 路由 / 工作流选择链

真实代码不是“Router 解析 DAG”，而是：

`route_orchestration -> build_orchestration_decision -> validate_orchestration_decision -> orchestration_router_shadow -> workflow_runner -> workflow_registry -> workflow handler`

其中：

- `route_orchestration` 既算 workflow，也顺手写入 `facet_set`、`target_resolution`、`router_policy_decision`、`comparison_route_reason`
- `h_workflow_runner` 才是真正把 workflow 名称交给注册表并分发 handler 的地方

证据：

- `[planning/orchestration_router.py:1584-1710](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L1584)`
- `[engine/subgraphs/orchestration_router_shadow.py:20-79](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/orchestration_router_shadow.py#L20)`
- `[engine/workflow_runner.py:97-291](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L97)`

### 2. Planning 子图链

`h_planning_subgraph()` 的真实顺序是：

1. `_h_goal_planner`
2. `_h_goal_review`
3. `_h_target_resolve`
4. `_h_evidence_planner`
5. `_h_plan_validator`
6. 根据结果路由到 `planning_route`

比较任务、歧义店铺、缺失当前店等情况会在这个子图中提前澄清或 fallback。

证据：

- `[planning_subgraph.py:253-483](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L253)`
- `[planning_subgraph.py:493-535](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L493)`
- `[planning_subgraph.py:539-590](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L539)`
- `[planning_subgraph.py:571-760](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L571)`
- `[planning_subgraph.py:1138-1256](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L1138)`
- `[planning_subgraph.py:1259-1300](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L1259)`

### 3. 执行 / 证据 / 决策链

`h_execution_review_subgraph()` 的真实顺序是：

1. `_h_tool_execute`
2. `_h_evidence_build`
3. `_h_evidence_review`
4. `_h_decision_planner`
5. `_h_decision_review`
6. 路由到 `execution_review_route`

证据：

- `[execution_review_subgraph.py:57-103](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L57)`
- `[execution_review_subgraph.py:111-206](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L111)`
- `[execution_review_subgraph.py:210-241](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L210)`
- `[execution_review_subgraph.py:244-292](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L244)`
- `[execution_review_subgraph.py:295-342](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L295)`

## 现有第二层对象

### `ExecutionStage`

- 文件 / 定义：`local_life_agent/domain/schemas.py:948-961`
- 现有字段：
  - `stage_id`
  - `description`
  - `tool_names`
  - `depends_on`
  - `max_parallelism`
- 结论：当前已经有 stage 级结构，但它只描述阶段，不是完整 DAG 执行器
- 证据：`[schemas.py:948-961](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L948)`

### `ToolCallSpec`

- 文件 / 定义：`local_life_agent/domain/schemas.py:964-980`
- 现有字段：
  - `call_id`
  - `tool_name`
  - `args`
  - `target_shop_id`
  - `required`
  - `facet`
  - `depends_on`
  - `timeout_ms`
  - `retry_policy`
  - `fallback_policy`
  - `group_id`
  - `max_parallelism`
- 结论：这是可执行计划的核心节点，但还没有 `cache_key`、`degrade_policy`、`node_id` 这些 DAG 级字段
- 证据：`[schemas.py:964-980](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L964)`

### `ExecutionPlan`

- 文件 / 定义：`local_life_agent/domain/schemas.py:983-1019`
- 现有字段已经同时混合了：
  - 计划描述：`plan_id`、`task_type`、`facets`、`optional_facets`
  - 执行结构：`dependencies`、`tool_calls`、`stages`
  - 约束 / 预算：`timeout_policy`、`degradation_policy`
  - 规划元数据：`plan_source`、`planning_notes`、`assumptions_used`
  - 预算 / 验证结果：`facet_budget_plan`、`blocked_tool_calls`、`unsupported_facets`
- 结论：当前 `ExecutionPlan` 既是逻辑计划载体，又是执行契约，边界还没拆开
- 证据：`[schemas.py:983-1019](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L983)`

### `EvidencePlannerResult`

- 文件 / 定义：`local_life_agent/planning/evidence/facet_budget.py:33-43`
- 现有字段：
  - `facet_candidates`
  - `validation_result`
  - `budget_plan`
  - `tool_calls`
  - `blocked_tool_calls`
  - `unsupported_facets`
  - `missing_inputs`
  - `planning_warnings`
  - `evidence_top_k`
  - `budget_context_snapshot`
- 结论：它更接近逻辑层“证据需求 + 预算结果”，但当前又被直接塞进 `ExecutionPlan`
- 证据：`[facet_budget.py:33-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L33)`

### `DecisionPlan`

- 文件 / 定义：`local_life_agent/domain/decision.py:280+`
- 现有职责：只基于 `EvidencePack` 产生可回答的最终决策，不再引入新事实
- 结论：它是第二层后段的“证据驱动决策”对象，不是 DAG
- 证据：`[decision.py:280](D:/javacode/hm-dianping/local_life_agent/domain/decision.py#L280)`

### `BudgetContext`

- 文件 / 定义：`local_life_agent/planning/budget/budget_context.py:8-42`
- 现有能力：
  - `snapshot()`
  - `remaining(field)`
  - `record_exhaustion(reason)`
- 结论：预算对象已存在，但当前主要用于 workflow / evidence / response 里的预算读取，而不是统一 DAG 预算
- 证据：
  - `[budget_context.py:8-42](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8)`
  - `[budget_context.py:52-61](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L52)`

## 计划生成与编译现状

### LLM 直接产出 `ExecutionPlan`

当前最关键的边界问题是：

- `plan_evidence_with_llm()` 直接用 `ExecutionPlan.model_validate` 作为 LLM response validator
- 也就是说，LLM 输出已经被当作可执行计划候选，而不是纯逻辑计划

证据：

- `[evidence_planner.py:242-352](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py#L242)`

### 现有“编译器”其实是直接构建执行计划

仓库里没有 `ToolPlanCompiler` 或 `SubTaskDAG`，现有近似编译器主要是：

- `plan_evidence()`
- `plan_evidence_with_llm()`
- `build_recommendation_execution_plan()`
- `build_execution_plan()`
- `evidence_planner_result_to_execution_plan()`

其中 `evidence_planner_result_to_execution_plan()` 直接把 `tool_calls` 包进单 stage 的 `ExecutionPlan`，没有独立 DAG 归一化层。

证据：

- `[facet_budget.py:365-389](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L365)`
- `[execution_plan_builder.py:114-397](D:/javacode/hm-dianping/local_life_agent/planning/plans/execution_plan_builder.py#L114)`
- `[evidence_planner.py:111-239](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py#L111)`

### 距离工具别名归一化当前藏在 planning 子图

`_normalize_distance_tool_calls()` 会把 `get_distance_eta` 归一化为 `calculate_distance_km`，而且是在 `planning_subgraph` 内部做的，不在 compiler 或 gateway adapter。

证据：

- `[planning_subgraph.py:169-203](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L169)`

## Validator 现状

### `ExecutionPlanValidator` 已做的校验

当前验证器已经覆盖：

- 工具是否注册
- `call_id` 是否重复 / 缺失
- 参数 schema 是否匹配
- shop_id 是否由合法 resolver 产生
- `depends_on` 是否引用存在节点
- `depends_on` 是否有环
- 推荐任务下的 forbidden tools
- 最大工具调用数
- 推荐依赖规则

证据：

- `[plan_validator.py:117-182](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L117)`
- `[plan_validator.py:187-255](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L187)`
- `[plan_validator.py:260-300](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L260)`
- `[plan_validator.py:305-330](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L305)`
- `[plan_validator.py:341-345](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L341)`
- `[plan_validator.py:376-383](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L376)`

### `ExecutionPlanValidator` 当前缺口

现有实现里：

- `_check_required_optional` 只是 `pass`
- 没有 `max_parallel_workers` 校验
- 没有 DAG 节点级 `cache_key` 校验
- 没有明确的“required 失败后必须走哪种 degrade/clarify/fallback”的强约束

证据：

- `[plan_validator.py:335-336](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L335)`

## 执行现状

### `ExecutionCore` / `BatchToolExecutor` 只做并发批量，不做 DAG 调度

当前真正执行工具的路径是：

- `ToolBatchExecutor.execute() -> ExecutionCore.execute_batch() -> BatchToolExecutor.execute_sync() -> BatchToolExecutor.execute()`

`BatchToolExecutor.execute()` 只是把 batch call `asyncio.gather` 并发跑掉，没有拓扑排序、没有按 `depends_on` 分层执行、没有 single-flight。

证据：

- `[tool_batch_executor.py:11-21](D:/javacode/hm-dianping/local_life_agent/planning/evidence/tool_batch_executor.py#L11)`
- `[execution_core.py:14-30](D:/javacode/hm-dianping/local_life_agent/core/execution_core.py#L14)`
- `[gateway.py:154-261](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L154)`

### `dispatch_tool_call` 只是网关调用，不含 DAG 元数据

`dispatch_tool_call()` 记录 `tool_name`、`call_id`、`args`、耗时和结果，但没有 DAG 节点 ID、依赖链、cache key、degrade_reason 这类结构化执行轨迹。

证据：

- `[gateway.py:275-321](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L275)`

### `build_evidence()` 只提供 evidence cache，不提供 single-flight

`build_evidence()` 会调用 `EvidenceCache.get_or_build()`，以 `cache_scope + payload fingerprint` 做缓存，但这里是证据构建缓存，不是并发请求去重 / single-flight。

证据：

- `[evidence_builder.py:876-960](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L876)`
- `[evidence_cache.py:47-93](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py#L47)`

## 流程级事实

### `route_orchestration` 不是纯 workflow selector

`route_orchestration()` 当前不仅决定 workflow，还顺手构造：

- `facet_set`
- `facets`
- `target_resolution`
- `router_policy_decision`
- `router_policy_conflicts`
- `comparison_*` 一组字段

这意味着它并不只是“选 workflow”，而是还承担了一部分 route-task 推导和语义侧辅助决策。

证据：

- `[orchestration_router.py:1584-1710](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L1584)`
- `[orchestration_router.py:1501-1565](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L1501)`

### `workflow_runner` 才是真正的工作流分发器

`h_workflow_runner()` 负责：

- registry lookup
- handler dispatch
- fallback patch

因此“Router 只负责选择 workflow”这件事，在现有代码里只部分成立，真正分发发生在 workflow runner。

证据：

- `[workflow_runner.py:97-291](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L97)`

### 简单 / 单店事实路径的现状是 `deterministic_tool_workflow`

仓库中没有 `single_shop_fact_workflow` 这个符号；现有轻量路径是 `run_deterministic_tool_workflow()`，它会：

- 先做单店目标解析
- 再构造 execution plan
- 再 batch 执行
- 再构建 evidence pack 和 answer plan

证据：

- `[deterministic_tool_workflow.py:1046-1234](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L1046)`

## 当前缺失或未找到的模型 / 层

以下命名在当前仓库中没有找到独立实现：

- `ToolPlanCompiler`
- `SubTaskDAG`
- `StageToolExecutor`
- `LogicalEvidencePlan`
- `ExecutionDagTrace`
- `single_shop_fact_workflow`

因此，当前第二层的 DAG 相关能力主要是“分散在多个 planning / executor / gateway / workflow 文件里的字段与函数”，不是一个统一的编译-校验-执行闭环。

## 文档与代码偏差

和用户给出的理想分层相比，真实代码存在以下偏差：

- `LLM / Planner` 现在已经能直接产出 `ExecutionPlan`，不是只产出逻辑计划
- 没有独立 `ToolPlanCompiler`
- `ExecutionStage.depends_on` 和 `ToolCallSpec.depends_on` 已存在，但执行器不按 DAG 拓扑调度
- `route_orchestration` 不仅选 workflow，还构造 router policy 和部分语义辅助字段
- `single_shop_fact_workflow` 不存在，当前轻量路径名称是 `deterministic_tool_workflow`
- 没有统一的 DAG trace schema

---

## 补充 1：`_routes.py` 路由函数矩阵

`local_life_agent/engine/_routes.py` 中与第二层路由相关的函数：

### `_route_workflow_runner`（行 ~311-320）

```python
if workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison":
    return "planning_subgraph"
return "response_subgraph"
```

**三重判定含义**：
- `workflow_name == "discovery_decision"` — 主链路 workflow 路由
- `workflow_callable == "planning_subgraph"` — 兜底：只要 handler 是 planning_subgraph 就进
- `response_mode == "comparison"` — **隐藏路由**：即使 workflow 不是 discovery_decision，只要 response_mode 有 comparison 标志，仍然进入 planning_subgraph

**读字段**：`workflow_name`、`workflow_callable`、`response_mode`
**写字段**：无（返回路由目标字符串）

### `_route_decision_review`（行 ~174-205）

从 `decision_review` 节点路由：

| next_action | 路由目标 |
|---|---|
| `FINISH` | `response_subgraph` |
| `REPLAN_EVIDENCE` | `planning_subgraph`（retry） |
| `EXPAND_SEARCH` | `expand_search`（放宽约束） |
| `CLARIFY` | `clarify_response` |
| `FALLBACK` | `fallback_answer` |

**读字段**：`next_action`（来自 decision_review）
**写字段**：无

### `_route_evidence_review`（行 ~212-257）

从 `evidence_review` 节点路由：

| next_action | 路由目标 |
|---|---|
| `FINISH` | continue to decision_planner |
| `REPLAN_EVIDENCE` | `planning_subgraph` |
| `EXPAND_SEARCH` | `expand_search` |
| `CLARIFY` | `clarify_response` |
| `FALLBACK` | `fallback_answer` |
| `DEGRADE_ANSWER` | degrade path |

**读字段**：`next_action`（来自 evidence_review）
**写字段**：无

### `_route_execution_review`

从 `execution_review_subgraph` 整体路由，返回 `_route_decision_review` 或 `_route_evidence_review` 的结果。

---

## 补充 2：State 字段逐节点读写矩阵

| 节点 | 读取字段 | 写入字段 | 文件/行号 |
|---|---|---|---|
| `route_orchestration` | `user_input`, `session_state`, `facets` | `workflow_name`, `facet_set`, `facets`, `target_resolution`, `router_policy_decision`, `router_policy_conflicts`, `comparison_*` 组字段 | `orchestration_router.py:1584-1710` |
| `orchestration_router_shadow` | `workflow_name`, `response_mode`, `next_action` | `workflow_name`, `response_mode`, `next_action`（直接透传，加 log） | `orchestration_router_shadow.py:20-79` |
| `workflow_runner` | `workflow_name`, `workflow_callable`, `response_mode` | dispatch result, `_orm_decisions`（部分补丁） | `workflow_runner.py:97-291` |
| `_h_goal_planner` | `user_input`, `session_state`, `facets`, `facet_set`, `target_resolution` | `goal_plan`, `execution_plan`, `goal_plan_raw` | `planning_subgraph.py:253-483` |
| `_h_goal_review` | `goal_plan` | `goal_review_result`, `next_action` | `planning_subgraph.py:493-535` |
| `_h_target_resolve` | `goal_plan`, `target_resolution`, `user_input` | `target_resolution`（增强）, `candidate_set`, `pending_clarification`, `pending_candidate_targets` | `planning_subgraph.py:539-760`（核心）, `571-760`（外部） |
| `_h_evidence_planner` | `target_resolution`, `facets`, `facet_set`, `goal_plan` | `execution_plan`（tool_calls, stages, dependencies） | `planning_subgraph.py:1138-1256` |
| `_h_plan_validator` | `execution_plan`, `target_resolution` | `validation_result` | `planning_subgraph.py:1259-1300` |
| `_h_tool_execute` | `execution_plan.tool_calls`, `execution_plan.stages` | `tool_results`, `search_results`, `batch_dispatch_records` | `execution_review_subgraph.py:111-206` |
| `_h_evidence_build` | `tool_results`, `goal_plan` | `evidence_pack` | `execution_review_subgraph.py:210-241` |
| `_h_evidence_review` | `evidence_pack`, `goal_plan`, `session_state` | `review_results`, `next_action`, `session_state.review_results` | `execution_review_subgraph.py:244-292` |
| `_h_decision_planner` | `evidence_pack`, `goal_plan`, `review_results` | `decision_plan` | `execution_review_subgraph.py:295-342` |
| `_h_decision_review` | `decision_plan`, `evidence_pack`, `session_state` | `review_results`, `next_action` | `execution_review_subgraph.py:345-377` |

---

## 补充 3：Workflow Registry 完整矩阵

当前 `LEGAL_WORKFLOW_NAMES`（`workflow_registry.py:24-30`）只允许 5 个名称：

| 注册名 | entry_node | handler | 是否真实执行工具 | 当前路由路径 |
|---|---|---|---|---|
| `discovery_decision` | `planning_subgraph` | `_dispatch_discovery_decision` | 是（通过 planning_subgraph） | `_routes.py` 三重判定 → planning_subgraph |
| `deterministic_tool` | `response_subgraph` | `run_deterministic_tool_workflow` | 是 | `_routes.py` → response_subgraph |
| `direct_response` | `response_subgraph` | `run_direct_response_workflow` | 否 | `_routes.py` → response_subgraph |
| `clarification_fallback` | `response_subgraph` | `run_clarification_fallback_workflow` | 否 | `_routes.py` → response_subgraph |
| `exploration_planning` | `response_subgraph` | `run_exploration_planning_workflow` | 是 | `_routes.py` → response_subgraph |

**关键注意**：
- `_dispatch_discovery_decision`（`workflow_registry.py:139-149`）并不直接执行工具，只是返回 dispatch patch，真实执行在 `planning_subgraph` 内部
- `discovery_decision` 是唯一 entry_node 为 `planning_subgraph` 的 workflow
- `deterministic_tool`、`direct_response`、`clarification_fallback`、`exploration_planning` 的 entry_node 都是 `response_subgraph`

---

## 补充 4：`expand_search` 清除 filters 的事实

**已确认风险**。`_h_expand_search`（`planning_subgraph.py:1304-1346`）的 relax 逻辑：

```python
# planning_subgraph.py:1319-1325（已验证）
relaxed.filters = {}      # 清空所有过滤条件
relaxed.sort_by = []      # 清空所有排序条件
```

这意味着：
- 用户设置的品类（如"火锅"）丢失
- 用户设置的位置范围丢失
- 用户设置的预算上限丢失
- 用户设置的营业状态要求丢失
- `expand_search` 的计数器通过 `SessionState.replan_counters["expand_search"]` 控制，上限 `MAX_EXPAND_SEARCH_ROUNDS=1`（`config.py:213`）

---

## 补充 5：retry/replan 计数器跨轮污染事实

```python
# state.py:136-140
replan_counters: dict[str, int] = Field(default_factory=lambda: {
    "expand_search": 0,
    "replan_evidence": 0,
    "rewrite": 0,
})
```

**风险说明**：
- 计数器在 `SessionState` 中跨轮持久化
- 如果第 N 轮 query 用尽 `expand_search`，第 N+1 轮继承已耗尽计数器
- 导致后续 query 错误降级（无法 expand_search）
- 计数器递增函数在 `replan_policy.py:133-148`（`increment_replan_evidence` / `increment_expand_search`）

与 `BudgetContext`（`budget_context.py:8-62`）的对比：
- `BudgetContext` 是 per-workflow 运行时预算，不会跨轮
- `SessionState.replan_counters` 是跨轮持久化的，与 BudgetContext 语义不同

---

## 补充 6：EvidencePack 完整字段

`schemas.py:1101-1167`:

```python
class EvidencePack(BaseModel):
    items: list[EvidenceItem]                  # 证据条目列表
    summary: str | None = None                 # 证据摘要
    evidence_quality: str = "unknown"          # 证据质量评级
    coverage_gaps: list[str] = Field(default_factory=list)  # 覆盖缺口
    confidence_score: float = 0.0              # 置信度
    ranking_policy: RankingPolicy | None = None  # 排序策略
    ranking_explanation: str | None = None     # 排序说明
    freshness_assessment: str | None = None    # 新鲜度评估
    source_diversity: float = 0.0              # 来源多样性
    cross_source_conflicts: list[str] = Field(default_factory=list)  # 跨源冲突
    metadata: dict[str, Any] = Field(default_factory=dict)  # 元数据
```

`EvidenceItem`（`schemas.py:1069-1095`）：

```python
class EvidenceItem(BaseModel):
    facet: str                                 # 证据 facet 类型
    value: Any                                 # 证据值
    source: str                                # 来源
    confidence: float = 1.0                    # 置信度
    freshness_class: str = "unknown"           # 新鲜度类别
    ttl_seconds: int | None = None             # TTL
    observed_at_ms: int | None = None          # 观测时间
    is_stale: bool = False                     # 是否过期
    shop_id: str | None = None                 # 关联店铺
    item_type: str = "fact"                    # 条目类型
    supporting_detail: str | None = None       # 支持细节
    citations: list[str] = Field(default_factory=list)  # 引用
```

---

## 补充 7：Trace span 现状

当前可观测性基础设施：

| 能力 | 位置 | 现状 |
|---|---|---|
| `trace_spans` 列表 | `graph_state.py:187`（`Annotated[list, add]`） | 字段已存在，每次追加 |
| `event_log` 列表 | `graph_state.py:185` | 字段已存在，可记录事件 |
| 工具调用日志 | `gateway.py:275-321`（`dispatch_tool_call`） | 记录 `[TOOL_CALL]` 和 `[TOOL_RESULT]`，含耗时 |
| Workflow 选择日志 | `workflow_runner.py` | 记录 workflow dispatch 信息 |
| Plan 日志 | `evidence_planner.py` / `execution_plan_builder.py` | 记录计划生成过程 |

**当前缺失**：
- 没有从"路由→计划→执行→证据→决策→回答"的统一 trace schema
- 没有 DAG 节点级 trace（node_id、depends_on、cache_hit、degrade_reason）
- 没有 stage 级 trace（并行节点数、stage 耗时）
- 没有 reduce trace（evidence 合并、冲突解决、最终决策）
- trace 事件之间缺乏关联 ID（无法串联同一 query 的全链路）

