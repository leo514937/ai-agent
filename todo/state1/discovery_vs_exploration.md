# discovery_decision vs exploration_planning 工作流设计对比分析报告

> 撰写日期：2026-07-01
> 范围：`local_life_agent/` 全部相关模块
> 目的：系统对比两个 bounded plan-execute-review 工作流的架构差异、设计权衡和演进路径

---

## 目录

1. [概述与核心结论](#1-概述与核心结论)
2. [架构定位对比](#2-架构定位对比)
3. [LangGraph 集成深度](#3-langgraph-集成深度)
4. [编排路由对比](#4-编排路由对比)
5. [规划阶段对比](#5-规划阶段对比)
6. [执行阶段对比](#6-执行阶段对比)
7. [证据与决策对比](#7-证据与决策对比)
8. [回答生成对比](#8-回答生成对比)
9. [验证与回退对比](#9-验证与回退对比)
10. [状态与 Schema 对比](#10-状态与-schema-对比)
11. [测试覆盖对比](#11-测试覆盖对比)
12. [设计权衡分析](#12-设计权衡分析)
13. [演进建议](#13-演进建议)

---

## 1. 概述与核心结论

### 一句话总结

**discovery_decision** 是一个深度 LangGraph 集成、完整 plan-execute-review 循环、支持 LLM 驱动规划与决策的通用工作流；**exploration_planning** 是一个轻量独立 handler、模板驱动规划、确定性回答组合的领域专用工作流。

### 核心差异矩阵

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 架构模式 | 子图编排（subgraph DAG） | 独立函数（inline handler） |
| LangGraph 节点数 | 3 个子图（planning + execution_review + response） | 0 个（直接输出） |
| 路由后去向 | planning_subgraph | response_subgraph |
| 规划方式 | LLM 驱动（GoalPlanner + GoalReview） | 模板驱动（5 个硬编码 template）+ 文本拆分 |
| 工具执行 | ExecutionCore → BatchToolExecutor（批处理并发） | 直接调用 dispatch_tool_call（顺序遍历） |
| 回答生成 | LLMVerbalizer（LLM 生成） | `_compose_final_response`（确定性组合） |
| 验证机制 | response_subgraph 内部 verify_answer → B2MiniVerifier | 内联调用 verify_answer，失败则 fallback |
| 重试/回退 | LangGraph 条件边（retry → expand_search → replan） | 内联 if/else → run_clarification_fallback_workflow |
| 响应模式 | recommendation / comparison / search_list / refinement | exploration_plan |
| 任务复杂度 | medium | high |
| 任务类型数 | 6 种 | 5 种 |

---

## 2. 架构定位对比

### 2.1 discovery_decision：通用子图编排工作流

```
orchestration_router_shadow (Phase 4)
        │
        ▼
workflow_runner (Phase 5) ──→ _route_workflow_runner ──→ "planning_subgraph"  ◄── discovery_decision
        │                                              └── "response_subgraph" ◄── 其他 workflow
        ▼
planning_subgraph
  ├── GoalPlanner → GoalReview → TargetResolve → ClarifyDecide
  └── EvidencePlanner → PlanValidator
        │
        ▼
execution_review_subgraph
  ├── ToolExecute → EvidenceBuild → EvidenceReview
  └── DecisionPlanner → DecisionReview (↺ retry / expand_search / replan)
        │
        ▼
response_subgraph
  ├── AnswerPlanBuild → AnswerGenerate (LLMVerbalizer)
  └── AnswerVerify → Rewrite (↺ 最多 1 次) → FinalResponse
        │
        ▼
state_update_plan → END
```

- discovery_decision 在 `workflow_registry.py` 中的 handler 是 `_dispatch_discovery_decision`——一个**极薄的 dispatch 存根**，仅设置 `workflow_run_status="dispatched"`，不执行任何业务逻辑。
- 真正的业务逻辑在 `planning_subgraph` + `execution_review_subgraph` + `response_subgraph` 三个子图中执行。
- `_route_workflow_runner` 条件边：`workflow_name == "discovery_decision"` → `planning_subgraph`，其余 → `response_subgraph`。
- 这意味着 discovery_decision 实际复用了**主链路子图**，与其他 workflow（direct_response / deterministic_tool）走完全不同的路径。

### 2.2 exploration_planning：独立 Handler 工作流

```
orchestration_router_shadow (Phase 4)
        │
        ▼
workflow_runner (Phase 5) ──→ registration.handler(route_state, decision)
        │                       = run_exploration_planning_workflow()
        │                       │
        │                       ├── _build_subgoals() (template / text-split)
        │                       ├── _tool_round_search() (dispatch_tool_call)
        │                       ├── _tool_round_expand() (dispatch_tool_call)
        │                       ├── build_evidence() (evidence_builder)
        │                       ├── _compose_final_response() (deterministic)
        │                       └── verify_answer() (内联)
        │                       │
        │                       └── 失败 → run_clarification_fallback_workflow()
        │
        ▼
_route_workflow_runner ──→ "response_subgraph" (workflow_run_status="dispatched")
```

- `run_exploration_planning_workflow` 是一个完整自包含的异步 handler，直接在 workflow_runner 内部完成全部 plan-execute-review-answer 流程。
- 成功后设置 `workflow_run_status="completed"`，然后通过 `_route_workflow_runner` 路由到 `response_subgraph`。
- 失败时直接调用 `run_clarification_fallback_workflow()`，返回 fallback 结果。
- **整个过程不经过 planning_subgraph 和 execution_review_subgraph**。

### 关键洞察

| 角度 | discovery_decision | exploration_planning |
|---|---|---|
| 执行上下文 | 跨 3 个子图，跨多次 LangGraph 执行轮次 | 单一函数调用内完成 |
| 状态持久化 | 通过 GraphState 在子图间传递 | 局部变量 + 返回 patch dict |
| 复用性 | 复用主链路子图（planning/execution_review/response） | 自包含，不依赖主链路子图 |
| 可观测性 | 子图级别 logging + span 追踪 | 函数级别 logging |
| 故障隔离 | 子图级条件边控制（不同节点可失败） | 全有或全无（单点失败 → fallback） |

---

## 3. LangGraph 集成深度

### 3.1 discovery_decision

| 层级 | 集成方式 |
|---|---|
| 图节点 | `planning_subgraph`、`execution_review_subgraph`、`response_subgraph` 三个 StateGraph 子图 |
| 条件边 | `_route_workflow_runner`（入口）、`_route_planning_subgraph`、`_route_execution_review_subgraph`、`_route_response_subgraph` |
| 重试循环 | `execution_review_subgraph` → `OUTER_ROUTE_RETRY` → `planning_subgraph` |
| 重规划循环 | `decision_review.REPLAN_EVIDENCE` → `evidence_planner`↺、`decision_review.EXPAND_SEARCH` → `expand_search`↺ |
| 回退链路 | 子图条件边 → `response_subgraph` 的 fallback_answer / clarify_response 节点 |
| 路由映射 | `_GRAPH_PLANNING_ROUTES`、`_GRAPH_EXECUTION_ROUTES`、`_GRAPH_RESPONSE_ROUTES` |

discovery_decision 利用了 LangGraph 的全部能力：子图嵌套、条件边、带计数器的重试循环、跨多轮状态持久化。

### 3.2 exploration_planning

| 层级 | 集成方式 |
|---|---|
| 图节点 | 0 个子图（所有逻辑内联在 handler 函数中） |
| 条件边 | 无（由 `_route_workflow_runner` 单条件判断路由到 response_subgraph） |
| 重试循环 | 无（失败即调用 `run_clarification_fallback_workflow`） |
| 回退链路 | 直接调用 `run_clarification_fallback_workflow()`，不经过条件边 |
| 路由映射 | 无（仅在 `_WORKFLOW_RUNNER_ROUTES` 中有一条被动路由） |

exploration_planning 对 LangGraph 的使用极浅，本质上是一个**注册到 workflow_runner 的普通 Python 函数**。

### 核心差异：控制反转

- discovery_decision：**LangGraph 控制**——graph 决定何时进入什么节点，handler 返回状态 patch 等待下一轮调度。
- exploration_planning：**Handler 自控制**——在函数内部完成全部逻辑，向 graph 返回最终结果 patch。

---

## 4. 编排路由对比

### 4.1 策略表（`orchestration_router.py`）

```
discovery_decision 路由的任务类型（6 种）：
  shop_search       → pattern=discovery_decision, complexity=medium, response_mode=search_list
  recommendation    → pattern=discovery_decision, complexity=medium, response_mode=recommendation
  comparison        → pattern=discovery_decision, complexity=medium, response_mode=comparison
  condition_refine  → pattern=discovery_decision, complexity=medium, response_mode=refinement
  scene_recommendation → pattern=discovery_decision, complexity=medium, response_mode=recommendation
  deal_compare      → pattern=discovery_decision, complexity=medium, response_mode=comparison

exploration_planning 路由的任务类型（5 种）：
  local_trip_plan     → pattern=exploration_planning, complexity=high, response_mode=exploration_plan
  date_plan           → pattern=exploration_planning, complexity=high, response_mode=exploration_plan
  family_activity_plan → pattern=exploration_planning, complexity=high, response_mode=exploration_plan
  coffee_then_dinner  → pattern=exploration_planning, complexity=high, response_mode=exploration_plan
  eat_and_play_plan   → pattern=exploration_planning, complexity=high, response_mode=exploration_plan
```

### 4.2 路由判定逻辑（normalize_route_task）

discovery_decision：通过 `task_type` 或 `goal_type` 进入 `_DISCOVERY_TASKS` 集合匹配：

```python
_DISCOVERY_TASKS = {
    "shop_search", "recommendation", "comparison",
    "condition_refine", "scene_recommendation", "deal_compare",
}
```

exploration_planning：通过 `goal_type` 或 `task_type` 进入 `_EXPLORATION_TASKS` 集合匹配，**优先级高于 discovery_decision 和 deterministic_tool**：

```python
_EXPLORATION_TASKS = {
    "local_trip_plan", "date_plan", "family_activity_plan",
    "coffee_then_dinner", "eat_and_play_plan",
}
```

在 `normalize_route_task` 函数中，exploration_planning 的匹配**发生在 deterministic_tool 和 discovery_decision 之前**：
```python
# normalize_route_task 第 628 行
if goal_type in _EXPLORATION_TASKS or task_type in _EXPLORATION_TASKS:
    return goal_type or task_type
```

### 4.3 置信度评分

| 任务 | discovery_decision | exploration_planning |
|---|---|---|
| 置信度基准 | 0.68-0.72 | 0.58 |
| requires_tool 加成 | +0.05 | +0.05 |
| 有效置信度 | ~0.73-0.77 | ~0.63 |

exploration_planning 任务的置信度明显偏低，反映了系统对于"高复杂度规划任务"预测准确性的保守态度。

---

## 5. 规划阶段对比

### 5.1 discovery_decision：LLM 驱动规划链

```
planning_subgraph 内部流程：

1. GoalPlanner (plan_goal)
   - 使用 LLM（call_llm）根据 semantic_frame 生成 GoalPlan
   - 包含：goal_type、target_entities、facets、constraints、confidence

2. GoalReview (review_goal)
   - 使用 LLM 评估 GoalPlan 的充分性
   - 输出 next_action: FINISH / CLARIFY / UNSUPPORTED_ANSWER / FALLBACK

3. TargetResolve (resolve_shop → CandidateResolver)
   - 解析目标店铺（单店或候选列表）
   - 输出 ResolveShopResult: RESOLVED / AMBIGUOUS / NOT_FOUND

4. ClarifyDecide
   - 根据 ResolveShopResult 决定：proceed / clarify / emit

5. EvidencePlanner (plan_evidence)
   - 使用 LLM 生成 ExecutionPlan（tool_calls + stages）
   - 包含：调用哪些工具、参数、依赖顺序、并行度

6. PlanValidator (ExecutionPlanValidator)
   - 验证工具名称合法性、参数完整性、依赖关系
   - 失败 → fallback_answer；成功 → tool_execute
```

**关键特性**：
- 使用两次 LLM 调用（GoalPlanner + EvidencePlanner）
- 使用一次 LLM 调用（GoalReview）作为质量门
- 目标解析和计划验证是确定性逻辑
- 支持 CandidateResolver 的候选集解析

### 5.2 exploration_planning：模板驱动规划

```
exploration_planning 内部规划流程：

1. _normalize_task_type()
   - 从 state / semantic_frame / decision 提取 task_type

2. _build_subgoals()
   a) _template_subgoals() - 优先匹配 5 个硬编码模板
      ▸ coffee_then_dinner: [咖啡店 → 餐厅]
      ▸ date_plan: [咖啡甜品 → 约会餐厅 → 公园散步]
      ▸ family_activity_plan: [亲子餐厅 → 儿童乐园 → 甜品店]
      ▸ local_trip_plan: [景点 → 餐厅 → 咖啡店]
      ▸ eat_and_play_plan: [餐厅 → 游玩地点 → 咖啡甜品]
      ▸ 模板中自动注入 hard_constraints/soft_preferences 做 query 增强

   b) 无模板匹配：
      ▸ _split_sequence_text() - 用分隔符拆分 "先...然后...再..." 文本
      ▸ facet-derived：将语义面的 facet_list 转为子目标
      ▸ task_type fallback：单子目标兜底

3. 约束检查：
   - 子目标 > 3 → FALLBACK (too_many_subgoals)
   - 无位置信息 → FALLBACK (missing_location)
   - 无子目标 → FALLBACK
```

**关键特性**：
- 零 LLM 调用（纯规则 + 模板匹配）
- 5 个任务类型有精确的预定义模板（查询词、时序关系）
- 失败时直接 fallback，不尝试 LLM 兜底
- 子目标数量硬限制为 3 个

### 5.3 规划阶段对比总结

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 规划驱动方式 | LLM 驱动 | 模板 + 规则驱动 |
| LLM 调用次数 | 2-3 次（GoalPlanner + GoalReview + EvidencePlanner） | 0 次 |
| 规划灵活性 | 高（LLM 可适应任意 query） | 低（仅覆盖 5 种预设场景） |
| 规划可预测性 | 低（LLM 输出方差大，需 review 验证） | 高（确定性输出） |
| 规划失败模式 | 正常回退（review → replan / clarify / fallback） | 直接 fallback |
| 错误补充机制 | GoalReview 可触发 CLARIFY | 无（模板不匹配即放弃） |
| 支持自定义规划 | 是（plan_goal_with_llm / plan_evidence_with_llm） | 否（仅模板 + 文本拆分） |

---

## 6. 执行阶段对比

### 6.1 discovery_decision：批量并发执行

```
execution_review_subgraph 内部流程：

1. ToolExecute (_h_tool_execute)
   - 从 validated_plan 或 execution_plan 读取 ToolCallSpec 列表
   - 通过 ExecutionCore.execute_batch() 执行
   - BatchToolExecutor.execute_sync() 内部：
     ▸ 按 group_id 分组
     ▸ 同组内并发调用 dispatch_tool_call()
     ▸ 跨组按 depends_on 顺序执行
   - 输出: tool_results (dict[call_id, ToolResult])

2. EvidenceBuild (_h_evidence_build)
   - 调用 build_evidence() 聚合 tool_results
   - 支持 3 种模式：
     ▸ 单店多维度（coupon / open_status / distance）
     ▸ 推荐列表（ranking_snapshot）
     ▸ 多店对比（comparison_matrix + dimension_winners）
   - 输出: EvidencePack

3. EvidenceReview (review_evidence)
   - LLM 驱动：review_evidence_with_llm()
   - 检查证据是否充分（是否覆盖所有 required facet）
   - 输出 next_action: FINISH / REPLAN_EVIDENCE / FALLBACK / CLARIFY / DEGRADE_ANSWER
```

**工具调用路径**：
```
ExecutionCore.execute_batch()
    └── BatchToolExecutor.execute_sync()
        ├── dispatch_tool_call("search_shops", ...)    [并发]
        ├── dispatch_tool_call("get_shop_cards", ...)   [并发]
        ├── dispatch_tool_call("check_open_status", ...) [并发]
        ├── dispatch_tool_call("get_coupon_list", ...)  [并发]
        └── dispatch_tool_call("get_distance_eta", ...) [并发]
```

### 6.2 exploration_planning：顺序遍历执行

```
exploration_planning 内部执行流程：

1. _tool_round_search() — "发现轮"
   - 遍历每个 subgoal
   - 对每个 subgoal 调用 dispatch_tool_call("search_shops", ...)
   - 结果存入 subgoal["candidate_shops"]
   - 任何失败 → 全局标记 any_failure = True → FALLBACK

2. _tool_round_expand() — "详情轮"
   - 遍历每个 subgoal
   - 对每个 subgoal 的第一个候选 (candidates[0]) 调用：
     ▸ get_shop_detail()
     ▸ check_open_status()
     ▸ get_distance_eta()
     ▸ （条件：get_shop_review_summary()）
   - 结果存入 tool_results (dict[str, ToolResult])
   - 任何失败 → 全局标记 failure = True → FALLBACK
```

**工具调用路径**：
```
_tool_round_search():
    for subgoal in subgoals:
        dispatch_tool_call("search_shops", query, location, limit=3)  [顺序]

_tool_round_expand():
    for subgoal in subgoals:
        candidates[0]  # 只取第一个候选
        dispatch_tool_call("get_shop_detail", shop_id)         [顺序]
        dispatch_tool_call("check_open_status", shop_id)       [顺序]
        dispatch_tool_call("get_distance_eta", shop_id, loc)   [顺序]
        # 无并发，无批处理
```

### 6.3 执行阶段对比总结

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 执行模式 | 批量并发（按 stage/group_id） | 顺序遍历 |
| 执行引擎 | ExecutionCore → BatchToolExecutor | 直接 dispatch_tool_call |
| 候选选择 | 全部候选（多 shop_id 批处理） | 仅第一个候选（candidates[0]） |
| 工具数量 | 取决于 ExecutionPlan（通常 5-15 次调用） | 固定：search_shops + 3-4 个详情工具 × N subgoal |
| 并发度 | 同 group 内全并发 | 0（全串行） |
| 失败处理 | 按 call 级别记录（单个失败不影响整体） | 全局失败标记（任一失败 → FALLBACK） |
| 重试策略 | 内置 retry_policy（max_attempts=3, backoff=200ms） | 无（失败即 FALLBACK） |
| 降级策略 | EvidenceReview 输出 DEGRADE_ANSWER | 无降级 |
| 可扩展性 | 高（可灵活添加 tool_calls） | 低（固定调用模式） |

---

## 7. 证据与决策对比

### 7.1 共享组件

两个工作流**共享**同一个 `build_evidence` 函数（`planning/evidence/evidence_builder.py`）：

- `build_evidence(tool_results, resolved_target, execution_plan, recommendation_candidates, comparison_targets)`
- 根据 `execution_plan.task_type` 自动选择构建模式：
  - `"comparison"` → `_build_comparison_evidence()` 含 ComparisonMatrix、dimension_winners
  - `"recommendation"` → `_build_recommendation_evidence()` 含 ranking_snapshot
  - 其他 → 单店多维度证据

**但使用方式不同**：

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| evidence 输入 | tool_results 来自 BatchToolExecutor 全量结果 | tool_results 来自 `_tool_round_expand()` 部分结果 |
| resolved_target | 来自 planning_subgraph 的完整 ResolveShopResult | 传入 `{}`（空字典，无店铺解析） |
| execution_plan | 来自 EvidencePlanner 的完整 ExecutionPlan | 手动构造的伪 ExecutionPlan（tool_calls=[]） |
| recommendation_candidates | 来自 CandidateResolver | 传入 `[]` |
| comparison_targets | 来自 SemanticFrame | 传入 `[]` |

### 7.2 决策阶段

#### discovery_decision

```
DecisionPlanner (_h_decision_planner)
  - 使用 LLM (plan_decision_with_llm) 根据 EvidencePack 生成 DecisionPlan
  - 包含：selected_targets, overall_ranking, best_for, factual_points, uncertainty_notes

DecisionReview (_h_decision_review)
  - 使用 LLM (review_decision) 评估 DecisionPlan 质量
  - 输出 next_action: FINISH / REPLAN_EVIDENCE / EXPAND_SEARCH / FALLBACK / CLARIFY / DEGRADE_ANSWER

然后 → AnswerPlanBuild (decision_to_answer_plan) 生成 AnswerPlan
    → AnswerGenerate (LLMVerbalizer) 生成 final_response
    → AnswerVerify (verify_answer) 验证 → B2MiniVerifier (LLM-based)
```

#### exploration_planning

```
无 DecisionPlan 阶段！

直接构建 AnswerPlan（手动构造）：
  answer_type = "exploration_plan"
  response_sections = [exploration_summary]
  allowed_claims = []
  forbidden_claims = []

然后 → _compose_final_response() 确定性组合最终回答
    → verify_answer() 内联验证 → B2MiniVerifier (LLM-based)
    → 失败 → run_clarification_fallback_workflow()
```

### 7.3 关键差异：LLM 在决策中的作用

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 决策规划 | LLM 生成（plan_decision_with_llm） | 无（手动构造 AnswerPlan） |
| 决策审查 | LLM 审查（review_decision） | 无（直接验证最终回答） |
| 回答生成 | LLM 生成（LLMVerbalizer） | 确定性组合（_compose_final_response） |
| 验证时机 | 在回答生成之后 | 在回答组合之后 |
| 失败后行为 | 重写最多 1 次 → fallback | 直接 fallback |

---

## 8. 回答生成对比

### 8.1 discovery_decision：LLM 生成自然语言

```
AnswerPlanBuild → decision_to_answer_plan()
    ▸ 将 DecisionPlan 转为 AnswerPlan（结构化的回答指令）
    ▸ 包含：response_sections, allowed_claims, required_claims, forbidden_claims

AnswerGenerate → LLMVerbalizer
    ▸ 使用 LLM 根据 AnswerPlan + EvidencePack 生成自然语言回答
    ▸ 支持：single_shop, recommendation, comparison, clarification, error 等类型
    ▸ LLM 负责：组织语言、生成推荐语气、店铺对比表述

AnswerVerify → verify_answer() → B2MiniVerifier
    ▸ LLM 评估回答是否忠实于 evidence
    ▸ 检查：shop_name 幻觉、排序篡改、未支持维度胜出声明、false positive/negative
    ▸ 可触发 rewrite（最多 1 次）
```

### 8.2 exploration_planning：确定性组合

```
_compose_final_response(plan, evidence)
  ▸ 遍历 plan.subgoals
  ▸ 从 evidence.evidence_items 中提取每个 subgoal.selected_candidate 的信息
  ▸ 组合：店名 + 营业状态 + 距离/ETA + 评价摘要
  ▸ 按时序关系组织 subgoal 顺序
  ▸ 输出格式：
      "按顺序安排如下：1. [店铺信息]；2. [店铺信息]；3. [店铺信息]"

verify_answer() 内联
  ▸ 与 discovery_decision 使用相同的 B2MiniVerifier
  ▸ 但不需要 LLM 生成回答，只需验证确定性组合的结果
  ▸ 失败 → 直接 fallback（无重写）
```

### 8.3 回答生成对比

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 生成方式 | LLM 生成 | 确定性组合 |
| 回答多样性 | 高（不同 LLM 调用产生不同表述） | 低（固定模板格式） |
| 回答可控性 | 低（需 verify + rewrite 约束） | 高（精确格式控制） |
| 回答质量 | 自然、有推荐感 | 结构化、但生硬 |
| 幻觉风险 | 较高（需 verifier 兜底） | 极低（纯提取已知数据） |
| LLM 成本 | 高（4-6 次 LLM 调用） | 低（1 次 verify 调用） |
| 延迟 | 高 | 低 |

---

## 9. 验证与回退对比

### 9.1 验证链

二者**共享**验证工具链：

```
verify_answer(answer, evidence, task_type)
    ├── _build_decision_plan()  # 从 evidence 提取约束
    └── B2MiniVerifier().verify(plan, answer)
        └── call_llm()  # LLM 判断回答是否符合 evidence
```

但**集成位置不同**：

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| verify 位置 | response_subgraph 的 _h_answer_verify 节点 | `run_exploration_planning_workflow` 函数内联 |
| verify 输入 | LLMVerbalizer 生成的 draft_response | `_compose_final_response` 生成的 final_response |
| 重写机制 | 支持（最多 1 次 rewrite → answer_generate ↺） | 不支持（失败直接 fallback） |
| verify 失败路由 | answer_verify → rewrite / fallback_answer | verify → run_clarification_fallback_workflow |

### 9.2 回退链

**discovery_decision 回退路径**（多级）：

```
1. ToolExecute 成功 → EvidenceBuild → EvidenceReview
   └── EvidenceReview.FALLBACK / CLARIFY
       └── response_subgraph → fallback_answer / clarify_response

2. EvidenceReview.REPLAN_EVIDENCE
   └── planning_subgraph → evidence_planner (↺ 最多 config.MAX_REPLAN_EVIDENCE_ROUNDS 次)

3. DecisionReview.REPLAN_EVIDENCE / EXPAND_SEARCH
   └── expand_search → evidence_planner (↺ 有计数器)
   └── target_resolve → clarify_decide

4. DecisionReview.FALLBACK / CLARIFY / UNSUPPORTED_ANSWER
   └── response_subgraph → fallback_answer / clarify_response / emit_response

5. AnswerVerify 失败
   └── rewrite (最多 1 次) → answer_generate ↺
   └── rewrite 用完 → fallback_answer
```

**exploration_planning 回退路径**（单级）：

```
1. _build_subgoals → too_many_subgoals/missing_location
   └── run_clarification_fallback_workflow()

2. _tool_round_search → any_failure
   └── run_clarification_fallback_workflow(reason="no_result")

3. _tool_round_expand → any_failure
   └── run_clarification_fallback_workflow(reason="tool_failure")

4. verify_answer → not passed
   └── run_clarification_fallback_workflow(reason="exploration_verifier_rejected")
```

### 9.3 回退对比

| 维度 | discovery_decision | exploration_planning |
|---|---|---|
| 回退层级数 | 4-5 级（逐步降级） | 1 级（一刀切） |
| 中间恢复路径 | 有（replan / expand / rewrite） | 无 |
| 计数器保护 | 有（MAX_REPLAN_EVIDENCE_ROUNDS / MAX_EXPAND_SEARCH_ROUNDS） | 无 |
| 降级输出 | 支持（DEGRADE_ANSWER → 用已有证据回答） | 不支持 |
| 澄清 | 支持（CLARIFY → clarify_response） | 支持（委托 clarification_fallback） |
| 全链路 fallback | response_subgraph → fallback_answer / clarify_response | 直接调用 run_clarification_fallback_workflow |

---

## 10. 状态与 Schema 对比

### 10.1 discovery_decision 使用的状态字段

通过主链路子图填充大量 GraphState 字段：

| 阶段 | 状态字段 |
|---|---|
| 规划 | `semantic_frame`, `goal_plan`, `goal_review_result`, `resolve_shop_result`, `candidate_set`, `execution_plan`, `validated_plan` |
| 执行 | `tool_results`, `tool_result_set`, `evidence_pack`, `review_results` |
| 决策 | `answer_plan`, `decision_review_result` |
| 回答 | `final_response`, `verify_result`, `draft_response`, `rewrite_count` |
| 路由 | `planning_route`, `execution_review_route`, `response_route` |

### 10.2 exploration_planning 使用的状态字段

| 字段 | 作用 |
|---|---|
| `exploration_plan` | ExplorationPlan 对象（完整 schema） |
| `evidence_pack` | EvidencePack 对象 |
| `answer_plan` | AnswerPlan 对象 |
| `final_response` | 字符串回答 |
| `draft_response` | 同 final_response |
| `subgoals` | 子目标列表（用于后续渲染） |
| `has_temporal_sequence` | 是否有时序关系 |
| `expected_output` | 期望输出描述 |
| `exploration_round_count` | 工具轮次计数 |
| `tool_availability` | 可用工具白名单 |
| `location_status` | 位置状态 |
| `user_location` | 用户位置 |
| `workflow_run_status` | "completed" 或 "fallback" |

### 10.3 Schema 对比

| Schema | discovery_decision | exploration_planning |
|---|---|---|
| **GoalPlan** | ✓ GoalPlanner LLM 生成 | ✗ 不使用 |
| **ExecutionPlan** | ✓ EvidencePlanner LLM 生成（含 tool_calls + stages） | ✓ 手动构造（tool_calls=[]） |
| **EvidencePack** | ✓ build_evidence() 全量构建 | ✓ build_evidence() 部分构建 |
| **DecisionPlan** | ✓ DecisionPlanner LLM 生成 | ✗ 跳过 |
| **AnswerPlan** | ✓ decision_to_answer_plan 转换 | ✓ 手动构造 |
| **ExplorationPlan** | ✗ 不使用 | ✓ 核心 schema |
| **ComparisonMatrix** | ✓ 比较流程中构建 | ✗ 不使用 |
| **RankingSnapshot** | ✓ 推荐/比较流程中构建 | ✗ 不使用 |

### 10.4 ExplorationPlan 与 EvidencePack 的分工

在 exploration_planning 中，**ExplorationPlan** 承担了"规划信息 + 执行结果"的双重角色：

```
ExplorationPlan (核心 schema)
  ├── task_type, goal_type, expected_output
  ├── has_temporal_sequence：多子目标时序关系
  ├── subgoals: list[ExplorationSubgoal]
  │     ├── kind, query, sequence_order, temporal_relation
  │     ├── tool_rounds: 每轮工具调用记录
  │     ├── candidate_shops: 搜索候选列表
  │     └── selected_candidate: 最终选中的店铺
  ├── tool_rounds_used, tool_names_used
  └── location_required, location_available

EvidencePack (共享 schema)
  └── evidence_items: 详情工具调用的证据
```

而在 discovery_decision 中，规划信息和执行结果是**分离**的：
- **GoalPlan**：规划信息
- **ExecutionPlan**：执行计划
- **EvidencePack**：执行结果
- **DecisionPlan**：决策结果

---

## 11. 测试覆盖对比

### 11.1 测试文件

| 工作流 | 测试文件 | 测试函数数 |
|---|---|---|
| discovery_decision | 隐含在 `test_orchestration_router.py` | 1 个相关测试 |
| discovery_decision | `test_phase7_workflows.py` | 无直接测试 |
| exploration_planning | `test_exploration_planning_workflow.py` | 10 个专用测试 |
| 路由层 | `test_orchestration_router.py` | 涵盖两种模式路由 |

### 11.2 路由测试

```python
# test_orchestration_router.py
test_orchestration_router_prefers_discovery_decision_for_recommendation()
  → 验证推荐请求路由到 discovery_decision

test_orchestration_router_prefers_exploration_planning_for_trip_plan()
  → 验证行程规划请求路由到 exploration_planning
```

### 11.3 exploration_planning 专用测试

```python
test_exploration_planning_workflow.py (10 个测试函数)：

1. test_registry_entry_is_real_callable()
   → 验证注册条目 is_real=True, entry_node="response_subgraph", callable="run_exploration_planning_workflow"

2. test_workflow_runner_can_schedule_exploration()
   → 验证 workflow_runner 能调度 exploration_planning

3. test_exploration_subgoal_limits(task_type, raw_text, max_subgoals)
   → 参数化测试：3 种任务模板的子目标数量限制
   → 验证：工具调用只使用 ALLOWED_TOOLS

4. test_exceeding_three_subgoals_falls_back()
   → 5 子目标 → FALLBACK (too_many_subgoals)

5. test_missing_location_falls_back()
   → 无位置信息 → FALLBACK (missing_location)

6. test_tool_failure_does_not_hallucinate()
   → 工具失败 → FALLBACK，不产生幻觉

7. test_no_forbidden_future_tools_and_no_state_pollution()
   → 验证不允许的工具不在调用列表中
   → 验证不污染 session_state 的 orchestration 字段

8. test_existing_workflows_still_route_correctly()
   → 验证其他 workflow（discovery_decision, deterministic_tool, direct_response）路由正确

9. test_workflow_runner_routes_exploration_to_response_subgraph()
   → 验证 _route_workflow_runner("exploration_planning") → "response_subgraph"
```

### 11.4 discovery_decision 测试覆盖缺口

| 测试维度 | 覆盖情况 |
|---|---|
| 路由正确性 | ✓ 通过 `test_orchestration_router_prefers_discovery_decision_for_recommendation` |
| planning_subgraph 节点测试 | △ 通过 `test_goal_planner`, `test_evidence_planner` 等间接覆盖 |
| execution_review_subgraph 节点测试 | △ 通过 `test_execution_plan_validator`, `test_evidence_review` 等间接覆盖 |
| 全工作流集成测试 | ✗ 无直接端到端测试 |
| 失败场景测试 | ✗ 无专用 fail 测试 |
| 重试/重规划边界测试 | ✗ 无循环边界测试 |

---

## 12. 设计权衡分析

### 12.1 discovery_decision 的架构决策

**优势**：
- **通用性强**：同一套 plan-execute-review 架构可处理 6 种不同任务类型
- **LLM 灵活性**：GoalPlanner/EvidencePlanner/DecisionPlanner 都能适应任意 query
- **容错性好**：多级回退路径，能自动 replan/expand/retry
- **证据完备**：通过 EvidenceReview 检查证据充分性，通过 DecisionReview 检查决策质量
- **自然输出**：LLMVerbalizer 能生成自然、有推荐感的回答

**劣势**：
- **架构复杂**：3 个子图 + 大量条件边 + 计数器逻辑，理解门槛高
- **LLM 成本高**：全程 4-6 次 LLM 调用（GoalPlanner + GoalReview + EvidencePlanner + EvidenceReview + DecisionPlanner + DecisionReview + LLMVerbalizer + B2MiniVerifier）
- **延迟大**：串行 LLM 调用链导致响应时间长
- **测试困难**：需要 mock 多个 LLM 调用点，集成测试覆盖不足
- **状态体积大**：在 GraphState 中累积大量中间数据

### 12.2 exploration_planning 的架构决策

**优势**：
- **实现简单**：单个 ~760 行函数包含全部逻辑，无子图依赖
- **零 LLM 规划**：模板驱动 + 规则拆分，完全确定性
- **低延迟**：1 次 LLM 调用（B2MiniVerifier）即可完成
- **可控性高**：回答格式固定，无幻觉风险
- **测试简单**：无 LLM 依赖，容易 mock dispatch_tool_call
- **状态隔离**：不依赖主链路子图状态，独立产出所有 schema

**劣势**：
- **覆盖范围窄**：仅覆盖 5 种预设场景，无模板的任务直接 fallback
- **扩展性差**：新增任务类型需要修改 `_TASK_TEMPLATES` 字典
- **候选选择单一**：总是取 `candidates[0]`，不支持用户真实偏好决策
- **无容错分级**：任何错误都直接 fallback，无降级或重试
- **回答生硬**：确定性组合格式固定，缺乏自然语言推荐感
- **子目标固定**：最多 3 个子目标，不支持更复杂的多步规划

### 12.3 本质差异：通用 vs 专用

```
discovery_decision = 通用工作流引擎
  - 类似"完整的 LangGraph 应用程序"
  - 通过插件（子图）方式扩展能力
  - 适用于：任何需要 LLM 推理 + 工具调用 + 证据验证的场景

exploration_planning = 专用领域 handler
  - 类似"微服务中的单一领域服务"
  - 通过注册表（workflow_registry）集成
  - 适用于：固定流程、高确定性要求、低延迟场景
```

### 12.4 这种设计是否合理？

**针对当前场景，这种分叉设计是合理的**，理由如下：

1. **业务需求差异大**：推荐/比较需要 LLM 推理用户偏好，行程规划需要结构化输出
2. **响应要求不同**：推荐可接受 3-5 秒延迟，行程规划需快速返回结构化结果
3. **控制需求不同**：推荐需要自然语言弹性输出，行程规划需要精确格式控制
4. **复用成本**：如果将 exploration_planning 改造为子图 + LLM 驱动，将显著增加复杂性和延迟，而业务收益有限

**但需要注意**：
1. 两个工作流之间没有共享的"规划层抽象"——如果未来增加第三个工作流，可能产生重复代码
2. exploration_planning 的证据构建跳过 resolved_target 和 recommendation_candidates，如果未来需要跨工作流证据共享，需要重构
3. exploration_planning 的 verify_answer 内联调用在失败时不重写，这个策略与其他 workflow 不一致

---

## 13. 演进建议

### 建议 1：为 exploration_planning 增加子目标级别的重试

当前 `_tool_round_search` 和 `_tool_round_expand` 使用全局 `any_failure` 标记，任一子目标失败即全流程 fallback。可以改为按子目标记录失败，在最终回答中注明"某某子目标暂无法获取"。

**影响**：提高成功率，不牺牲确定性。

### 建议 2：共享证据构建的参数标准化

`build_evidence()` 在两个工作流中的调用签名不一致：
```python
# discovery_decision
build_evidence(tool_results, resolved_target, execution_plan, recommendation_candidates, comparison_targets)

# exploration_planning
build_evidence(tool_results, {}, minimal_execution_plan, [], [])
```

可以考虑统一为命名参数，或提供一个 `build_evidence_from_raw()` 包装函数。

### 建议 3：抽象规划层接口

如果计划增加第三个 bounded plan-execute-review 工作流（如"附近活动规划"），建议提取一个抽象接口：

```python
class WorkflowPlanner(ABC):
    def plan(self, state, decision) -> PlanResult
    def execute(self, plan) -> ExecutionResult
    def review(self, evidence) -> ReviewResult
```

当前两个工作流的规划层完全不同（LLM 驱动 vs 模板驱动），抽象接口可以统一编排模式而不约束实现。

### 建议 4：补全 discovery_decision 的端到端测试

当前 `test_exploration_planning_workflow.py` 有 10 个专用测试，但 discovery_decision 的端到端集成测试缺失。建议增加：

- `test_discovery_decision_recommendation_flow()`：推荐全流程
- `test_discovery_decision_comparison_flow()`：比较全流程  
- `test_discovery_decision_tool_fallback()`：工具失败回退
- `test_discovery_decision_replan_boundary()`：重规划循环边界

### 建议 5：可选的"混合模式"

对于 future work，可以考虑将 exploration_planning 的模板规划能力注入 discovery_decision 的规划层：

- 当 `task_type` 是已知规划类型时，使用模板快速生成 GoalPlan（无需 LLM）
- 当 `task_type` 是未知类型时，回退到 LLM GoalPlanner
- 这可以在不增加 LLM 调用次数的情况下，提高 planning_subgraph 的响应速度

---

## 附录：代码位置速查

| 组件 | 文件路径 | 行数 |
|---|---|---|
| discovery_decision dispatch handler | `local_life_agent/engine/workflow_registry.py:138` | 11 |
| exploration_planning handler | `local_life_agent/engine/workflows/exploration_planning_workflow.py` | 762 |
| planning_subgraph | `local_life_agent/engine/subgraphs/planning_subgraph.py` | 825 |
| execution_review_subgraph | `local_life_agent/engine/subgraphs/execution_review_subgraph.py` | 368 |
| response_subgraph | `local_life_agent/engine/subgraphs/response_subgraph.py` | 456 |
| workflow_runner | `local_life_agent/engine/workflow_runner.py` | 263 |
| workflow registry | `local_life_agent/engine/workflow_registry.py` | 203 |
| 条件边路由 | `local_life_agent/engine/_routes.py` | 435 |
| 编排路由策略表 | `local_life_agent/planning/orchestration_router.py` | 1096 |
| 证据构建 | `local_life_agent/planning/evidence/evidence_builder.py` | ~1300 |
| 回答验证 | `local_life_agent/answer/verifier.py` | 428 |
| B2MiniVerifier | `local_life_agent/answer/b2_mini_verifier.py` | 567 |
| 执行核心 | `local_life_agent/core/execution_core.py` | 30 |
| tool gateway | `local_life_agent/tools/gateway.py` | ~500 |
| 主图构建 | `local_life_agent/engine/graph_builder.py` | 615 |
| 全局 schemas | `local_life_agent/domain/schemas.py` | 855 |
| exploration_planning 测试 | `local_life_agent/tests/test_exploration_planning_workflow.py` | ~400 |
| 编排路由测试 | `local_life_agent/tests/test_orchestration_router.py` | ~170 |
