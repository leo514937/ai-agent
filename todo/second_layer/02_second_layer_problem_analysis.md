# 第二层问题分析

本文件只按当前仓库真实代码做风险分析，不把理想架构当成已实现。

## P0

> **注**：以下是基于当前仓库真实代码确认的 P0 问题。前 8 个为用户明确要求的分析维度，P0-9/P0-10 为保留的原有有效问题。

### P0-1. 轻重链路未分层

- **风险**：简单单店事实 query 走重链路（整个 `planning_subgraph` 1399 行），复杂 query 也被塞进同一个大 `planning_subgraph`。没有轻量/重型的分层机制。
- **真实代码**：
  - `deterministic_tool_workflow` entry_node 是 `response_subgraph`（`workflow_registry.py:176-182`）
  - `discovery_decision` entry_node 是 `planning_subgraph`（`workflow_registry.py:152-164`）
  - `_route_workflow_runner`（`_routes.py:311-320`）中 `response_mode == "comparison"` 会导致比较 query 被重路由回 `planning_subgraph`
- **影响**：简单 query 延迟和成本上升（不必要的 LLM review）；复杂 query 缺乏专门处理链路

### P0-2. `deterministic_tool_workflow` handler 是自包含单体，绕过整个 execution_review_subgraph

**精确问题**：不是"可能过轻"，而是**整个 review 层被绕过**。

- `run_deterministic_tool_workflow`（`deterministic_tool_workflow.py:1223-1411` ~190 行）是一个**自包含单体函数**：
  1. 内部做 target_resolve（`_resolve_single_target`）
  2. 内部做 evidence_plan（`plan_evidence`）
  3. 内部执行工具（`dispatch_tool_call`）
  4. 内部 build_evidence
  5. 内部 compose_answer + verify_answer
  6. 最终以**单次 patch 写 40+ 个 GraphState 字段**返回（`deterministic_tool_workflow.py:1070-1132`）
- entry_node = `"response_subgraph"`（`workflow_registry.py:176-182`）→ 所以不走 `execution_review_subgraph`
- **影响**：
  - ❌ 没有 evidence_review（不走 `_h_evidence_review`，证据是否充分无校验）
  - ❌ 没有 decision_planner（不走 `_h_decision_planner`，决策是否基于证据无校验）
  - ❌ 没有 decision_review（不走 `_h_decision_review`，不产生 `EXPAND_SEARCH`/`REPLAN_EVIDENCE`/`FALLBACK` 信号）
  - ❌ 无法触发 expand_search（搜索结果不足时无法自动放宽）
  - ❌ 无法触发 replan（工具失败时不能重试）
  - ⚠️ 但工具是**真实执行的**，evidence 是**真实构建的**——所以"过轻"不能简单理解为"不查工具"
- **修复方向**：拆出 handler 中的工具执行 + evidence 构建部分与 execution_review_subgraph 共享，但允许 `single_shop_fact` 跳过 LLM-heavy 的 evidence_review 和 decision_planner

### P0-3. 路由权威被策略层覆盖（已不止是命名问题）

**精确问题**：不是"命名不一致"，而是**路由权威被两处策略层覆盖**：

**覆盖点 1**：`_routes.py:311-320` 的 `_route_workflow_runner` 有隐藏路由逻辑，覆盖 Router 的 workflow 选择：
```python
# _routes.py L318：优先级逻辑覆盖 Router 的 workflow_name
if workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison":
    return "planning_subgraph"
return "response_subgraph"
```
- `response_mode == "comparison"` 是 policy 层（`execution_review_subgraph` 的 decision_review）写的字段，不是 Router 的字段
- comparison query 在 Router 中被选为 `comparison_decision` workflow，但 `_route_workflow_runner` 用 `response_mode == "comparison"` 强制重路由回 `planning_subgraph`，绕过了 workflow 路由

**覆盖点 2**：Policy 层（`execution_review_subgraph`）直接改 `next_action`，绕过了 Router：
- `_h_evidence_review` → `next_action = "EXPAND_SEARCH"` 或 `"REPLAN_EVIDENCE"`
- `_h_decision_review` → `next_action = "EXPAND_SEARCH"` / `"REPLAN_EVIDENCE"` / `"CLARIFY"` / `"FALLBACK"`
- 这些 `next_action` 直接决定了下一步路由（`_routes.py:174-210`），不需要 Router 同意
- 意味着 policy review 层事实上承担了部分路由决策

**影响**：
1. Router 不决定最终 workflow 选择（`_route_workflow_runner` 覆盖）
2. Policy 层不遵守 Router 的 workflow 分配（review 直接改 next_action）
3. 不存在"受理权在 Router，策略只调参数"的架构边界

### P0-5. （新增）缺少 LogicalEvidencePlan，LLM 直接输出可执行 ExecutionPlan

**精确问题**：当前 `plan_evidence_with_llm`（`evidence_planner.py:242-352`）中，LLM **直接** 输出一个 `ExecutionPlan`（工具调用级别），没有中间的"事实需求分析"层。

**代码路径**：
- `plan_evidence_with_llm` → LLM prompt → `response_validator=ExecutionPlan.model_validate` → 直接验证为可执行计划
- 没有 `LogicalEvidencePlan` DTO 定义"用户问了什么 → 需要哪些事实 → 每个事实用什么工具"

**影响**：
1. LLM 必须同时做两件事：判断"需要什么事实" + 选择"调什么工具获取事实"——在单次 LLM 调用中混合声明性和可执行推理，更容易出错
2. LLM 输出非法 `tool_name` / 幻觉 `shop_id` / 错误 `args` 时，直接被 `ExecutionPlan.model_validate` 接收 → 只有 schema 级别校验，没有"事实需求是否合理"级别校验
3. 没有可审计的中间产物：无法回答"LLM 认为需要查什么事实，它选择了哪些工具来查"
4. deterministic 路径（`plan_evidence`）也一样，没有 logical 层

**修复方向**：引入 `LogicalEvidencePlan`（声明性："需要 coupon + open_status for shop X"），由 `ToolPlanCompiler` 编译为 `ExecutionPlan`（可执行："call get_coupon_list(shop_id=X) + check_open_status(shop_id=X) in parallel"）

### P0-6. `expand_search` 放宽策略过粗

- **风险**：清空 `filters` 和 `sort_by`，丢失所有硬约束。
- **真实代码**：`planning_subgraph.py:1319` — `relaxed.filters = {}`；`planning_subgraph.py:1320` — `relaxed.sort_by = []`
- **影响**：品类的约束、预算上限、营业状态要求全部丢失

### P0-6. retry/replan 计数放在 SessionState

- **风险**：`SessionState.replan_counters` 跨轮持久化，当前轮预算污染后续 query。
- **真实代码**：
  - `state.py:136-140` — `replan_counters` 在 SessionState
  - `replan_policy.py:133-148` — 递增计数器
  - `config.py:213-215` — `MAX_EXPAND_SEARCH_ROUNDS=1`
- **影响**：turn N 耗尽 expand_search 后，turn N+1 继承已耗尽计数器，错误降级

### P0-7. RankingPolicy 不可执行，推荐排序缺少确定性执行引擎

**精确问题**：不是"权威不清"，而是 **RankingPolicy 当前是描述性标签，不是可执行的排序规则**。

**当前代码**（`facets.py:102-105`）：
```python
class RankingPolicy(BaseModel):
    primary_facets: list[str]            # 描述：["distance", "rating"]
    secondary_facets: list[str]          # 描述：["coupon"]
    tradeoff_notes: list[str]            # 描述：["价格 vs 距离"]
```

**缺少的能力**（导致不可执行）：

| 缺少项 | 影响 |
|---|---|
| `hard_filters: list[HardConstraintRule]` | 没有硬约束过滤规则结构，当前 `_h_expand_search` 直接 `filters = {}` 清空所有约束 |
| `objective_weights: dict[str, float]` | 没有客观评分权重，无法确定性计算综合得分 |
| `score_normalization: dict[str, str]` | 距离是米、评分是 0-5、评价数是整数——不同 facet 量纲不同，缺归一化策略 |
| `tie_breakers: list[str]` | 同分时没有决胜策略，可能靠 LLM 随机选 |
| `scoring_provenance: list[ScoreProvenance]` | 排序结果没有来源追溯：每个 shop 的每个 facet 分数是工具算的还是 LLM 猜的 |
| `max_boost_cap: float` | 软偏好可能无限叠加，压过硬约束 |

**影响**：
1. 推荐排序只能靠 LLM 在 `plan_decision_with_llm` 或 `review_evidence_with_llm` 中隐式完成
2. 无法保证推荐结果不违反硬约束（品类、预算、营业状态）
3. 无法审计"为什么 A 排在 B 前面"，排序结果不可调试
4. 对比 query 的 winner 选择也没有确定性依据，靠 LLM 凭印象选 winner

### P0-8. MapReduce 缺少结构化 reducer 契约（⚠️ 第二阶段实施，非首批）

> **优先级说明**：MapReduce / complex_orchestrator 是第二层**第二阶段**的能力。第一批实施应聚焦：单店事实工具稳定、推荐不违反硬约束、对比 winner 不乱、工具调用不重复、response 不绕过证据。MapReduce 的 reducer 契约可以先设计但**不要求在 Phase 1 实现**。

- **风险**：复杂 query 多 workflow 并行时，最终回答可能变成自然语言片段拼接，产生冲突和重复。
- **真实代码**：
  - 无 `WorkerResult` — handler 返回 dict 直接 patch GraphState（`workflow_registry.py:139-149`）
  - 无 `EvidenceReducer` — 当前仅在单 workflow 内构建 EvidencePack
  - 无 `DecisionReducer` — `DecisionPlan` 在单 workflow 内生成（`execution_review_subgraph.py:295-342`）
- **影响**：超复杂 query 无法结构化解构和合并（但这类 query 当前占比低，可作为第二阶段优化）

### P0-9. （保留）LLM 输出被直接当成可执行 `ExecutionPlan`

- **风险**：`plan_evidence_with_llm()` 用 `ExecutionPlan.model_validate` 接收 LLM 输出，幻觉内容穿透到可执行层。
- **真实代码**：`evidence_planner.py:242-352`
- **影响**：LLM 输出非法 `tool_name`/`args`/`depends_on` 时打穿执行和规划边界

### P0-10. （保留）执行器并不理解 DAG，只理解 batch

- **风险**：`depends_on` 已存在但执行器只做 batch 并发，不做拓扑调度。
- **真实代码**：`execution_core.py:14-30`、`gateway.py:243-259`
- **影响**：依赖链可能被"平铺后并发"执行，`depends_on` 仅为语义字段

### 1. LLM 输出被直接当成可执行 `ExecutionPlan`

- 风险：`plan_evidence_with_llm()` 直接用 `ExecutionPlan.model_validate` 接收 LLM 输出，导致 LLM 的幻觉内容可能穿透到可执行计划层。
- 真实代码：
  - `[evidence_planner.py:242-352](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py#L242)`
- 影响：
  - LLM 一旦输出了非法 `tool_name`、错误 `args` 或伪造 `depends_on`，就会把执行层和规划层边界打穿

### 2. 执行器并不理解 DAG，只理解 batch

- 风险：`ToolCallSpec.depends_on` 和 `ExecutionStage.depends_on` 已经存在，但 `ExecutionCore.execute_batch()` / `BatchToolExecutor.execute()` 只是并发执行一个列表，不做拓扑排序、层次调度或依赖门控。
- 真实代码：
  - `[execution_core.py:14-30](D:/javacode/hm-dianping/local_life_agent/core/execution_core.py#L14)`
  - `[gateway.py:243-259](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L243)`
- 影响：
  - 依赖链可能被“平铺后并发”执行
  - `depends_on` 目前更像语义字段，不是执行保证

### 3. `route_orchestration` 不是纯 Router

- 风险：Router 既选 workflow，又产出 `facet_set`、`target_resolution`、`router_policy_decision` 和比较上下文，容易让 route 和 plan 之间职责粘连。
- 真实代码：
  - `[orchestration_router.py:1584-1710](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L1584)`
- 影响：
  - Router 逻辑越来越像“轻量 planner”，后续很难收窄到只负责 workflow 选择

### 4. `ExecutionPlanValidator` 还不是完整 DAG 规则门

- 风险：虽然已经检查注册表、参数 schema、shop_id 来源、环、max_tool_calls 等，但还缺少 `max_parallel_workers`、required/fallback 策略、节点级 cache/single-flight、LLM 幻觉字段的系统性封堵。
- 真实代码：
  - `[plan_validator.py:155-180](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L155)`
  - `[plan_validator.py:214-255](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L214)`
  - `[plan_validator.py:305-345](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L305)`
  - `[plan_validator.py:335-336](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L335)`
- 影响：
  - 计划可以“形式上合法、执行时仍失控”

### 5. 没有统一 DAG Trace

- 风险：现在只有 tool log、plan log、evidence log、workflow log，没有一个能串起 DAG 节点、stage、依赖、cache、降级的统一 trace schema。
- 真实代码：
  - `dispatch_tool_call()` 只记录工具入参和结果 `[gateway.py:275-321](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L275)`
  - `ExecutionPlan` 没有 DAG trace 字段 `[schemas.py:983-1019](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L983)`
- 影响：
  - 出现非法工具、预算超限、缓存命中异常、降级路径时，不容易还原“为什么这么跑”

## P1

### 6. 工具别名归一化藏在 planning_subgraph 内

- 风险：`get_distance_eta` / `calculate_distance_km` 的归一化逻辑现在在 `planning_subgraph._normalize_distance_tool_calls()` 里，既不是编译器，也不是 gateway adapter。
- 真实代码：
  - `[planning_subgraph.py:169-203](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L169)`
- 影响：
  - tool alias 规则会被散落在不同 planning 分支里

### 7. 没有 single-flight 去重

- 风险：同一 `cache_key` 的并发请求可能重复打真实工具，尤其是同店券 / 营业 / 距离这类高频字段。
- 真实代码：
  - `EvidenceCache.get_or_build()` 只管 evidence build cache，不是并发 single-flight `[evidence_cache.py:47-93](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py#L47)`
  - `BatchToolExecutor.execute()` 只是 `asyncio.gather` `[gateway.py:243-259](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L243)`
- 影响：
  - 重复真实工具调用，浪费预算和时延

### 8. 逻辑计划与执行计划混在一个 `ExecutionPlan` 里

- 风险：`ExecutionPlan` 同时装了 facets、budget、tool_calls、stages、timeout_policy、degradation_policy、facet_budget_result 等，导致它既像逻辑计划又像执行计划。
- 真实代码：
  - `[schemas.py:983-1019](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L983)`
- 影响：
  - 不利于形成“LLM 只出逻辑计划，compiler 负责可执行化”的硬边界

### 9. 轻量事实路径的命名不统一

- 风险：用户提出的 `single_shop_fact_workflow` 在仓库里不存在，当前对应的是 `deterministic_tool_workflow`。
- 真实代码：
  - `[deterministic_tool_workflow.py:1046-1234](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L1046)`
- 影响：
  - 讨论“轻量路径”和“DAG 大链路”时容易产生语义偏差

### 10. Budget / freshness / cache 语义分散

- 风险：预算和 freshness 已经存在，但分散在 `BudgetContext`、`FacetBudgetPlan`、`EvidenceCache`、`build_evidence()`、`deterministic_tool_workflow`、`response_subgraph` 中，不是统一的第二层资源模型。
- 真实代码：
  - `[budget_context.py:8-61](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8)`
  - `[facet_budget.py:21-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L21)`
  - `[evidence_builder.py:876-960](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L876)`
- 影响：
  - 预算和 freshness 很难在 DAG 层统一校验和统一观测

## P2

### 11. 现有测试有边界覆盖，但缺 DAG 编译 / 执行 / trace 专项

- 风险：已有测试能验证部分 validator、workflow boundary、deterministic workflow，但没有专门覆盖非法 DAG、cache key 去重、stage trace、max_parallel_workers。
- 现有测试：
  - `test_execution_plan_validator.py`
  - `test_planning_execution_boundary.py`
  - `test_deterministic_tool_workflow.py`
  - `test_workflow_runner.py`
  - `test_p9_evidence_planner_capability_budget.py`
  - `test_p12_deadline_budget_freshness_ttl.py`

### 12. `ExecutionPlanValidator._check_required_optional` 仍是空实现

- 风险：required/optional 的失败策略目前不是真正由 validator 约束。
- 真实代码：
  - `[plan_validator.py:335-336](D:/javacode/hm-dianping/local_life_agent/planning/plans/plan_validator.py#L335)`

### 13. LLM 幻觉字段缺少统一拦截语义

- 风险：现在 validator 主要看 schema / registry / shop_id / cycles；对“LLM 猜出来的额外字段”缺少统一的字段白名单 / 限定输出契约。
- 真实代码：
  - `plan_evidence_with_llm()` 直接验证 `ExecutionPlan` `[evidence_planner.py:242-352](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py#L242)`
  - `ToolCallSpec` 本身只有固定字段 `[schemas.py:964-980](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L964)`

### 14. Router / workflow boundary 的责任不够清晰

- 风险：`route_orchestration`、`workflow_runner`、`planning_subgraph` 之间的边界仍有交叉，后续如果再在 Router 里塞 DAG 解析逻辑，会继续膨胀。

## 文档与代码偏差

以下是用户给出的目标架构与当前真实代码之间的偏差，后续方案需要按真实代码收敛：

- 当前没有 `ToolPlanCompiler`
- 当前没有 `SubTaskDAG`
- 当前没有 `StageToolExecutor`
- 当前没有 `LogicalEvidencePlan`
- 当前没有 `ExecutionDagTrace`
- 当前没有 `single_shop_fact_workflow`
- 当前的 `route_orchestration` 不是纯 workflow selector
- 当前的 LLM evidence planner 可以直接产出 `ExecutionPlan`
- 当前的执行器只会 batch 并发，不会基于 DAG 拓扑执行

