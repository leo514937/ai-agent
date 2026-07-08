# 第二层 MapReduce / Orchestrator-Worker 设计

> ⚠️ **优先级说明**：MapReduce / complex_orchestrator 是第二层**第二阶段**能力，不在首批实施范围内。
>
> **首批实施优先级**（按重要性降序）：
> 1. single_shop_fact workflow 稳定（当前 deterministic_tool 的问题修复）
> 2. 推荐排序不违反硬约束（RankingPolicy 可执行化）
> 3. 对比 winner 确定性选择（基于证据的 winner 判定）
> 4. 工具调用去重（ToolResultCache + request coalescing）
> 5. Response 不能绕过证据链（EvidencePack 强制约束）
>
> MapReduce 的契约设计（SubTaskDAG、WorkerResult、EvidenceReducer 等）可以**先设计但暂不实现**，直到上述 5 项稳定为止。

本文件只设计复杂 query 的拆解与合并方案，不修改业务代码。目标是把“复杂任务”从一个大 planning_subgraph 中拆出来，变成可验证、可观测、可合并的结构化流程。

## 1. 什么时候进入 MapReduce

只有在以下场景才考虑进入 `complex_orchestrator_workflow`：

- 多阶段任务
- 多目标对比
- 多约束推荐
- 推荐 + 对比混合
- 多地点 / 多时间组合规划

### 典型例子

- `周末先吃饭再逛街再喝咖啡`
- `帮我比较 A/B/C 三家，顺便看哪家有券`
- `带长辈半天活动，既要方便又要安静`

## 2. 什么时候不进入 MapReduce

以下场景应继续走轻量 workflow：

- 单店有券吗
- 这家营业吗
- 离我多远
- 简单附近推荐

这些场景如果进入 MapReduce，只会增加延迟和成本。

## 3. Map 阶段设计

### 3.1 `query_decomposer`

输出逻辑子任务。当前仓库没有通用的 `SubTask` 类（codegraph 搜索确认不存在），但有一个近似的概念 `ExplorationStageSpec`：

- [schemas.py:185-245](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L185) — 定义了 `stage_id`、`stage_type`、`category`、`required`、`candidate_query`、`fallback_strategy`、`evidence_requirements` 等字段
- `SubTaskDAG` 完全不存在，需要全新设计

建议的 `SubTask` 设计：

```python
SubTask:
    subtask_id: str
    kind: str
    depends_on: list[str]
    inputs: dict
    outputs: list[str]
    required: bool
```

### 3.2 `workflow_mapper`

把子任务映射到工作流 worker。当前 workflow registry（[workflow_registry.py:152-201](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L152)）有 5 个已注册 workflow：

| 当前名称 | 目标名称 | entry_node | handler |
|---|---|---|---|
| `direct_response` | → `direct_response_workflow` | `response_subgraph` | `run_direct_response_workflow` |
| `deterministic_tool` | → `single_shop_fact_workflow` | `response_subgraph` | `run_deterministic_tool_workflow` |
| `discovery_decision` | → `recommendation_decision_workflow` / `comparison_decision_workflow` | `planning_subgraph` | `_dispatch_discovery_decision` |
| `exploration_planning` | → `exploration_planning_workflow` | `response_subgraph` | `run_exploration_planning_workflow` |
| `clarification_fallback` | → `clarification_workflow` | `response_subgraph` | `run_clarification_fallback_workflow` |

MapReduce 阶段 `workflow_mapper` 将子任务映射到上述 workflow worker。

### 3.3 当前并行执行能力的局限

当前仓库中已经有一个"非 LangGraph-Send"的 MapReduce 风格的批量执行器：

- `BatchToolExecutor.execute()`（[gateway.py:243-259](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L243)）在工具调用层做了 fan-out（map），然后 merge 结果（reduce）
- 但这个 map 只在单 workflow 内部的工具调用层面，不是 workflow/子任务层面
- 当前没有跨 workflow 的并行 worker；所有 workflow 走的是 `workflow_runner → workflow_registry → single handler dispatch` 的串行路径

### 3.3 `stage_worker_executor`

Worker 只负责执行已分配的子任务，不负责最终回答。

### 3.4 Worker 输出

Worker 输出必须是结构化对象：

- `WorkerResult`（当前不存在，需新设计）
- `DecisionFragment`（当前不存在，需新设计）
- `EvidencePack`（已存在，[schemas.py:1101-1167](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1101) 定义了完整证据包）
- `session_write_proposal`（当前不隔离，需新设计）

不能输出最终自然语言结论。

**Worker 状态隔离要求**：当前 `planning_subgraph` 和 `execution_review_subgraph` 中的节点直接读写 `GraphState` 字段（例如 `_h_evidence_review` 直接写 `session_state.review_results`，见 [execution_review_subgraph.py:287-291](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L287)）。在 MapReduce 模式下，worker 必须禁止直接写 `SessionState`，只能返回 `session_write_proposal` 由 orchestrator 统一处理。

## 4. Reduce 阶段设计

### 4.1 `EvidenceReducer`

作用：

- 合并多 worker 产生的证据
- 去重：同一个 (shop_id, facet) 对不重复存储
- 标记事实冲突：不同 worker 对同一 facet 给出矛盾结论时生成 `EvidenceConflict`
- 保留来源与 freshness

**对比当前现状**：当前 `_h_evidence_build`（[execution_review_subgraph.py:210-241](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L210)）只处理单 workflow 内的工具结果合并，没有多来源证据的冲突检测和去重。`EvidencePack` 虽然可以包含多个 `EvidenceItem`，但它没有区分"哪些证据来自哪个 worker"的字段。

### 4.2 `ConflictResolver`

作用：

- 解决多个 workflow 的证据冲突
- 避免简单投票（非同源的证据不能加权求和）
- 按规则裁决（见第 5 节冲突解决策略）

**与当前 `ConflictingFacet` 的关系**：当前 `ConflictingFacet`（[facets.py:96-99](D:/javacode/hm-dianping/local_life_agent/domain/facets.py#L96)）只定义了 `facets`、`reason`、`severity` 三个字段，粒度在 facet 级别，没有到"同一 facet 下多个不同来源的断言值"的冲突记录。新的 `EvidenceConflict` 需要细化到具体断言值级别。

### 4.3 `DecisionReducer`

作用：

- 接收多个 `DecisionFragment`，生成 `FinalDecisionPlan`
- 生成可供 `response_subgraph` 使用的最终结构化决策
- 不拼接多个 worker 的自然语言

**与当前 `DecisionPlan` 的关系**：当前 `DecisionPlan`（[decision.py:280-361](D:/javacode/hm-dianping/local_life_agent/domain/decision.py#L280)）已有丰富的字段（`winner_shop_id`、`ranking`、`claims`、`caveats` 等），但它是单 workflow 决策的输出。`FinalDecisionPlan` 应该是多 workflow 场景下 `DecisionPlan` 的超集——保留所有子决策的结构化内容但不保留自然语言片段。

## 5. 冲突解决策略

冲突解决必须遵守：

1. 工具事实优先于 LLM 推断
2. 新鲜数据优先于过期数据
3. required facet 优先于 optional facet
4. 硬约束优先于软偏好
5. 无法解决的事实冲突标记 unknown，不编造
6. 推荐结论冲突转换成 trade-off，而不是强行掩盖

### 5.1 证据来源优先级

- 真实工具结果（`source_type=TOOL`，[schemas.py:1097](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1097)）
- 已验证证据（已通过 `evidence_review` 确认，[execution_review_subgraph.py:244-292](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L244)）
- 逻辑推断（由 `decision_planner` 基于已有证据推导）
- LLM 解释（仅用于 trade-off 和偏好说明，不能作为事实来源）

### 5.2 freshness 优先级

对于营业状态、距离、券类信息，过期证据不能压过新证据。当前 `EvidenceItem` 已定义了 `freshness_class`、`ttl_seconds`、`observed_at_ms` 字段（[schemas.py:1089-1095](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1089)），这些字段可以用于冲突解决时的 freshness 比较，但目前没有被系统性地使用。

## 6. Reduce 输出

Reduce 阶段至少输出：

- `GlobalEvidencePack`
- `EvidenceConflict` 列表
- `ConflictResolution`
- `FinalDecisionPlan`
- `ReduceTrace`

## 7. 当前实现与目标的偏差

当前仓库里：

- **没有真正的 `SubTaskDAG`**：只有 `ExplorationStageSpec`（[schemas.py:185-245](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L185)）作为近似的阶段描述，但它是为探索规划设计的，不是通用 DAG 节点
- **没有 `WorkerResult`**：当前 workflow handler 返回 dict 直接 patch 到 GraphState（如 `workflow_registry.py:139-149` 中的 `_dispatch_discovery_decision`）
- **没有 `EvidenceReducer`**：当前只能在单 workflow 内构建 EvidencePack，无跨 workflow 合并
- **没有 `DecisionReducer`**：当前 `DecisionPlan` 由 `_h_decision_planner` 在单 workflow 内生成（[execution_review_subgraph.py:295-342](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L295)）
- **没有 `ConflictResolver`** 作为独立 reducer

现状是 `planning_subgraph`（1369 行，[planning_subgraph.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)）和 `execution_review_subgraph`（377 行，[execution_review_subgraph.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py)）在一个大链路里顺带完成了规划、执行、review、fallback，复杂 query 的并行与合并能力还没有结构化分层。

关键观察：当前工具执行层虽然使用了"batch concurrent"模式（`asyncio.gather`，[gateway.py:243-259](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L243)），但这是在单 workflow、单 handler 内部的工具调用粒度的并行；workflow 之间仍然是串行 dispatch。要实现 MapReduce，需要将并行粒度提升到 workflow/subtask 级别。

---

## 8. WorkerState 状态隔离机制

### 8.1 隔离原则

| 原则 | 说明 |
|---|---|
| Worker 不得直接读写 SessionState | Worker 只能通过 WorkerResult.session_write_proposal 建议 |
| Worker 不得直接修改 GraphState | Worker 可读 GraphState（read-only reference） |
| Worker 的 local_tool_results / local_evidence 在 reduce 阶段合并 | EvidenceReducer 负责合并 |
| 多个 Worker 不共享局部状态 | 各 Worker 有独立的 WorkerState |

### 8.2 WorkerState 定义

```python
class WorkerState:
    worker_id: str
    assigned_subtask: SubTask
    local_tool_results: dict[str, Any]  # 仅当前 worker 的工具结果
    local_evidence: dict[str, Any]      # 仅当前 worker 的证据
    status: str  # "running" / "success" / "failed" / "degraded"
    error: str | None
    
    # 禁止字段
    # session_state: NOT ALLOWED
    # graph_state: NOT ALLOWED（read-only reference OK）
```

### 8.3 与当前代码的对比

当前 `planning_subgraph` 和 `execution_review_subgraph` 中的节点直接读写 GraphState 字段：
- `_h_evidence_review` 直接写 `session_state.review_results`（`execution_review_subgraph.py:287-291`）
- `_h_decision_review` 写 `next_action` 到 GraphState

新设计中 Worker 不允许这样的直接写入。

---

## 9. `session_write_proposal` 设计

```python
class SessionWriteProposal:
    proposer_worker_id: str
    target_fields: list[str]    # 建议写入的 SessionState 字段名
    data: dict[str, Any]        # 建议写入的数据
    rationale: str              # 写入理由
    required: bool              # 是否必须（false=可拒绝）
    conflict_check: bool        # 是否需要冲突检查
```

### 规则

1. Worker 只提 proposal，不执行写入
2. Orchestrator 的 ConflictResolver 校验 proposal
3. 多个 worker 对同一字段提 proposal → 走冲突裁决流程
4. 只有 FinalDecisionPlan 确认后，才统一写入 SessionState

---

## 10. ReduceTrace 字段设计

```python
class ReduceTrace:
    reducer_id: str
    phase: str  # "evidence_reduce" / "conflict_resolve" / "decision_reduce"
    start_time_ms: int
    end_time_ms: int
    evidence_sources: list[str]       # worker IDs or workflow names
    conflicts_found: list[EvidenceConflict]
    conflicts_resolved: list[ConflictResolution]
    resolution_strategy: str          # "rule_based" / "llm_assisted" / "hybrid"
    items_merged: int
    items_deduplicated: int
    items_rejected: int
    final_output_ref: str             # ref to FinalDecisionPlan.plan_id
```

---

## 11. FinalDecisionPlan 字段设计

```python
class FinalDecisionPlan:
    plan_id: str
    source_workflows: list[str]                     # 参与 reduce 的 workflow
    global_evidence_pack: GlobalEvidencePack         # 合并后的全局证据
    decision_fragments_used: list[str]               # 引用的 DecisionFragment ID
    final_ranking: list[RankedShop]                  # 最终排名（跨 workflow 合并）
    final_winner: str | None                         # 最终 winner shop_id
    tradeoffs: list[TradeoffExplanation]             # 推荐冲突转 trade-off
    unresolved_conflicts: list[EvidenceConflict]     # 无法解决的冲突
    caveats: list[str]                               # 最终回答注意事项
    session_write_proposals: list[SessionWriteProposal]  # 统一处理后
    reduce_trace: ReduceTrace
```

### 约束

- 不能由多个自然语言片段拼接而来
- 必须是结构化决策，response_subgraph 据此生成最终回答
- `final_ranking` 和 `final_winner` 必须基于 GlobalEvidencePack

---

## 12. SubTaskDAG 节点级完整字段

```python
class SubTask:
    subtask_id: str
    kind: str  # "search" / "detail" / "coupon" / "distance" / "compare" / "plan"
    depends_on: list[str]         # DAG 依赖
    inputs: dict                  # 输入参数
    outputs: list[str]            # 预期输出（evidence facet 列表）
    required: bool                # 失败是否阻断主链路
    timeout_ms: int | None
    retry_policy: str | dict | None
    degrade_policy: str | dict | None
    cache_key: str | None         # 用于 single-flight
    mapped_workflow: str | None   # workflow_mapper 分配的目标 workflow
```

---

## 13. 冲突解决 5 层优先级具体规则

### 第一层：source_type 优先级

```text
优先级: TOOL result > VERIFIED evidence > LOGICAL inference > LLM explanation
```

- 来自工具调用的证据永远优先于 LLM 推断
- `EvidenceItem.source_type` 决定层级

### 第二层：freshness 优先级

```text
freshness = observed_at_ms + ttl_seconds
高 freshness 优先于低 freshness
is_stale=True 的数据不参与裁决
```

- 营业状态、距离 ETA、券余量等需要新鲜度的冲突走此规则
- 使用 `EvidenceItem.observed_at_ms` 和 `ttl_seconds` 比较

### 第三层：required facet 优先级

```text
required facet 上的冲突优先于 optional facet 上的冲突
多个 required facet 冲突必须全部解决
```

- required facet 确认失败时必须进入明确 degrade/fallback

### 第四层：hard constraint 优先级

```text
违反硬约束的推荐结论被降级
hard constraint 定义来自 SemanticFrame.hard_constraints
```

- 品类、位置范围、预算上限、营业状态等硬约束

### 第五层：confidence 优先级

```text
同等条件下 confidence_score 高的优先
多个置信度相同时标记为 trade-off
```

### 无法解决的冲突

```text
无法解决 → 标记 unknown，不编造
推荐结论冲突 → 转成 trade-off 说明，不强行掩盖
```

---

## 14. 从现状到 MapReduce 的迁移路径

| 步骤 | 内容 |
|---|---|
| 1 | 设计 SubTask / SubTaskDAG 数据结构 |
| 2 | 实现 query_decomposer（LLM 拆解复杂 query） |
| 3 | 实现 workflow_mapper（子任务到 workflow 的映射） |
| 4 | 实现 EvidenceReducer / ConflictResolver / DecisionReducer |
| 5 | 实现 stage_worker_executor（按 DAG 拓扑执行 worker） |
| 6 | 注册 complex_orchestrator workflow |
| 7 | Router 将超复杂 query 路由到 complex_orchestrator |
| 8 | 全量测试和 trace 完整性验证 |


