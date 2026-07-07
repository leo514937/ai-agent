# 第二层契约设计

本文件只描述建议契约和归属，不删除旧字段。

## 契约总览

| 契约 | 类型建议 | 权威归属 | 说明 |
|---|---|---|---|
| `LogicalEvidencePlan` | Domain DTO | `GraphState` 中间态 / LLM 输出 | 只描述逻辑计划，不含真实工具调用 |
| `EvidenceNeed` | Domain DTO | `LogicalEvidencePlan` | 描述需要什么证据 |
| `RequiredFacet` | Domain DTO | `LogicalEvidencePlan` | 描述哪些 facet 必须满足 |
| `SubTask` | Domain DTO | `LogicalEvidencePlan` | 描述逻辑子任务和业务依赖 |
| `ExecutionPlan` | Domain DTO / Executable Contract | `GraphState` 中间态 | 由 compiler 产出，进入 validator / executor |
| `ExecutionStage` | Domain DTO | `ExecutionPlan` | stage 级调度单元 |
| `ToolCallSpec` | Domain DTO | `ExecutionPlan` / `ExecutionStage` | 真实工具调用节点 |
| `ExecutionBudget` | Domain DTO | `GraphState` 中间态 / budget service | 统一 max_tool_calls / max_parallel_workers / deadline |
| `ExecutionDagTrace` | Observability / Trace | `GraphState` trace 或独立 trace 表 | 记录 DAG 节点和 stage 执行情况 |
| `ToolInvocationRecord` | Observability / Trace | `ExecutionDagTrace` | 记录单工具调用结果 |
| `ToolPlanCompiler` | Service | planning layer | 逻辑计划到执行计划的唯一编译器 |
| `PlanValidator` | Service | planning layer | DAG 合法性门 |
| `StageToolExecutor` | Service | execution layer | 按 DAG 执行 stage 和工具节点 |

## 1. `LogicalEvidencePlan`

### 目的

- 作为 LLM / Planner 的输出契约
- 只允许表达逻辑意图，不允许直接表达真实工具调用

### 建议字段

```python
LogicalEvidencePlan:
    plan_id: str
    task_type: str
    evidence_needs: list[EvidenceNeed]
    required_facets: list[str]
    optional_facets: list[str]
    subtasks: list[SubTask]
    budget_hint: dict[str, Any]
    assumptions_used: list[str]
    warnings: list[str]
```

### 归属

- `Domain DTO`
- 作为 `GraphState` 中间态
- 作为 LLM response validator 的目标对象

## 2. `EvidenceNeed`

### 目的

- 统一表达“需要哪类证据”

### 建议字段

```python
EvidenceNeed:
    facet: str
    required: bool
    priority: int
    source: str
```

### 归属

- `Domain DTO`
- 只存在于逻辑层

## 3. `RequiredFacet`

### 目的

- 从证据需求中抽离必需 facet 的概念

### 建议字段

```python
RequiredFacet:
    name: str
    required: bool
    preferred_tool: str | None
    reason: str
```

### 归属

- `Domain DTO`

## 4. `SubTask`

### 目的

- 表达子任务及其业务依赖，不直接绑定具体工具

### 建议字段

```python
SubTask:
    subtask_id: str
    kind: str
    depends_on: list[str]
    inputs: dict[str, Any]
    outputs: list[str]
    required: bool
```

### 归属

- `Domain DTO`
- 由 `ToolPlanCompiler` 编译为 `ExecutionStage` / `ToolCallSpec`

## 5. `ExecutionPlan`

### 现状

- 现在已存在，但承担了太多职责

### 建议收敛后字段

```python
ExecutionPlan:
    plan_id: str
    task_type: str
    facets: list[QueryFacet]
    optional_facets: list[str]
    target_resolution: TargetResolutionResult | None
    conflicting_facets: list[ConflictingFacet]
    ranking_policy: RankingPolicy | None
    dependencies: list[str]
    stages: list[ExecutionStage]
    tool_calls: list[ToolCallSpec]
    target_shop_ids: list[str]
    plan_source: str
    timeout_policy: dict[str, Any]
    degradation_policy: dict[str, Any]
```

### 归属

- `GraphState` 中间态
- `ToolPlanCompiler` 的输出
- `PlanValidator` 的输入
- `StageToolExecutor` 的输入

### 兼容派生字段

以下字段建议继续保留过渡期兼容，但不作为权威源：

- `blocked_tool_calls`
- `unsupported_facets`
- `facet_budget_plan`
- `evidence_planner_result`
- `planning_notes`
- `assumptions_used`

## 6. `ExecutionStage`

### 现有字段

- `stage_id`
- `description`
- `tool_names`
- `depends_on`
- `max_parallelism`

### 建议补强

```python
ExecutionStage:
    stage_id: str
    description: str
    tool_names: list[str]
    depends_on: list[str]
    max_parallelism: int
    required: bool
    degrade_policy: str
```

### 归属

- `Domain DTO`
- 进入 DAG trace

## 7. `ToolCallSpec`

### 现有字段

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

### 建议补强

```python
ToolCallSpec:
    cache_key: str
    degrade_policy: dict[str, Any]
    node_id: str
    tool_alias_source: str
```

### 归属

- `Domain DTO`
- 真实执行节点

## 8. `ExecutionBudget`

### 目的

- 统一第二层预算概念

### 建议字段

```python
ExecutionBudget:
    max_tool_calls: int
    max_parallel_workers: int
    deadline_ms: int | None
    remaining_tool_calls: int
    remaining_parallel_workers: int
    remaining_time_ms: int | None
    cache_scope: dict[str, Any]
```

### 归属

- `GraphState` 的预算中间态
- 可由现有 `BudgetContext` 兼容映射

## 9. `ExecutionDagTrace`

### 目的

- 记录可执行 DAG 的完整执行轨迹

### 建议字段

```python
ExecutionDagTrace:
    plan_id: str
    workflow_name: str
    stage_id: str
    node_id: str
    tool_name: str
    depends_on: list[str]
    status: str
    latency_ms: int | None
    cache_hit: bool
    error: str
    degrade_reason: str
```

### 归属

- `Observability / Trace`
- 不应作为业务事实源

## 10. `ToolInvocationRecord`

### 目的

- 记录单工具节点执行细节

### 建议字段

```python
ToolInvocationRecord:
    node_id: str
    tool_name: str
    call_id: str
    status: str
    latency_ms: int | None
    cache_hit: bool
    error_code: str
    error_message: str
    degrade_reason: str
```

### 归属

- `Observability / Trace`

## 11. `ToolPlanCompiler`

### 目的

- 这是服务，不是 DTO

### 责任边界

- 输入：`LogicalEvidencePlan`
- 输出：`ExecutionPlan`
- 处理：
  - 工具白名单映射
  - 参数 schema 填充
  - shop_id 来源绑定
  - `depends_on` 生成
  - `cache_key` 生成
  - `required/optional` 标记
  - `timeout_ms / retry_policy / degrade_policy`
  - alias 归一化

### 归属

- `planning` 层服务
- 不是 `GraphState` / `SessionState` 的权威字段

## 兼容字段原则

以下字段应视为兼容派生，不应作为未来唯一权威：

- `execution_plan` 内的 LLM 原始回填内容
- `evidence_planner_result`
- `facet_budget_plan`
- `blocked_tool_calls`
- `router_policy_decision`
- `router_policy_conflicts`
- `workflow_candidate_reason`

## 对现有结构的映射建议

- `GraphState`
  - 持有 `LogicalEvidencePlan`、`ExecutionPlan`、`ExecutionBudget`、`ExecutionDagTrace`
- `SessionState`
  - 只保留跨轮、可复用、可过期的上下文，不保存 DAG 节点执行细节
- `Domain DTO`
  - `LogicalEvidencePlan`、`EvidenceNeed`、`RequiredFacet`、`SubTask`、`ExecutionPlan`、`ExecutionStage`、`ToolCallSpec`、`ExecutionBudget`
- `Observability / Trace`
  - `ExecutionDagTrace`、`ToolInvocationRecord`

## 12. 补充契约对象清单

下面这批对象是为了把“逻辑计划”“可执行 DAG”“运行时 trace”进一步拆开，和当前仓库里已经存在的 `ExecutionPlan`、`ToolCallSpec`、`EvidencePack`、`DecisionPlan`、`BudgetContext` 形成过渡兼容。

| 契约 | 类型建议 | 归属建议 | 说明 |
|---|---|---|---|
| `TaskComplexity` | Domain DTO | `GraphState` 中间态 | 描述简单 / 中等 / 复杂 / 超复杂 query 的分级结果 |
| `WorkflowKind` | Domain DTO | `GraphState` 中间态 | 描述 `direct_response` / `single_shop_fact` / `recommendation` / `comparison` / `exploration` / `complex_orchestrator` |
| `ReviewPolicy` | Domain DTO | 配置 / 策略层 | 控制是否进入 goal review / evidence review / decision review |
| `ExpandSearchPolicy` | Domain DTO | 配置 / 策略层 | 控制放宽顺序和保留硬约束的规则 |
| `RankingPolicy` | Domain DTO | `ExecutionPlan` / `DecisionPlan` 中间态 | 推荐排序权威，不直接等同于 LLM 结论 |
| `ToolCallCacheKey` | Domain DTO | `ToolResultCache` / `GraphState` trace | 统一表达单次工具调用缓存键 |
| `ToolResultCacheEntry` | Domain DTO | 缓存层 | 记录真实工具调用结果、TTL、来源、命中状态 |
| `EvidenceCacheEntry` | Domain DTO | 缓存层 | 记录证据构建缓存结果 |
| `SubTask` | Domain DTO | `LogicalEvidencePlan` / `SubTaskDAG` | 逻辑子任务，不直接绑定真实工具 |
| `SubTaskDAG` | Domain DTO | `GraphState` 中间态 | 逻辑层 DAG，不允许直接执行 |
| `WorkerState` | Domain DTO | worker 局部态 | 只在 worker 内使用，禁止直接写 `SessionState` |
| `WorkerResult` | Domain DTO | worker 输出 | 可带 `session_write_proposal`，不能直接持久化 |
| `DecisionFragment` | Domain DTO | reducer 输入 | 结构化决策片段，不是最终回答 |
| `GlobalEvidencePack` | Domain DTO | reducer 输出 | 多 worker 证据合并结果 |
| `EvidenceConflict` | Domain DTO | reducer / trace | 记录证据冲突和冲突来源 |
| `ConflictResolution` | Domain DTO | reducer 输出 | 记录最终裁决逻辑和依据 |
| `FinalDecisionPlan` | Domain DTO | `GraphState` 中间态 / response 输入 | 最终回答依据，不应由多个自然语言片段拼接而来 |
| `WorkflowTrace` | Observability / Trace | `GraphState` trace | 记录 workflow 选择、planner、tool、review 的整体跨度 |
| `ReduceTrace` | Observability / Trace | `GraphState` trace | 记录 map-reduce 合并过程、冲突解决过程、最终裁决过程 |

## 13. 关键归属约束

- `WorkerState` 不允许写 `SessionState`
- `WorkerResult` 可以包含 `session_write_proposal`，但不能直接持久化
- `FinalDecisionPlan` 是最终回答依据
- `GlobalEvidencePack` 是多 workflow 证据合并结果
- `EvidenceConflict` 用于记录多个 workflow 的事实冲突
- `ConflictResolution` 不能简单投票，必须基于 `source`、`freshness`、`required`、`confidence`、`hard constraint` 优先级裁决
- `ExecutionPlan` / `ToolCallSpec` 可以继续作为兼容权威字段，但未来应由 `ToolPlanCompiler` 输出后再进入 `PlanValidator`

## 14. 对当前实现的收敛建议

- `GraphState` 中新增的这些对象都应是“中间态 + trace”，不是最终事实源
- `SessionState` 只能承载跨轮上下文，不承载 DAG 级执行状态
- `domain/schemas.py` 中现有的 `ExecutionPlan`、`ExecutionStage`、`ToolCallSpec` 可保留兼容字段，但要逐步收缩"逻辑计划"和"可执行计划"的混用

---

## 15. 新增契约对象设计（补充）

以下 17 个契约是当前文档缺少、用户明确要求设计的。

### 15.1 `TaskComplexity`

| 维度 | 说明 |
|---|---|
| **Purpose** | 描述 query 复杂度分级，用于 Router 选择 workflow |
| **Domain** | GraphState 中间态 |
| **Ownership** | `active_orchestration_router` 输出 |

```python
class TaskComplexity:
    task_type: str  # "simple_single_fact" / "recommendation" / "comparison" / "exploration" / "super_complex"
    complexity_level: str  # "simple" / "medium" / "complex" / "super_complex"
    estimated_llm_calls: int
    estimated_tool_calls: int
    suggested_workflow: str
    dimensions: dict  # 复杂度判定维度明细
```

### 15.2 `WorkflowKind`

| 维度 | 说明 |
|---|---|
| **Purpose** | 枚举 workflow 类型，用于路由和策略选择 |
| **Domain** | Domain DTO |

```python
class WorkflowKind(str, enum):
    DIRECT_RESPONSE = "direct_response"
    CLARIFICATION = "clarification"
    SINGLE_SHOP_FACT = "single_shop_fact"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    EXPLORATION_PLANNING = "exploration_planning"
    COMPLEX_ORCHESTRATOR = "complex_orchestrator"
```

### 15.3 `ReviewPolicy`

| 维度 | 说明 |
|---|---|
| **Purpose** | 控制每个 review 节点的强度，不同 workflow 不同配置 |
| **Domain** | 配置/策略层 |

```python
class ReviewPolicy:
    workflow_kind: WorkflowKind
    goal_review: str  # "skip" / "deterministic" / "conditional" / "required"
    evidence_review: str  # "skip" / "deterministic" / "required" / "per_subtask_optional"
    decision_planner: str  # "deterministic" / "hybrid" / "LLM" / "reduce_llm"
    decision_review: str  # "skip" / "deterministic_sanity_check" / "required"
```

### 15.4 `ExpandSearchPolicy`

| 维度 | 说明 |
|---|---|
| **Purpose** | 控制搜索放宽的顺序、哪些约束可放宽、哪些必须保留 |
| **Domain** | 配置/策略层 |

```python
class ExpandSearchPolicy:
    max_expand_rounds: int
    relax_steps: list[str]  # ["increase_limit", "expand_radius", "relax_soft_preferences", "retain_hard_constraints", "report_relaxations"]
    preserve_hard_constraints: bool = True
    expand_radius_by: float = 1.5  # 半径倍数
    increase_limit_by: int = 5     # limit增量
    max_radius_m: int = 5000
```

### 15.5 `ToolCallCacheKey`

| 维度 | 说明 |
|---|---|
| **Purpose** | 工具调用缓存键，用于 ToolResultCache 和 single-flight |
| **Domain** | Domain DTO |

```python
class ToolCallCacheKey:
    tool_name: str
    normalized_args: dict
    shop_id: str | None
    facet: str | None
    cache_scope: str  # "session" / "workflow" / "global"
```

### 15.6 `ToolResultCacheEntry`

| 维度 | 说明 |
|---|---|
| **Purpose** | 缓存单个工具调用结果 |
| **Domain** | 缓存层 |

```python
class ToolResultCacheEntry:
    cache_key: ToolCallCacheKey
    result: Any
    ttl_ms: int
    created_at: int  # timestamp ms
    source_workflow: str
    hit_count: int = 0
    is_stale: bool = False
```

### 15.7 `EvidenceCacheEntry`

| 维度 | 说明 |
|---|---|
| **Purpose** | 证据构建缓存 |
| **Domain** | 缓存层 |

```python
class EvidenceCacheEntry:
    cache_scope: str
    fingerprint: str
    evidence_result: EvidencePack
    ttl_ms: int
    created_at: int
```

### 15.8 `SubTask`（DAG 级版本）

| 维度 | 说明 |
|---|---|
| **Purpose** | DAG 级子任务，包含完整的执行元数据 |
| **Domain** | Domain DTO, complex_orchestrator_workflow |

```python
class SubTask:
    subtask_id: str
    kind: str  # "search" / "detail" / "coupon" / "distance" / "compare" / "plan"
    depends_on: list[str]     # DAG 依赖
    inputs: dict
    outputs: list[str]        # 预期 evidence facet 列表
    required: bool
    timeout_ms: int | None
    retry_policy: str | dict | None
    degrade_policy: str | dict | None
    cache_key: str | None
    mapped_workflow: str | None  # workflow_mapper 分配的目标 workflow
```

### 15.9 `SubTaskDAG`

| 维度 | 说明 |
|---|---|
| **Purpose** | 子任务 DAG，包含拓扑结构和执行调度信息 |
| **Domain** | GraphState 中间态 |

```python
class SubTaskDAG:
    subtasks: list[SubTask]
    entry_points: list[str]   # 无依赖的起始节点
    execution_order: list[list[str]]  # 拓扑排序后的层级
    parallel_groups: list[list[str]]  # 可并行的节点组
    metadata: dict
```

### 15.10 `WorkerState`

| 维度 | 说明 |
|---|---|
| **Purpose** | worker 局部状态，隔离于 SessionState |
| **Domain** | worker 局部态 |

```python
class WorkerState:
    worker_id: str
    assigned_subtask: SubTask
    local_tool_results: dict[str, Any]
    local_evidence: dict[str, Any]
    status: str  # "running" / "success" / "failed" / "degraded"
    error: str | None
    
    # 禁止：直接写 SessionState 或直接修改 GraphState
```

### 15.11 `WorkerResult`

| 维度 | 说明 |
|---|---|
| **Purpose** | worker 输出，结构化非自然语言 |
| **Domain** | Domain DTO, reducer 输入 |

```python
class WorkerResult:
    worker_id: str
    subtask_id: str
    evidence_pack: EvidencePack | None
    decision_fragment: DecisionFragment | None
    session_write_proposal: dict | None  # 不能直接持久化
    status: str
    errors: list[str]
    tool_call_count: int
    latency_ms: int
```

### 15.12 `DecisionFragment`

| 维度 | 说明 |
|---|---|
| **Purpose** | 结构化决策片段，不是最终回答 |
| **Domain** | Domain DTO, reducer 输入 |

```python
class DecisionFragment:
    fragment_id: str
    source_worker: str
    shop_ids: list[str]
    ranking: list[RankedShop] | None
    winner_shop_id: str | None
    claims: list[str]
    caveats: list[str]
    confidence: float
```

### 15.13 `GlobalEvidencePack`

| 维度 | 说明 |
|---|---|
| **Purpose** | 多 worker 证据合并结果 |
| **Domain** | Domain DTO, reducer 输出 |

```python
class GlobalEvidencePack:
    evidence_items: list[EvidenceItem]  # 去重合并后的证据
    source_map: dict[str, str]  # item_id -> worker_id
    coverage_gaps: list[str]
    cross_source_conflicts: list[EvidenceConflict]
    dedup_count: int
    merge_count: int
```

### 15.14 `EvidenceConflict`

| 维度 | 说明 |
|---|---|
| **Purpose** | 记录同一 facet 上多个来源的证据冲突 |
| **Domain** | Domain DTO, reducer/trace |

```python
class EvidenceConflict:
    conflict_id: str
    facet: str
    shop_id: str
    value_a: Any
    value_b: Any
    source_a: str   # 来源 worker/workflow
    source_b: str
    freshness_a: int
    freshness_b: int
    severity: str  # "high" / "medium" / "low"
    source_type_a: str  # "TOOL" / "LLM" / "VERIFIED"
    source_type_b: str
```

### 15.15 `ConflictResolution`

| 维度 | 说明 |
|---|---|
| **Purpose** | 冲突裁决结果 |
| **Domain** | Domain DTO, reducer 输出 |

```python
class ConflictResolution:
    conflict_id: str
    resolution: str  # "use_a" / "use_b" / "tradeoff" / "unknown"
    reason: str      # 裁决理由
    resolver: str    # "rule_based" / "llm_assisted" / "human"
    resolved_at_ms: int
```

### 15.16 `FinalDecisionPlan`

| 维度 | 说明 |
|---|---|
| **Purpose** | 最终回答依据，reducer 产物，不是多个自然语言片段拼接 |
| **Domain** | GraphState 中间态, response 输入 |

```python
class FinalDecisionPlan:
    plan_id: str
    source_workflows: list[str]
    global_evidence_pack: GlobalEvidencePack
    decision_fragments_used: list[str]
    final_ranking: list[RankedShop]
    final_winner: str | None
    tradeoffs: list[TradeoffExplanation]
    unresolved_conflicts: list[EvidenceConflict]
    caveats: list[str]
    session_write_proposals: list[SessionWriteProposal]
    reduce_trace: ReduceTrace
```

### 15.17 `WorkflowTrace` / `ReduceTrace`

| 维度 | 说明 |
|---|---|
| **Purpose** | 全链路追踪 |
| **Domain** | Observability/Trace |

```python
class WorkflowTrace:
    workflow_kind: WorkflowKind
    entry_node: str
    start_time_ms: int
    end_time_ms: int
    nodes_visited: list[str]
    llm_calls: int
    tool_calls: int
    total_latency_ms: int

class ReduceTrace:
    reducer_id: str
    phase: str  # "evidence_reduce" / "conflict_resolve" / "decision_reduce"
    start_time_ms: int
    end_time_ms: int
    evidence_sources: list[str]
    conflicts_found: list[EvidenceConflict]
    conflicts_resolved: list[ConflictResolution]
    resolution_strategy: str  # "rule_based" / "llm_assisted" / "hybrid"
    items_merged: int
    items_deduplicated: int
    items_rejected: int
    final_output_ref: str
```

---

## 16. 契约归属总表

| 契约 | 类型 | 归属 |
|---|---|---|
| `TaskComplexity` | Domain DTO | GraphState 中间态 |
| `WorkflowKind` | Domain DTO | 路由/策略 |
| `ReviewPolicy` | Domain DTO | 配置/策略层 |
| `ExpandSearchPolicy` | Domain DTO | 配置/策略层 |
| `RankingPolicy` | Domain DTO | ExecutionPlan/DecisionPlan |
| `ToolCallCacheKey` | Domain DTO | ToolResultCache |
| `ToolResultCacheEntry` | Domain DTO | 缓存层 |
| `EvidenceCacheEntry` | Domain DTO | 缓存层 |
| `SubTask` | Domain DTO | 逻辑计划/DAG |
| `SubTaskDAG` | Domain DTO | GraphState 中间态 |
| `WorkerState` | Domain DTO | worker 局部态 |
| `WorkerResult` | Domain DTO | reducer 输入 |
| `DecisionFragment` | Domain DTO | reducer 输入 |
| `GlobalEvidencePack` | Domain DTO | reducer 输出 |
| `EvidenceConflict` | Domain DTO | reducer/trace |
| `ConflictResolution` | Domain DTO | reducer 输出 |
| `FinalDecisionPlan` | Domain DTO | GraphState 中间态 |
| `WorkflowTrace` | Observability | Trace |
| `ReduceTrace` | Observability | Trace |
| `HardConstraintFilterRule` | Domain DTO | RankingPolicy 的硬约束规则 |
| `HardConstraintFilterSet` | Domain DTO | 硬约束规则集合（AND/OR） |
| `ObjectiveWeight` | Domain DTO | 客观评分单维度权重 |
| `ObjectiveScoringSpec` | Domain DTO | 完整客观评分规格 |
| `TieBreakerRule` | Domain DTO | 平局决胜单规则 |
| `TieBreakerChain` | Domain DTO | 平局决胜链 |
| `ScoreProvenance` | Domain DTO | 单 facet 分数来源追溯 |
| `ScoringProvenanceSet` | Domain DTO | 一次排序的完整评分溯源 |
| `ToolCallCacheKey` | Domain Value | 工具调用缓存键（scope + fingerprint） |

## 补充契约：排序与评分相关 DTO

### HardConstraintFilterRule / HardConstraintFilterSet

**目的**：将当前 `_h_expand_search` 中的 `filters = {}` 清空行为替换为结构化硬约束过滤。

```python
class HardConstraintFilterRule(BaseModel):
    field: str                                   # 约束字段
    operator: Literal["eq", "ne", "le", "ge", "lt", "gt", "in", "not_in", "exists", "not_exists"]
    value: Any                                   # 比较值
    source: str = "semantic_frame"               # 约束来源
    required: bool = True                        # True=硬性排除
    reason: str = ""                             # 约束来源说明

class HardConstraintFilterSet(BaseModel):
    rules: list[HardConstraintFilterRule] = Field(default_factory=list)
    logic: Literal["and", "or"] = "and"
    on_violation: Literal["exclude", "mark", "fallback"] = "exclude"
```

### ObjectiveWeight / ObjectiveScoringSpec

**目的**：替代当前 LLM 隐式排序，提供确定性评分引擎。

```python
class ObjectiveWeight(BaseModel):
    facet: str
    weight: float                                # 权重（sum≈1.0）
    normalization: Literal["identity", "minmax", "log", "zscore", "boolean", "inverse_rank"]
    fallback_value: float = 0.0
    source_field: str = ""

class ObjectiveScoringSpec(BaseModel):
    weights: list[ObjectiveWeight] = Field(default_factory=list)

    def score(self, shop_data: dict) -> dict[str, float]:
        """确定性评分，返回 {facet: score, _total: float}"""
```

### TieBreakerRule / TieBreakerChain

**目的**：同分 shop 的确定决胜策略。

```python
class TieBreakerRule(BaseModel):
    facet: str
    direction: Literal["desc", "asc"] = "desc"

class TieBreakerChain(BaseModel):
    rules: list[TieBreakerRule] = Field(default_factory=list)

    def break_ties(self, ranked: list) -> list:
        """按 rules 顺序依次比较，确定最终排序"""
```

### ScoreProvenance / ScoringProvenanceSet

**目的**：每次排序都必须可追溯，解决"为什么 A 排在 B 前面"问题。

```python
class ScoreProvenance(BaseModel):
    shop_id: str
    facet: str
    score: float
    raw_value: Any
    normalized_value: float
    weight_applied: float
    source: Literal["tool_result", "llm_estimate", "rule_default", "missing_fallback"]
    tool_name: str | None = None
    tool_call_id: str | None = None
    confidence: float = 1.0

class ScoringProvenanceSet(BaseModel):
    provenances: list[ScoreProvenance] = Field(default_factory=list)
    ranking_policy_id: str = ""
    executed_at: str = ""

    def get_shop_scores(self, shop_id: str) -> dict[str, float]:
        """返回某 shop 各 facet 得分"""
```

### ToolCallCacheKey（工具去重）

**目的**：为 ToolResultCache 提供标准缓存键，支持 request coalescing / single-flight。

```python
class ToolCallCacheKey(BaseModel):
    tool_name: str                               # 工具名
    args_fingerprint: str                        # 参数指纹（sorted JSON 后 hash）
    scope: str = "global"                        # 缓存范围：global / session / turn
    location_fingerprint: str | None = None      # 位置指纹（相同位置才命中）
```
