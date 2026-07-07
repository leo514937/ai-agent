# 第二层：任务决策与证据层 — 架构报告

> 分析日期: 2026-07-05
> 范围: `orchestration_router_shadow` → `workflow_runner` → `planning_subgraph` → `execution_review_subgraph`
> 代码行数统计: ~4100 行

---

## 目录

1. [第二层职责边界](#1-第二层职责边界)
2. [模块总参与数据流](#2-模块总参与数据流)
3. [orchestration_router_shadow — 编排路由（影子模式）](#3-orchestration_router_shadow--编排路由影子模式)
4. [workflow_runner — 工作流调度](#4-workflow_runner--工作流调度)
5. [planning_subgraph — 规划子图](#5-planning_subgraph--规划子图)
6. [execution_review_subgraph — 执行审查子图](#6-execution_review_subgraph--执行审查子图)
7. [第二层路由判定总表](#7-第二层路由判定总表)
8. [关键设计决策与注意事项](#8-关键设计决策与注意事项)

---

## 1. 第二层职责边界

第二层（Layer 2）是本地生活 Agent 的核心智能层，负责"决定查什么、调什么工具、收集什么事实、证据够不够"。

**做的事**：
- ✅ 编排模式决策（shadow 模式，不改变 LangGraph 执行路径）
- ✅ 工作流注册表查找与分发（Phase 5 dispatch）
- ✅ 目标规划（从 SemanticFrame 生成 GoalPlan）
- ✅ 目标审查（GoalReview：可执行？支持？需要澄清？）
- ✅ 目标解析（TargetResolve：找哪家店、对比哪些目标、候选集评审）
- ✅ 证据规划（EvidencePlanner：调哪些工具、查什么数据）
- ✅ 计划验证（PlanValidator：tool_calls 格式/ID 合法性）
- ✅ 工具批量执行（ToolExecute：两阶段批处理：search_calls 并行→follow-up calls 并行）
- ✅ 证据构建（EvidenceBuild：工具结果 → EvidencePack，含排名快照和对比矩阵）
- ✅ 证据审查（EvidenceReview：LLM 判断证据是否足够回答用户）
- ✅ 决策规划（DecisionPlanner：从证据生成 DecisionPlan）
- ✅ 决策审查（DecisionReview：证据够了就回答，不够则重规划/降级/澄清）
- ✅ 搜索扩展（ExpandSearch：放宽筛选条件扩大搜索结果）

**不做的事**：
- ❌ 不生成最终自然语言回答
- ❌ 不持久化会话状态
- ❌ 不做输入校验和标准化
- ❌ 不做安全守卫和顶层意图分类

---

## 2. 模块总参与数据流

```
第一层: understanding_subgraph (proceed)
                     │
     ┌───────────────▼───────────────────┐
     │  Phase 4 / 规划路由 (Shadow)        │
     │                                    │
     │  ① orchestration_router_shadow     │
     │     (engine/subgraphs/             │
     │      orchestration_router_shadow.py)│
     │      ↓ 无条件边                     │
     │  ② workflow_runner                  │
     │     (engine/workflow_runner.py)      │
     └───────────────┬───────────────────-─┘
                     │
         ┌───────────┴──────────────┐
         ▼                          ▼
   planning_subgraph          response_subgraph
   (主路径)                    (直接回答/降级)
         │
         ▼
  execution_review_subgraph
         │
    ┌────┴────┐
    ▼         ▼
response   planning_subgraph
_subgraph  (重规划重试)
    │
state_update_plan
    │
   END
```

### 完整流程图（内部节点）

```
                      ┌─────────────────────────────────────┐
                      │  orchestration_router_shadow         │
                      │  → route_orchestration()             │
                      │  → build_orchestration_decision()    │
                      │  → normalize_route_task()            │
                      │  → validate_orchestration_decision() │
                      └────────────┬────────────────────────┘
                                   │ (无条件边)
                                   ▼
                      ┌─────────────────────────────────────┐
                      │  workflow_runner                      │
                      │  → WORKFLOW_REGISTRY.lookup()         │
                      │  → registration.handler()             │
                      │  → _dispatch_discovery_decision()     │
                      │  → 设置 workflow_callable=           │
                      │    "planning_subgraph"                │
                      └────────────┬────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  planning_route              │
                    │  execute / retry / clarify   │
                    │  / fallback                  │
                    ▼                              ▼
       ┌──────────────────────────┐        response_subgraph
       │  planning_subgraph        │        (clarify/fallback)
       │                           │
       │  goal_planner             │
       │    → plan_goal_with_llm() │
       │    → GoalPlan             │
       │      ↓                    │
       │  goal_review              │
       │    → review_goal()        │
       │    → GoalReviewResult     │
       │      ↓                    │
       │  target_resolve           │
       │    → resolve_shop_entity()│
       │    → build_candidate_set()│
       │    → review_candidate_set()│
       │      ↓                    │
       │  clarify_decide           │
       │    → RESOLVED? AMBIGUOUS? │
       │     ↙        ↘           │
       │ evidence    clarify/      │
       │ planner    emit/fallback  │
       │    ↓                      │
       │  evidence_planner         │
       │    → plan_evidence()      │
       │    → ExecutionPlan        │
       │      ↓                    │
       │  plan_validator           │
       │    → ExecutionPlanValidator│
       │    → report.passed?       │
       └────────────┬──────────────┘
                    │ (planning_route = execute)
                    ▼
       ┌──────────────────────────────┐
       │  execution_review_subgraph    │
       │                              │
       │  tool_execute (两阶段批处理)   │
       │    → search_calls 并行        │
       │    → remaining_specs 解析     │
       │    → resolved_batch 并行      │
       │      ↓                       │
       │  evidence_build              │
       │    → build_evidence()         │
       │    → EvidencePack             │
       │      ↓                       │
       │  evidence_review             │
       │    → review_evidence()       │
       │    → 够不够？                 │
       │      ↓                       │
       │  decision_planner            │
       │    → plan_decision()         │
       │    → DecisionPlan            │
       │      ↓                       │
       │  decision_review             │
       │    → review_decision()       │
       │    → FINISH / REPLAN /       │
       │      EXPAND / DEGRADE /      │
       │      FALLBACK / CLARIFY      │
       └────────────┬────────────────┘
                    │
         ┌──────────┴──────────────┐
         ▼                         ▼
  response_subgraph          planning_subgraph
  (enough/degrade/clarify/  (retry: expand_search
   fallback)                 → evidence_planner)
```

---

## 3. `orchestration_router_shadow` — 编排路由（影子模式）

**文件**: `engine/subgraphs/orchestration_router_shadow.py`（79 行）

**LangGraph 位置**: `understanding_subgraph` → `orchestration_router_shadow` → `workflow_runner`

### 3.1 设计理念

该节点是**影子模式（shadow mode）**：只做编排决策的记录和透传，**不改变 LangGraph 执行路径**。它产出的 `OrchestrationDecision` 只用于日志/监控/调试。

```python
builder.add_edge("orchestration_router_shadow", "workflow_runner")  # 无条件边
```

### 3.2 核心逻辑

```python
def h_orchestration_router_shadow(state: GraphState) -> dict:
    shadow_patch = route_orchestration(state)  # 核心调用
    after = {**state, **shadow_patch}
    return _state_delta(before, after, always_include={
        "orchestration_decision", "orchestration_pattern", "workflow_name",
        "workflow_reason", "task_complexity", "requires_tool",
        "requires_clarification", "response_mode", "next_action", ...
    })
```

调用的 `route_orchestration()` 在 `planning/orchestration_router.py:1584` 实现了完整的编排决策流水线：

| 步骤 | 函数 | 说明 |
|---|---|---|
| 规则信号收集 | `_collect_router_rule_signals()` | 从文本提取"推荐/附近/对比/这家那家"等关键词信号 |
| 路由任务标准化 | `normalize_route_task()` | ~200 行条件分支，将当前 turn 归为 30+ 路由标签之一 |
| 策略表查找 | `_policy_for_route_task()` | 从 `_ORCHESTRATION_POLICY_TABLE` 查执行策略 |
| 构建决策 | `_build_decision_from_policy()` | 组装 `OrchestrationDecision`（编排模式/工作流/置信度/缺失字段） |
| 决策校验 | `validate_orchestration_decision()` | 多重校验和兜底修正 |

### 3.3 策略表 `_ORCHESTRATION_POLICY_TABLE`

**定义**: `planning/orchestration_router.py:42-313`

30+ 路由标签分 5 大类：

| 类别 | 路由标签集合 | orchestration_pattern | workflow_name | 说明 |
|---|---|---|---|---|
| **直接回答** | `chat / capability / unsafe / out_of_scope / invalid / forbidden` | `direct_response` | `direct_response` | 打招呼/能力询问/违规/越界 |
| **确定性工具** | `shop_status / shop_distance / shop_price / shop_coupon / shop_review_summary / shop_scene_fit` | `deterministic_tool` | `deterministic_tool` | 单店查询特定方面 |
| **发现决策** | `shop_search / recommendation / comparison / condition_refine / scene_recommendation / deal_compare` | `discovery_decision` | `discovery_decision` | 需要搜索和决策 |
| **探索规划** | `local_trip_plan / date_plan / family_activity_plan / coffee_then_dinner / eat_and_play_plan` | `exploration_planning` | `exploration_planning` | 多步骤行程/活动规划 |
| **澄清降级** | `unknown / ambiguous / reference_failed / no_result / tool_failure / missing_required_slot / low_confidence` | `clarification_fallback` | `clarification_fallback` | 需要澄清或兜底 |

### 3.4 `normalize_route_task()` — 路由标签决策树

**文件**: `planning/orchestration_router.py:886-1187`（~300 行）

这是整张图最复杂的决策函数，通过多层条件分支将当前用户输入映射为路由标签。优先级从高到低：

```
 1. top_intent ∈ {chat/capability/unsafe/out_of_scope/invalid}
    → 直接返回 top_intent
 2. forbidden scope（平台政策/退款/支付/下单等）
    → "forbidden"
 3. 取消意图
    → "invalid"
 4. 置信度 < 0.5 + low-confidence parse source
    → "low_confidence"
 5. missing slot（缺店/缺位置/缺分类等）
    → "missing_required_slot"
 6. 有 pending_clarification
    → "reference_failed"
 7. 对比意图（2+ 目标/序数/指示词）
    → "comparison" / "missing_required_slot"
 8. 探索规划（2+ 阶段/行程类 goal_type）
    → 具体探索类型 / "missing_required_slot"
 9. 单店查询信号 ≤ 1 组
    → 具体确定性工具类型 / task_type
10. task_type ∈ {recommendation / comparison}
    → "recommendation" / "comparison" / "missing_required_slot"
11. goal_type ∈ DISCOVERY_TASKS
    → 对应发现类型
12. 引用解析（single_shop_query 或引用信号）
    → "shop_coupon" / "shop_status" / "recommendation" / "missing_required_slot"
13. 原始文本含"推荐/附近/找"
    → "recommendation"
14. 含"行程/安排/计划"
    → "unknown"
15. task_type ∈ CLARIFICATION_TASKS
    → 对应澄清类型
16. 兜底
    → "unknown"
```

### 3.5 `validate_orchestration_decision()` — 决策校验

**文件**: `planning/orchestration_router.py:1355-1467`

校验规则按优先级执行：

| # | 条件 | 处理 |
|---|---|---|
| 1 | 策略表无对应路由 | → `clarification_fallback` |
| 2 | workflow_name ≠ orchestration_pattern | → `clarification_fallback` |
| 3 | requires_clarification 但 next_action 不是 clarify/fallback | → 强制修正为 clarify |
| 4 | discovery/deterministic/exploration 有 missing_fields | → `clarification_fallback` |
| 5 | 同上且置信度 < 0.5（非 comparison） | → `clarification_fallback` |
| 6 | route_task=reference_failed 但 workflow=deterministic_tool | → `clarification_fallback` |
| 7 | route_task ∈ CLARIFICATION_TASKS | → `clarification_fallback` |
| 8 | route_task ∈ {chat/capability/unsafe/out_of_scope/invalid} | → `direct_response` |
| 9 | route_task=forbidden 且 workflow 不是 direct/clarification | → `direct_response` |

---

## 4. `workflow_runner` — 工作流调度

**文件**: `engine/workflow_runner.py`（291 行）

**LangGraph 位置**: `orchestration_router_shadow` → `workflow_runner` → `planning_subgraph` / `response_subgraph`

### 4.1 核心职责

1. 读取 `orchestration_decision` 中的 `workflow_name`
2. 在 `WORKFLOW_REGISTRY` 中查找对应的工作流注册
3. 调用注册的 handler 函数
4. 设置 `workflow_callable` 供 `_route_workflow_runner` 路由

### 4.2 工作流注册表

**文件**: `engine/workflow_registry.py`（204 行）

5 个已注册的工作流：

| workflow_name | handler | entry_node | is_real | 说明 |
|---|---|---|---|---|
| `discovery_decision` | `_dispatch_discovery_decision` | `planning_subgraph` | ✅ 是 | **主路径** — 含规划+执行+审查 |
| `direct_response` | `run_direct_response_workflow` | `response_subgraph` | ✅ 是 | 打招呼/能力询问等直接回答 |
| `deterministic_tool` | `run_deterministic_tool_workflow` | `response_subgraph` | ✅ 是 | 单店确定性工具流 |
| `clarification_fallback` | `run_clarification_fallback_workflow` | `response_subgraph` | ✅ 是 | 澄清/降级 |
| `exploration_planning` | `run_exploration_planning_workflow` | `response_subgraph` | ✅ 是 | 多步行程规划 |

### 4.3 `_route_workflow_runner` 路由

```python
def _route_workflow_runner(state: GraphState) -> str:
    workflow_name = state.get("workflow_name", "")
    workflow_callable = state.get("workflow_callable", "")
    response_mode = state.get("response_mode", "")

    # 三重判定避免透传丢失
    if (workflow_name == "discovery_decision"
        or workflow_callable == "planning_subgraph"
        or response_mode == "comparison"):
        return "planning_subgraph"
    return "response_subgraph"
```

**路由结果**：
| workflow_name / 字段 | 下一节点 |
|---|---|
| `discovery_decision` 或 `planning_subgraph` 或 `comparison` | **planning_subgraph** |
| 其他 | **response_subgraph** |

---

## 5. `planning_subgraph` — 规划子图

**文件**: `engine/subgraphs/planning_subgraph.py`（1369 行）

**LangGraph 位置**: `workflow_runner` / `merge_clarification`（restore） → `planning_subgraph` → `execution_review_subgraph` / `response_subgraph`

### 5.1 子图内部流水线

```
入口 →
  ┌─ goal_planner (LLM: SemanticFrame → GoalPlan)
  ├─ goal_review (规则: 可执行? 支持? 澄清?)
  │
  ├─ [goal_review 早早路由] → CLARIFY / UNSUPPORTED / FALLBACK
  │
  ├─ target_resolve (多路径: 已解析/对比/推荐/单店)
  │   ├─ 已有 resolved_target → 短路返回
  │   ├─ comparison → resolve_comparison_targets()
  │   ├─ recommendation → build_candidate_spec()
  │   └─ single_shop_query → resolve_shop_entity()
  │
  ├─ [comparison 模糊] → 构建 PendingClarification → CLARIFY
  ├─ [指示词无 current_shop] → CLARIFY
  ├─ [有 pending_clarification] → clarify_decide
  │
  ├─ clarify_decide (RESOLVED? → 继续 / AMBIGUOUS? → CLARIFY)
  │
  ├─ evidence_planner (LLM/确定性: GoalPlan + CandidateSet → ExecutionPlan)
  │   ├─ recommendation → build_recommendation_execution_plan()
  │   ├─ comparison/其他 → plan_evidence_with_llm()
  │   └─ LLM 失败 → deterministic fallback
  │
  └─ plan_validator (规则: tool_calls 格式/ID 校验)
      └─ 验证通过 → planning_route = "execute"
```

### 5.2 `_h_goal_planner` — 目标规划（第 493-536 行）

| 项目 | 内容 |
|---|---|
| **输入** | `semantic_frame`, `session_state`, `raw_text` |
| **核心调用** | `PlanningCore.plan_goal_with_llm(sf, session, raw_text)` |
| **输出** | `goal_plan` (GoalPlan 对象) |
| **写入** | `goal_plan` / `facet_set` / `facets` / `target_resolution` / `task_type` / `session_state.active_goal` |
| **失败** | `goal_plan = None`, `error_code = "GOAL_PLANNER_FAILED"` |

GoalPlan 包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `goal_type` | `GoalType` | RECOMMENDATION / SINGLE_SHOP_QUERY / COMPARISON / COUPON_QUERY / DISTANCE_QUERY |
| `source` | `CandidateSource` | EXPLICIT / DISCOVERY / CONTEXT / EXISTING |
| `requested_count` | int | 请求候选数 |
| `facets` | list | 关注的方面（open_status / coupon / distance / price / review_summary） |
| `hard_constraints` | dict | 硬约束（category / budget 等） |
| `ranking_signals` | list | 排名信号 |
| `planner_source` | str | "llm_goal_planner" 或 "deterministic_goal_planner" |

### 5.3 `_h_goal_review` — 目标审查（第 539-568 行）

| 项目 | 内容 |
|---|---|
| **输入** | `goal_plan`, `raw_text`, `session_state` |
| **核心调用** | `review_goal(gp, raw_text, session)` |
| **输出** | `GoalReviewResult` |

可选的 `next_action`：

| next_action | 含义 | 路由 |
|---|---|---|
| `FINISH` | 目标清晰可执行 | → `target_resolve` |
| `CLARIFY` | 需要用户补充信息 | → `planning_route=clarify` → response_subgraph |
| `UNSUPPORTED_ANSWER` | 完全无法处理 | → `planning_route=fallback` → response_subgraph |
| `FALLBACK` | 需要降级处理 | → `planning_route=fallback` → response_subgraph |

### 5.4 `_h_target_resolve` / `_h_target_resolve_candidate_set` — 目标解析（第 571-1082 行）

这是规划子图中最复杂的模块（~500 行），根据任务类型走不同路径。

#### 路径 1：已有 `resolved_target`（第 596-632 行）

从第一层的 `context_recovery` 带来的已解析目标 → 直接短路返回。

#### 路径 2：对比任务（第 645-683 行）

调用 `resolve_comparison_targets()` → 解析对比目标列表。

| comparison_resolution.status | 后续处理 |
|---|---|
| `RESOLVED` 且有 2+ target | 构建对比 candidate_set |
| `NEED_CLARIFICATION` / `NOT_FOUND` / `TOO_MANY` | 构建 PendingClarification → CLARIFY |
| `PARTIAL` | 用已解析部分继续 |

#### 路径 3：推荐任务（第 685-700 行）

无显式锚点时跳过 grounding（`should_skip_grounding = True`），直接走 `build_local_life_goal_draft` → `build_candidate_spec`。

有锚点时调用 `resolve_shop_entity()` 解析实体。

#### 路径 4：单店查询（第 760-807 行）

```
resolve_shop_entity(mention, session, location, semantic_frame)
  → ShopResolutionResult
    ├─ RESOLVED → 构建 candidate_set, review_candidate_set
    ├─ AMBIGUOUS → 构建 PendingClarification（含多个候选）→ CLARIFY
    └─ LOW_CONFIDENCE / NOT_FOUND / NO_MENTION → 同上
```

#### 候选集评审 `review_candidate_set`（第 885-886 行）

| review.next_action | 含义 | 路由 |
|---|---|---|
| `FINISH` | 足够 → 设 RESOLVED / CANDIDATE_SET_RESOLVED | → evidence_planner |
| `CLARIFY` | 不足（推荐无候选/模糊）→ 构建 PendingClarification | → CLARIFY |
| 其他 | 彻底失败 | → FALLBACK |

### 5.5 `_h_clarify_decide` — 澄清决策（第 1085-1135 行）

在 target_resolve 产出 pending_clarification 后执行：

| 条件 | 决策 |
|---|---|
| `resolution_stage == CANDIDATE_SET_RESOLVED`（多候选对比/推荐） | → 直接 proceed（不清除 pending） |
| `task_type == recommendation` + 有指示词无 current_shop | → "店名有点模糊" |
| `resolve_shop_result.status == RESOLVED` | → proceed |
| `resolve_shop_result.status == AMBIGUOUS / LOW_CONFIDENCE` | → clarify |
| reason 含 comparison_requires_at_least_two_shops 等 | → 对应 comparison 提示 |
| 其他 | → "没有找到这家店" |

### 5.6 `_h_evidence_planner` — 证据规划（第 1138-1256 行）

| 项目 | 内容 |
|---|---|
| **输入** | `goal_plan`, `candidate_set`, `location`, `semantic_frame` |
| **推荐路径** | `build_recommendation_execution_plan()` → 确定性构建（无 LLM） |
| **对比/其他路径** | `plan_evidence_with_llm()` → LLM 规划 → 失败时 `plan_evidence_from_candidates()` 确定性兜底 |
| **输出** | `ExecutionPlan` |

**ExecutionPlan 核心字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_type` | str | 任务类型 |
| `tool_calls` | list[ToolCallSpec] | 要调用的工具列表 |
| `stages` | list[StageSpec] | 执行阶段 |
| `plan_source` | str | 规划来源（llm / deterministic） |

**`_normalize_distance_tool_calls`**（第 169-203 行）：自动将 `get_distance_eta` 改写为 `calculate_distance_km`，并用从 state 提取的坐标填充 origin/destination。

### 5.7 `_h_plan_validator` — 计划验证（第 1259-1301 行）

| 项目 | 内容 |
|---|---|
| **核心调用** | `ExecutionPlanValidator().validate(plan, resolved_shop_ids)` |
| **校验内容** | tool_calls 格式、tool_name 合法性（`ToolRegistry` 注册检查）、shop_id 存在性、参数完整性（args 非空检查）、task_type 一致性 |
| **通过** | `error_code=""`, `validated_plan=plan`, `planning_route=execute` |
| **失败** | `error_code` 值域：`SCHEMA_VALIDATION_FAILED`（格式/参数不合法）、`INVALID_PLAN`（语义错误，如缺少 tool_calls） |
| | `planning_route=fallback` → 直接走 `fallback_answer`，**不尝试重规划** |
| **路由** | `_route_plan_validator`（`_routes.py:153-158`）→ 有 error_code 则 `fallback_answer`，否则 `tool_execute` |

### 5.8 `_h_expand_search` — 搜索扩展（第 1304-1346 行）

用于决策审查阶段判断"证据不够，需要扩大搜索范围"时的重试路径：

| 项目 | 内容 |
|---|---|
| **操作** | `CandidateSpec.limit = old_limit * 2 + 5` |
| | `filters = {}`（清除所有筛选条件） |
| | `sort_by = []`（清除排序） |
| **写入** | `candidate_spec`（放宽后的 spec） |
| | `expand_search_requested = True` |
| **重入点** | `evidence_planner`（用新的 spec 重新规划） |
| **循环防护** | `session_state.replan_counters["expand_search"]` 在 `_routes.py:187-197` 中递增和检查，超过 `MAX_EXPAND_SEARCH_ROUNDS`（默认 **1**）后强制 `fallback_answer` |

---

## 6. `execution_review_subgraph` — 执行审查子图

**文件**: `engine/subgraphs/execution_review_subgraph.py`（377 行）

**LangGraph 位置**: `planning_subgraph` → `execution_review_subgraph` → `response_subgraph` / `planning_subgraph`

### 6.1 子图内部流水线

```
入口 →
  ┌─ tool_execute (两阶段批处理: search_calls 并行 → 解析 → follow-up 并行)
  ├─ evidence_build (工具结果 → EvidencePack)
  ├─ evidence_review (LLM: 证据够不够? required_facets 覆盖了?)
  │
  ├─ [evidence_review 失败] → execution_review_route = fallback
  │
  ├─ decision_planner (LLM: 证据 → DecisionPlan, 含决策类型和回答计划)
  │
  ├─ [decision_planner 失败] → execution_review_route = fallback
  │
  └─ decision_review (规则: 证据够了就 FINISH，不够则重规划/降级/澄清)
```

### 6.2 `_h_tool_execute` — 工具执行（第 111-207 行）

#### 两阶段批处理架构

```
阶段 1: search_calls 并行
        所有 tool_name == "search_shops" 的调用 → ExecutionCore.execute_batch() 并行执行
                                    ↓
阶段 2: resolved_batch 并行
        遍历剩余 non-search calls（如 get_shop_detail / get_coupon 等）
          → 每个 call 检查 shop_id 是否在阶段 1 结果中
          → 带 shop_id 的 → resolved_batch
          → 不带 shop_id 的 → error_results
        所有 resolved_batch → ExecutionCore.execute_batch() 并行执行
                                    ↓
        合并 raw_results: phase1 + phase2 + error_results
                                    ↓
        按 tool_calls 顺序构建 ToolResult dict
```

| 项目 | 内容 |
|---|---|
| **工具调度** | `dispatch_tool_call()`（通过 `ToolCallGateway`） |
| **批处理器** | `ExecutionCore(call_fn=_dispatch_tool_call)` |
| **失败处理** | `result_status ∈ {failed, unknown, circuit_open}` → 标记失败（非 required 标记 degraded） |
| **超时处理** | raw_results 缺失 → `TOOL_TIMEOUT`, `result_status=unknown`（非 required）/ `failed`（required） |

### 6.3 `_h_evidence_build` — 证据构建（第 210-241 行）

| 项目 | 内容 |
|---|---|
| **核心调用** | `build_evidence(tool_results, resolved_target, plan, candidates, comparison_targets, cache, ...)` |
| **输出** | `EvidencePack`（Pydantic 模型） |
| **写入** | `evidence_pack`（含 `ranking_snapshot` 和 `comparison_matrix`） |
| | 推荐任务额外写入 `last_recommendation_list` |

**EvidencePack 核心字段**：

| 字段 | 说明 |
|---|---|
| `ranking_snapshot` | 排名快照（ranked / ranked_shops） |
| `comparison_matrix` | 对比矩阵（rows / columns） |
| `facets` | 覆盖的 facets |
| `required_ok` / `required_failed` | 必查项成功/失败列表 |
| `unknown_as_false_detected` | 是否检测到未知条件 |
| `failed_as_empty_detected` | 是否工具失败但返回空 |

### 6.4 `_h_evidence_review` — 证据审查（第 244-292 行）

| 项目 | 内容 |
|---|---|
| **核心调用** | `review_evidence_with_llm(goal, evidence_pack, tool_results, candidate_review, llm_call)` |
| **LLM 判断** | 证据是否足够回答用户的原始问题？ |
| | required_facets 是否覆盖？ |
| | 是否有 unknown/failed 导致证据不完整？ |
| **输出** | `EvidenceReviewResult` |

`review.next_action` 值域（由 `evidence_review.py` 定义）：

| action | 含义 | 路由 |
|---|---|---|
| `proceed` | 证据足够 | → `decision_planner` |
| `retry` | 证据不足，需要重查 | → `REPLAN_EVIDENCE` → `evidence_planner` |
| `expand_search` | 需要扩大搜索范围 | → `EXPAND_SEARCH` → `expand_search` → `evidence_planner` |
| `clarify` | 需要用户澄清 | → `CLARIFY` |
| `degrade` | 证据不足但可降级回答 | → `DEGRADE_ANSWER` |
| `fallback` | 完全无法回答 | → `FALLBACK` |

### 6.5 `_h_decision_planner` — 决策规划（第 295-342 行）

| 项目 | 内容 |
|---|---|
| **输入** | `goal_plan`, `candidate_set`, `evidence_pack`, `evidence_review` |
| **核心调用** | `plan_decision_with_llm(goal_plan, candidate_set, evidence_pack, evidence_review, llm_call)` |
| **输出** | `DecisionPlan`（Pydantic 模型） |

**DecisionPlan 核心字段**：

| 字段 | 说明 |
|---|---|
| `decision_type` | `single_shop_answer` / `recommendation` / `comparison` / `search_list` / `exploration_plan` |
| `answerable_facets` | 可以回答的方面列表 |
| `unknown_facets` | 无法确定的方面列表 |
| `failed_facets` | 工具失败的方面列表 |
| `winner_shop_id` | 推荐的优胜店铺 ID |
| `winner_shop_name` | 推荐的优胜店铺名 |
| `answer_plan` | 回答策略（概述/对比矩阵/推荐理由） |
| `comparison_winner` | 对比结果的优胜方 |

> **写入的 GraphState 字段名**：`p2_decision_plan`（非 `decision_plan`），见 [`graph_state.py:128`](../../local_life_agent/domain/graph_state.py)。该命名惯例表明决策计划由第二层规划产生，供第三层 `_h_answer_plan_build` 消费。同理，`validated_plan` 是 plan_validator 校验后的执行计划，`execution_plan` 是 evidence_planner 的原始输出。

### 6.6 `_h_decision_review` — 决策审查（第 345-377 行）

| 项目 | 内容 |
|---|---|
| **输入** | `decision_plan`, `goal_plan`, `evidence_review`, `candidate_review`, 重规划计数器 |
| **核心调用** | `review_decision(dp, gp, er, cr, expand_search_count, replan_evidence_count)` |
| **输出** | `DecisionReviewResult` |

**`review.next_action` 值域与路由对应**：

| next_action | 含义 | replan 计数器 | 执行审查路由 | 下一节点 |
|---|---|---|---|---|
| `FINISH` | 证据足够，可以回答 | - | `enough` → | **response_subgraph** |
| `DEGRADE_ANSWER` | 降级回答 | - | `degrade` → | **response_subgraph** |
| `CLARIFY` | 需要澄清 | - | `clarify` → | **response_subgraph** |
| `FALLBACK` / `UNSUPPORTED_ANSWER` | 降级兜底 | - | `fallback` → | **response_subgraph** |
| `REPLAN_EVIDENCE` | 重新规划证据收集 | `replan_evidence++` | `retry` → | **planning_subgraph** |
| `EXPAND_SEARCH` | 扩大搜索范围 | `expand_search++` | `retry` → | **planning_subgraph** |

**重规划循环防护**（`_routes.py:175-197`）：

```python
# 每次 REPLAN_EVIDENCE 或 EXPAND_SEARCH 前检查计数器
if current >= config.MAX_REPLAN_EVIDENCE_ROUNDS:   # 默认 2
    return "fallback_answer"
if current >= config.MAX_EXPAND_SEARCH_ROUNDS:       # 默认 2
    return "fallback_answer"
```

---

## 7. 第二层路由判定总表

### 7.1 `planning_subgraph` → 外层路由

**路由函数**: `_route_planning_subgraph(state)` → `state.get("planning_route")`
**路由映射**: `_GRAPH_PLANNING_ROUTES`（`_routes.py:428-433`）

| planning_route | 含义 | 下一节点 |
|---|---|---|
| `execute` | 规划完成，可以执行 | `execution_review_subgraph` |
| `clarify` | 需要澄清 | `response_subgraph` |
| `fallback` | 降级兜底 | `response_subgraph` |
| `retry` | 重试规划（来自 decision_review 的 REPLAN_EVIDENCE / EXPAND_SEARCH） | `planning_subgraph`（自身） |

> **注意**: `retry` 路由在 planning_subgraph 内部重新进入，但根据 `planning_route` 的来源不同走不同路径：`REPLAN_EVIDENCE` 直接回到 `evidence_planner`；`EXPAND_SEARCH` 经过 `expand_search` 放宽条件后再进入 `evidence_planner`。

### 7.2 `execution_review_subgraph` → 外层路由

**路由函数**: `_route_execution_review_subgraph(state)` → `state.get("execution_review_route")`

| execution_review_route | 含义 | 下一节点 |
|---|---|---|
| `enough` | 证据足够，可以回答 | `response_subgraph` |
| `degrade` | 降级回答 | `response_subgraph` |
| `clarify` | 需要澄清 | `response_subgraph` |
| `fallback` | 完全降级 | `response_subgraph` |
| `retry` | 重规划证据/扩展搜索 | `planning_subgraph` |

### 7.3 第二层内部条件边完整对应表

| 所在子图 | 来源步骤 | 条件 | 目的地 |
|---|---|---|---|
| planning | goal_review | FINISH | target_resolve |
| planning | goal_review | CLARIFY | response_subgraph（外层） |
| planning | goal_review | UNSUPPORTED_ANSWER | response_subgraph（外层） |
| planning | goal_review | FALLBACK | response_subgraph（外层） |
| planning | target_resolve | comparison 模糊 | response_subgraph（外层） |
| planning | target_resolve | 指示词无 current_shop | response_subgraph（外层） |
| planning | target_resolve | pending_clarification 非空 | clarify_decide |
| planning | clarify_decide | RESOLVED | evidence_planner |
| planning | clarify_decide | AMBIGUOUS/LOW_CONFIDENCE | response_subgraph（外层） |
| planning | clarify_decide | NOT_FOUND | response_subgraph（外层） |
| planning | plan_validator | 验证失败 | response_subgraph（外层） |
| planning | plan_validator | 验证通过 | execution_review_subgraph（外层） |
| execution | evidence_review | proceed | decision_planner |
| execution | evidence_review | retry/replan | 设置 REPLAN_EVIDENCE → 外部 retry |
| execution | evidence_review | expand_search | 设置 EXPAND_SEARCH → 外部 retry |
| execution | evidence_review | clarify | response_subgraph（外层） |
| execution | evidence_review | degrade | decision_planner |
| execution | evidence_review | fallback | response_subgraph（外层） |
| execution | decision_review | FINISH | response_subgraph（外层） |
| execution | decision_review | REPLAN_EVIDENCE | 外部 retry → planning_subgraph → evidence_planner |
| execution | decision_review | EXPAND_SEARCH | 外部 retry → planning_subgraph → expand_search → evidence_planner |
| execution | decision_review | DEGRADE_ANSWER | response_subgraph（外层） |
| execution | decision_review | CLARIFY | response_subgraph（外层） |
| execution | decision_review | FALLBACK / UNSUPPORTED | response_subgraph（外层） |

### 7.4 replan 循环防护限值

| 配置项 | 默认值（实际代码 `config.py:213-215`） | 作用 |
|---|---|---|
| `MAX_REPLAN_EVIDENCE_ROUNDS` | **1** | evidence replan 最大重试次数 |
| `MAX_EXPAND_SEARCH_ROUNDS` | **1** | expand search 最大重试次数 |

**重试路径**：decision_review 返回 `REPLAN_EVIDENCE` → 外层路由 `_route_decision_review` 检查计数器 → `< limit` 时递增计数器并回到 `evidence_planner`（或 `expand_search`）→ `>= limit` 时直接 `fallback_answer`。
**计数器存储**：`SessionState.replan_counters` dict，跨轮持久化（详见 [`state.py`](../../local_life_agent/domain/state.py)）。
**实际触发代码**：[`_routes.py:175-197`](../../local_life_agent/engine/_routes.py) 和 [`execution_review_subgraph.py:75-88`](../../local_life_agent/engine/subgraphs/execution_review_subgraph.py)。

> ⚠️ **纠正**：默认值为 **1**（不是 2）。两计数器独立计数，各自超过 1 次后强制走 `fallback_answer`，防止无限循环。

---

## 8. 关键设计决策与注意事项

### 8.1 编排路由是影子模式

`orchestration_router_shadow` 不改变执行路径。它的决策只写入 `orchestration_decision` 字段用于日志和监控，实际路由由 `planning_subgraph` / `execution_review_subgraph` 内部条件边决定。这种设计使路由逻辑可观测但不侵入。

### 8.2 工作流注册表做白名单分发

`workflow_runner` 不做任何业务逻辑。它只做：
1. 查表（`WORKFLOW_REGISTRY.lookup()`）
2. 调用 handler
3. 设置 `workflow_callable` 字段

所有 5 个工作流都有显式注册，非法名称直接抛 `WorkflowRegistryError`。

### 8.3 目标解析有多条独立路径

`_h_target_resolve_candidate_set` 根据 `task_type` 走完全不同的解析逻辑：

- **单店查询** → `resolve_shop_entity()`（实体解析，可能有模糊匹配）
- **对比** → `resolve_comparison_targets()`（跨轮视角的多目标解析）
- **推荐** → `build_candidate_spec()`（条件构建，可能有 grounding hint）
- **已解析短路** → 从 context_recovery 带来的结果直接返回

### 8.4 LLM 规划有确定性兜底

证据规划有 3 层兜底：

```
LLM 规划 (plan_evidence_with_llm)  → 失败？
  ↓ Yes
确定性规划 (plan_evidence_from_candidates)  → 失败？
  ↓ Yes
error_code = "EVIDENCE_PLANNER_FAILED"
```

推荐任务不走 LLM，直接用 `build_recommendation_execution_plan()` 确定性构建。

### 8.5 工具执行采用两阶段批处理

第一阶段：所有 `search_shops` 调用并行执行，结果用于解析 `shop_id`。
第二阶段：剩余带 `shop_id` 的工具调用并行执行，不带 `shop_id` 的标记为 `INVALID_ARGUMENT`。

这样避免 search 结果未到就执行依赖 search 结果的工具。

### 8.6 Replan 循环有硬防护

系统有两个独立计数器（`replan_evidence` 和 `expand_search`），各自默认最大 **1 次**重试（`config.py:213-215`）。超过后强制走 `fallback_answer`，防止无限循环。计数器存储在 `SessionState.replan_counters` dict 中，跨轮持久化。

### 8.7 推荐任务的执行计划是确定性的

`build_recommendation_execution_plan()` 不调用 LLM，而是根据 `semantic_frame` 中的 `focused_facets` / `hard_constraints` 等字段，确定性生成 `search_shops` 等工具调用。这保证了推荐任务的执行路径完全可预测。

### 8.8 对比任务的解析是跨轮的

`resolve_comparison_targets()` 不仅看当前输入，还读取 `session_state` 中的 `current_shop` / `last_recommendation_list` / `comparison_targets`，支持多轮对话中"第一家"、"第二家"、"这两家"等跨轮指代。

### 8.9 距离工具自动归一化

`_normalize_distance_tool_calls()` 自动将 `get_distance_eta` 改写为 `calculate_distance_km`，并用 `_location_from_state()` 和 `_resolved_shop_location_from_state()` 从多个 state 字段（location / resolved_target / current_shop）提取坐标，保证距离计算始终可用。

### 8.10 项目 AGENTS.md 约束对照

| 约束 | 第二层落实情况 |
|---|---|
| 禁止 Mock 数据 | `resolve_shop_entity` 调用真实工具查数据库，候选集通过 `dispatch_tool_call` 获取，不做静态列表 |
| 工具调用必须通过 Gateway | `_h_tool_execute` 使用 `dispatch_tool_call()`（`tools/gateway.py`），不走直接数据库访问 |
| Plan → Execute → Review | 完全吻合：`planning_subgraph`（Plan）→ `execution_review_subgraph`（Execute + Review）→ LLM Answer |
| 回答必须基于 EvidencePack | `decision_planner` 只读 `evidence_pack`，不直接编造答案；`answer_plan_build` 也基于 DecisionPlan 的 answerable_facets |
| 工具失败/空结果必须显式返回 | `_h_tool_execute` 的 `error_results` 和 `TOOL_TIMEOUT` 兜底确保不伪装成功 |
| 不允许工具层决定最终回答 | `execution_review_subgraph` 产出的是 DecisionPlan 结构，不是自然语言 |
