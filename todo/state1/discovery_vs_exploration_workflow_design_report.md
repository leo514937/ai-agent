# Discovery Decision vs Exploration Planning Workflow Design Report

## 1. Executive Summary

- `discovery_decision` 和 `exploration_planning` 都属于 bounded workflow，但粒度不同：前者是 candidate-level decision flow，后者是 subgoal / itinerary composition flow。
- 二者确实是 `orchestration_router -> workflow_runner` 后面的 sibling workflow name 分叉；但它们不是“同一套模块换 prompt”，下游链路和数据契约不同。
- `discovery_decision` 当前不是一个独立的 `discovery_decision_workflow.py` 文件，而是被 registry 映射到 `planning_subgraph -> execution_review_subgraph -> response_subgraph` 这条主链。
- `exploration_planning` 是独立 handler `run_exploration_planning_workflow`，内部自己做 subgoal 拆分、两轮工具执行、EvidencePack 组装、最终回答拼接与校验。
- 主要共享模块是：`orchestration_router`、`workflow_registry`、`workflow_runner`、`tools/gateway`、`EvidencePack`、`AnswerPlan`、`verify_answer`、`state_update_plan`、`SessionState`。
- 主要不共享的是：`planning_subgraph`、`execution_review_subgraph`、`CandidateSet`、`DecisionPlanner / DecisionReview` 这套 discovery 主链专有的规划与审查对象。
- 数据流转最大差异在于：`discovery_decision` 先形成 `CandidateSet` 和 `ExecutionPlan.tool_calls`，再做批量工具执行和 evidence/decision review；`exploration_planning` 先形成 `ExplorationPlan.subgoals`，再按子目标执行搜索和扩展，最后直接拼接答案并验证。
- 当前设计总体合理，更像“兄弟 workflow + 共享底层能力”，不建议硬合成一个通用 plan-execute agent。
- 但当前实现与需求清单并不完全同构：需求中点名的多个文件和文档在当前分支不存在，且 `discovery_decision` 的实现形态与文件名不一致。
- 结论：`PARTIAL PASS`。边界基本清楚，复用也合理，但文档/文件布局、状态契约与测试覆盖仍有明显缺口。

## 2. Scope and Methodology

已检查的关键文件：

- 路由与注册：`local_life_agent/engine/graph_builder.py`、`local_life_agent/engine/_routes.py`、`local_life_agent/engine/workflow_registry.py`、`local_life_agent/planning/orchestration_router.py`
- discovery 主链：`local_life_agent/engine/subgraphs/planning_subgraph.py`、`local_life_agent/engine/subgraphs/execution_review_subgraph.py`、`local_life_agent/core/execution_core.py`、`local_life_agent/tools/gateway.py`
- exploration：`local_life_agent/engine/workflows/exploration_planning_workflow.py`
- 状态与 schema：`local_life_agent/domain/graph_state.py`、`local_life_agent/domain/state.py`、`local_life_agent/domain/schemas.py`、`local_life_agent/domain/decision.py`、`local_life_agent/domain/evidence.py`、`local_life_agent/domain/goal.py`
- 测试：`local_life_agent/tests/test_workflow_registry.py`、`local_life_agent/tests/test_workflow_runner.py`、`local_life_agent/tests/test_orchestration_router.py`、`local_life_agent/tests/test_exploration_planning_workflow.py`、`local_life_agent/tests/test_mapreduce_semantics.py`、`local_life_agent/tests/test_comprehensive_graph_e2e.py`、`local_life_agent/tests/test_phase7_workflows.py`、`local_life_agent/tests/test_decision_planner.py`、`local_life_agent/tests/test_phase_d_decision_contracts.py`、`local_life_agent/tests/test_05_graph.py`

未找到的需求文件：

- `local_life_agent/engine/workflows/discovery_decision_workflow.py`
- `local_life_agent/planning/candidate_decision.py`
- `local_life_agent/planning/reference_resolver.py`
- `local_life_agent/domain/session_state.py`（实际存在的是 `local_life_agent/domain/state.py`）
- `todo/00_current_architecture_review.md`
- `todo/01_target_architecture.md`
- `todo/02_core_module_abstraction.md`
- `todo/03_workflow_design.md`
- `todo/04_migration_phases.md`
- `todo/05_state_and_schema_design.md`
- `todo/07_testing_and_acceptance.md`
- `todo/10_orchestration_router_design.md`
- `todo/11_workflow_pattern_mapping.md`

额外参考：

- `todo/discovery_decision_mapreduce_semantics_report.md` 也存在，且其结论与本次核对一致：discovery 是 batch/tool-level 的 MapReduce-style 执行，不是 LangGraph-native `Send/reducer`。

已运行验证：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_exploration_planning_workflow.py local_life_agent/tests/test_mapreduce_semantics.py local_life_agent/tests/test_orchestration_router.py -q`

结果：

- compileall 通过
- pytest：`29 passed`

## 3. Routing and Fork Relationship

### 结论

- `orchestration_router` 负责把语义任务归到 `discovery_decision` 或 `exploration_planning`。
- `workflow_runner` 是真正的 dispatch fork 点。
- 二者是 sibling workflow name 分叉，但不是同构实现。
- `discovery_decision` 走共享主链子图；`exploration_planning` 走独立 handler，再回到 `response_subgraph` 做 pass-through。

### 证据

- `local_life_agent/planning/orchestration_router.py:148-238` 把 `shop_search / recommendation / comparison / condition_refine / scene_recommendation / deal_compare` 映射到 `discovery_decision`，把 `local_trip_plan / date_plan / family_activity_plan / coffee_then_dinner / eat_and_play_plan` 映射到 `exploration_planning`。
- `local_life_agent/planning/orchestration_router.py:976-1093` 生成 `OrchestrationDecision` 与 shadow patch。
- `local_life_agent/engine/workflow_registry.py:24-25` 定义 `LEGAL_WORKFLOW_NAMES`，包含 `discovery_decision` 与 `exploration_planning`。
- `local_life_agent/engine/workflow_registry.py:138-196` 中：
  - `discovery_decision` 的 `entry_node="planning_subgraph"`
  - `exploration_planning` 的 `entry_node="response_subgraph"`
- `local_life_agent/engine/_routes.py:298-302`：
  - `workflow_name == "discovery_decision"` 时返回 `planning_subgraph`
  - 其他 registered workflow 返回 `response_subgraph`
- `local_life_agent/engine/graph_builder.py:334-338` 将 `workflow_runner` 挂到主图，并把 `_route_workflow_runner` 作为 conditional edge。
- `local_life_agent/engine/graph_builder.py:441-469` 的节点/边表也明确展示：
  - `orchestration_router_shadow -> workflow_runner`
  - `workflow_runner -> planning_subgraph`
  - `planning_subgraph -> execution_review_subgraph`
  - `execution_review_subgraph -> response_subgraph`
  - `response_subgraph -> state_update_plan`

### 真实链路图

```text
understanding_subgraph
  -> orchestration_router_shadow
  -> workflow_runner
      ├─ discovery_decision
      │    -> planning_subgraph
      │    -> execution_review_subgraph
      │    -> response_subgraph
      │    -> state_update_plan
      └─ exploration_planning
           -> run_exploration_planning_workflow
           -> response_subgraph (pass-through for exploration_plan)
           -> state_update_plan
```

### 是否存在一个调用另一个

- 没有证据表明 `discovery_decision` 调用 `exploration_planning`，也没有反向调用。
- 它们在 registry 和 router 层是并列分支，但 downstream 实现风格不同。

## 4. High-Level Design Difference

### `discovery_decision`

解决的是：

- search
- recommendation
- comparison
- condition_refine
- scene_recommendation
- deal_compare

核心是 candidate-level decision：先确认候选、再取证据、再下决策。

### `exploration_planning`

解决的是：

- local_trip_plan
- date_plan
- family_activity_plan
- coffee_then_dinner
- eat_and_play_plan

核心是 subgoal-level / itinerary-level composition：先拆子目标，再排顺序、跑搜索、选一个候选、再组合答案。

### 关键判断

> 二者不是同一套模块换 prompt，而是不同粒度、不同数据契约、不同 review 逻辑的 workflow。

## 5. Module Reuse Matrix

| Module / Capability | discovery_decision | exploration_planning | Reused? | Notes |
| --- | --- | --- | --- | --- |
| orchestration_router | yes | yes | yes | 同一套 policy table 产出两个 workflow name |
| workflow_registry | yes | yes | yes | 都在 `LEGAL_WORKFLOW_NAMES` 里 |
| workflow_runner | yes | yes | yes | 统一 dispatch 入口 |
| planning_subgraph | yes | no | no | discovery 主链专有 |
| execution_review_subgraph | yes | no | no | discovery 主链专有 |
| response_subgraph | yes | yes | yes | discovery 真正使用；exploration 走 pass-through |
| ExecutionCore.execute_batch | yes | no | no | exploration 直接 `dispatch_tool_call` |
| BatchToolExecutor | yes | no | no | 只在 discovery batch 执行层使用 |
| search_shops | yes | yes | yes | discovery 作为计划工具；exploration 作为子目标搜索 |
| get_shop_detail | yes | yes | yes | discovery 计划中可用；exploration 扩展轮必用 |
| check_open_status | yes | yes | yes | 两边都用 |
| get_distance_eta | yes | yes | yes | 两边都用 |
| get_coupon_list / coupon tool | yes | no | no | discovery 可规划；exploration 当前未实际调用 |
| get_shop_review_summary | yes | yes | yes | discovery 可规划；exploration 仅在 query 含 review 语义时追加 |
| EvidencePack | yes | yes | yes | 两边都作为可验证证据容器 |
| AnswerPlan | yes | yes | yes | 两边都构造回答约束 |
| verify_answer | yes | yes | yes | discovery 在 response_subgraph；exploration 在 workflow 内直接调用 |
| clarification_fallback | yes | yes | yes | 两边都可 fallback |
| CandidateSet | yes | no | no | discovery 专有 |
| ExplorationPlan / Subgoal | no | yes | no | exploration 专有 |

### 小结

- 底层健康复用：router、registry、runner、gateway、evidence/answer/verifier、state update。
- 主链独有：`planning_subgraph`、`execution_review_subgraph`、`CandidateSet`、`DecisionPlan` / `DecisionReviewResult`。
- exploration 独有：`ExplorationPlan`、`ExplorationSubgoal`、子目标模板与两轮执行。
- 目前看起来“应该复用但没有复用”的部分：exploration 的 batch execute 没有复用 `ExecutionCore.execute_batch`，但这未必是坏事，因为 exploration 本身是固定两轮、强确定性的独立实现。

## 6. Plan Stage Comparison

### discovery_decision Plan

输入与处理：

- 读取 `semantic_frame`、`task_type`、`comparison_targets`、`current_shop`、`last_recommendation_list`、`pending_clarification`
- `planning_subgraph.py:342-446` 进入 `target_resolve_candidate_set`
- `planning_subgraph.py:374-445` 生成 `CandidateSet`，并把 `candidate_set` / `effective_candidate_set` 写入 state
- `planning_subgraph.py:624-702` 用 `candidate_set` 和 goal 调 `build_recommendation_execution_plan` / `plan_evidence_with_llm`
- `planning_subgraph.py:706-747` 校验 `execution_plan`

输出到的关键 state 字段：

- `goal_plan`
- `local_life_goal_draft`
- `candidate_set`
- `resolved_target` / `resolve_shop_result`
- `execution_plan`
- `validated_plan`
- `execution_plan_source`
- `review_results`
- `comparison_targets`
- `last_recommendation_list`

### exploration_planning Plan

输入与处理：

- `run_exploration_planning_workflow` 读取 `orchestration_decision`、`semantic_frame`、`task_type`、`user_context`
- `_build_subgoals` 根据 task template / 分句 / facet hints 构造 `subgoals`
- `_build_exploration_plan` 组装 `ExplorationPlan`
- 没有 discovery 那套 `CandidateSet` / `DecisionPlanner` / `DecisionReview` 结构

输出到的关键对象 / state 字段：

- `exploration_plan`
- `execution_plan`（兼容性桥接对象，主要是给后续证据构造使用）
- `subgoals`
- `has_temporal_sequence`
- `expected_output`
- `location_status`
- `user_location`

### 差异总结

- `discovery plan = evidence / candidate decision plan`
- `exploration plan = subgoal / itinerary composition plan`

## 7. Execute Stage Comparison

### discovery_decision Execute

执行路径：

- `planning_subgraph` 产出 `validated_plan`
- `execution_review_subgraph._h_tool_execute`
- 先把 `search_shops` 单独摘出来做 batch 执行
- `ExecutionCore.execute_batch(...)`
- `BatchToolExecutor.execute_sync(...)`
- 对推荐类计划再做第二轮 resolved follow-up calls
- 汇总成 `tool_results` 与 `tool_result_set`

关键证据：

- `execution_review_subgraph.py:109-190` 的 `_h_tool_execute`
- `core/execution_core.py:1-27`
- `tools/gateway.py:89-212`

### exploration_planning Execute

执行路径：

- `_tool_round_search`：每个 subgoal 调一次 `search_shops`
- `_tool_round_expand`：每个 subgoal 取首个候选，再调 `get_shop_detail`、`check_open_status`、`get_distance_eta`，必要时加 `get_shop_review_summary`
- 固定最多两轮，失败直接 fallback 到 clarification / fallback workflow
- 不走 `ExecutionCore.execute_batch`
- 不走 `BatchToolExecutor`

关键证据：

- `exploration_planning_workflow.py:315-387` `_tool_round_search` / `_tool_round_expand`
- `exploration_planning_workflow.py:510-760` 主流程

### MapReduce-style 判断

- 二者都有 MapReduce-style 语义，但都不是 LangGraph-native `Send + reducer`
- discovery 的 map/reduce 是“tool batch -> evidence -> decision”
- exploration 的 map/reduce 是“subgoal batch -> subgoal evidence -> composed answer”
- `GraphState` 里的 reducer 只用于 `event_log` / `trace_spans`，不是业务结果聚合

## 8. Reduce / Evidence / Review / Verify Comparison

### discovery_decision

reduce / review 链路是标准化的：

- `tool_result_set -> EvidencePack`：`evidence_build`
- `EvidencePack -> EvidenceReviewResult`：`evidence_review`
- `EvidencePack + GoalPlan -> DecisionPlan`：`decision_planner`
- `DecisionPlan + EvidenceReviewResult -> DecisionReviewResult`：`decision_review`
- `DecisionPlan -> AnswerPlan`：`response_subgraph._h_answer_plan_build`
- `AnswerPlan + EvidencePack -> verify_answer`

关键证据：

- `execution_review_subgraph.py:197-341`
- `domain/decision.py`
- `domain/evidence.py`
- `response_subgraph.py:177-321`

### exploration_planning

reduce / verify 链路更轻：

- 子目标搜索结果 + 扩展工具结果 -> `build_evidence(...)`
- `_compose_final_response(...)` 直接拼出自然语言答案
- `verify_answer(final_response, evidence, "exploration_plan")`
- 不经过 `evidence_review` / `decision_planner` / `decision_review` 这套标准 P2 审查链

### review 行为差异

- discovery review 更体系化，围绕 evidence / decision / claim binding / winner sufficiency
- exploration review 更偏组合计划可行性 + 最终 answer verify
- 这不是“review prompt 不同”，而是 review 节点和对象本身不同

## 9. Data Flow Diagrams

### discovery_decision Data Flow

```text
user_input
-> GraphState.raw_text / normalized_text
-> semantic_frame / constraints
-> orchestration_decision(workflow_name=discovery_decision)
-> CandidateSet
-> ExecutionPlan.tool_calls / validated_plan
-> tool_results / tool_result_set
-> EvidencePack
-> DecisionPlan
-> AnswerPlan
-> final_response
-> state_update_plan
-> SessionState
```

### exploration_planning Data Flow

```text
user_input
-> GraphState.raw_text / normalized_text
-> semantic_frame / constraints
-> orchestration_decision(workflow_name=exploration_planning)
-> ExplorationPlan / subgoals
-> subgoal search results
-> candidate expansion results
-> execution_plan (compat bridge)
-> EvidencePack
-> AnswerPlan
-> final_response
-> state_update_plan
-> SessionState
```

### 真实字段补充

- discovery 里更关键的是 `candidate_set`、`resolved_target`、`validated_plan`、`p2_decision_plan`
- exploration 里更关键的是 `exploration_plan`、`subgoals`、`tool_availability`、`user_location`

## 10. State Field Comparison

| State field | discovery_decision read/write | exploration_planning read/write | Risk / Notes |
| --- | --- | --- | --- |
| orchestration_decision | R via `workflow_runner` | R via `run_exploration_planning_workflow` | 共享路由契约，正常 |
| candidate_set | W in `planning_subgraph`; R in evidence/decision stages | not used | discovery 专有，探索不应写 |
| current_shop | W in `state_update_plan` for single-shop resolution | not used | 探索不应污染会话 |
| last_recommendation_list | W in discovery comparison/recommendation flows; R by router / state update | not used | discovery 主链历史字段 |
| comparison_targets | W/R in discovery comparison flows | not used | discovery 专有 |
| active_constraints | R from session / semantic hints; not explicitly persisted by state_update_plan | R from semantic_frame hints only | 目前 persistence 较弱，需文档化 |
| pending_clarification | R/W in both discovery and exploration fallback paths | R/W | 两边都依赖，但触发原因不同 |
| execution_plan | W in discovery planning; also used by validation / tool execute | W in exploration as compatibility plan | 同名不同语义，需注明 |
| tool_results | W in discovery tool execute | W in exploration expand round | 共享结果容器 |
| tool_result_set | W in discovery tool execute | W in exploration mostly not used / less central | discovery 主链更依赖 |
| evidence_pack | W in both | W in both | 共享核心证据容器 |
| answer_plan | W in both | W in both | 共享回答约束容器 |
| final_response | W in both | W in both | discovery 由 response_subgraph 产出；exploration 先自行产出 |
| state_update_plan | W in both via state_update subgraph | W in both via state_update subgraph | 集中写回仍成立 |
| event_log | append in both | append in both | 仅观测字段，使用 reducer |
| trace_spans | append in both | append in both | 仅观测字段，使用 reducer |
| exploration_plan | not used | W in exploration | exploration 专有 |
| subgoals | not used | W in exploration | exploration 专有 |
| user_location | not used | W in exploration | exploration 专有 |
| comparison_result | W in discovery comparison | not used | discovery 专有 |

### 重点判断

- 字段复用是健康的，但 `execution_plan` 在两条 workflow 中语义不同，必须在文档里写清楚。
- exploration 没有绕开 state 协议，但它绕开了 discovery 的 candidate/decision 契约，这是合理的。
- `state_update_plan` 仍是集中写回入口，这一点保持一致。

## 11. Prompt / Policy Difference

### discovery_decision

- `planning_subgraph` 中的 `_h_goal_planner`、`_h_evidence_planner`、`_h_decision_planner` 都可能调用 LLM（通过 `call_llm` 与 `plan_*_with_llm`）。
- `response_subgraph` 里 `answer_generate` 也会调用 answer generator / verifier 体系。
- 对 discovery 而言，prompt / policy 只是其中一层，真正差异是对象链路本身：GoalPlan -> CandidateSet -> ExecutionPlan -> EvidencePack -> DecisionPlan -> AnswerPlan。

### exploration_planning

- `run_exploration_planning_workflow` 是确定性实现，`llm_called=False`，`llm_backend="deterministic"`。
- 它通过模板、分句、facet hints 构造 `ExplorationPlan`，然后直接拼答案、直接验证。
- 这里没有 discovery 那套 planner/reviewer LLM 组合。

### 结论

> 如果二者模块、状态对象、工具执行方式、review 方式不同，则不能说只是 prompt 不同。

本次核对结论是：它们确实不是只换 prompt。

## 12. Testing Coverage Comparison

| Test file / test name | Covers discovery | Covers exploration | What it verifies | Gaps |
| --- | --- | --- | --- | --- |
| `test_orchestration_router.py` | yes | yes | router 把 recommendation/comparison 送 discovery，把 trip plan 送 exploration | 不验证完整 graph 运行 |
| `test_workflow_registry.py` | yes | yes | registry 白名单、entry_node、exploration handler 可调用 | discovery 仍无独立 workflow file |
| `test_workflow_runner.py` | yes | yes | `workflow_runner` 对两个 workflow 的 dispatch 与 graph contract | 未覆盖所有 fallback 分支 |
| `test_exploration_planning_workflow.py` | no | yes | 子目标数量、两轮工具、fallback、无 state pollution | 主要依赖 fake dispatch |
| `test_mapreduce_semantics.py` | yes | no | discovery 的 batch/tool 执行不是 LangGraph Send/reducer | 只覆盖 discovery 语义 |
| `test_decision_planner.py` | yes | no | DecisionPlanner 以 evidence 为准，不拿 snapshot 当 winner | 不覆盖 exploration |
| `test_phase_d_decision_contracts.py` | yes | no | decision contract 与 evidence/winner 约束 | 不覆盖 exploration |
| `test_05_graph.py` | yes | 部分 | graph 路由、tool_execute、evidence_review、answer_verify | 主要是主链单元测试 |
| `test_subgraph_core_integration.py` | yes | no | target_resolve / tool_execute / state_update 的核心整合 | 不覆盖 exploration |
| `test_phase7_workflows.py` | no | 间接 | direct_response / clarification_fallback / runner pass-through | exploration 不在该文件主线 |
| `test_comprehensive_graph_e2e.py` | yes | 间接 | 真实 graph 覆盖 `workflow_runner -> planning_subgraph -> execution_review_subgraph -> response_subgraph` | exploration 的真实 e2e 仍较少 |

### 覆盖观察

- 有 fake / spy backend：`tests/fakes/*`、`conftest.py`、mock data fixtures。
- 有真实 LLM 相关测试：`test_real_llm_*`。
- 有真实 Java 后端 live integration：`tests/integration/test_java_backend_live.py`。
- 但 discovery / exploration 的“真实后端 + 真实 graph”组合场景仍偏少，尤其 exploration 目前主要靠 workflow 单测。

## 13. Design Assessment

1. 当前把二者拆成 sibling workflow 是否合理？

   - 合理。它们解决的问题粒度不同，数据对象不同，review 方式也不同。

2. 是否应该合并成一个通用 plan-execute agent？

   - 不建议合并。强行合并会把 `CandidateSet / DecisionPlan` 和 `ExplorationPlan / Subgoal` 混在一起，抽象会过度。

3. 是否应该抽出共享的 planner/executor/reviewer 模块？

   - 只抽底层共享件，不要抽成同一个高层 workflow。
   - 健康共享：router、registry、runner、gateway、EvidencePack、AnswerPlan、verify_answer、state update。

4. 哪些共享是健康的？

   - `tools/gateway`、`ExecutionCore`、`EvidencePack`、`AnswerPlan`、`SessionWriteDirective`、`state_update_plan`、`workflow_runner`

5. 哪些共享会导致抽象过度？

   - 把 discovery 的 `CandidateSet`、`DecisionPlan`、`DecisionReview` 硬套给 exploration
   - 把 exploration 的 `ExplorationPlan`、`Subgoal` 强行塞进 discovery 主链

6. discovery_decision 是否应该继续作为推荐/对比主链路？

   - 是，现有主链契约就是围绕 candidate decision / evidence / answer plan 设计的。

7. exploration_planning 是否应该继续作为组合计划链路？

   - 是，且它应该保持更确定性的 itinerary handler 风格。

8. 是否存在职责重叠场景，例如“推荐一家适合约会后吃饭的咖啡店和餐厅”？

   - 有。此类请求同时包含推荐与计划语义。

9. 遇到重叠场景，router 应如何判定？

   - 先看用户意图主轴：如果目标是“找一家/对比几家”优先 discovery；如果目标是“安排顺序/行程”优先 exploration。
   - 当前 policy table 已体现这一点；重叠时最好以 task_type / semantic_frame.primary_task / temporal_sequence 信号为准。

## 14. Key Findings

### P1

- 需求中点名的多个文件不存在，尤其是 `discovery_decision_workflow.py`、`candidate_decision.py`、`reference_resolver.py`、`domain/session_state.py`、一批 `todo/00..11` 文档；这说明当前分支与需求清单的文件布局不一致。
- `discovery_decision` 并不是独立 workflow 文件，而是 registry 将其映射到 `planning_subgraph` 的别名式入口；如果只看文件名，很容易误以为它有独立实现。
- `exploration_planning` 不是 discovery 的“prompt 变体”，而是独立 deterministic workflow，直接绕过 discovery 的 `CandidateSet -> DecisionPlan -> DecisionReview` 链路。

### P2

- `exploration_planning_workflow.py` 声明了 `get_coupon_list` 等工具可用，但实际 `_tool_round_expand` 并不调用 coupon/deal 工具，存在“能力表比实际执行面更宽”的轻微不一致。
- `execution_plan` 在两条 workflow 中语义不同，但字段名相同，后续若不在文档里注明，很容易造成误读。
- `active_constraints` 在 SessionState 中存在，但当前 `state_update_plan` 没有把它作为显式写回中心字段来处理，属于契约可读性问题。

### P0

- 未发现明确 P0。当前问题更多是边界与契约清晰度，而不是严重运行时错误。

## 15. Recommended Next Steps

### Step 1: Lock the sibling workflow boundary

- 新增或强化 `workflow_registry` / `workflow_runner` / `route_orchestration` 测试。
- 重点断言：
  - `discovery_decision -> planning_subgraph`
  - `exploration_planning -> response_subgraph`
  - `workflow_callable` 与 `entry_node` 一一对应

### Step 2: Document shared modules and owned modules

- 把“共享底座”和“workflow 专有层”写进架构文档。
- 明确说明：
  - shared: router / registry / runner / gateway / evidence / answer / state update
  - discovery-owned: candidate resolution / evidence decision chain
  - exploration-owned: subgoal planning / itinerary composition

### Step 3: Align data contracts

- 统一或注释这些字段的语义：
  - `execution_plan`
  - `tool_result_set`
  - `final_response`
  - `state_update_plan`
- 不建议强行统一：
  - `CandidateSet`
  - `DecisionPlan`
  - `ExplorationPlan`

### Step 4: Improve exploration_planning integration

- 当前更适合保留独立 handler，而不是塞回 `planning_subgraph` / `execution_review_subgraph`。
- 可以考虑抽取少量共享 helper，但不要把 exploration 改造成 discovery 的子类流程。

### Step 5: Add E2E tests

- discovery 侧补一个真实 graph 场景：
  - recommendation / comparison 至少各一条
  - 验证 `workflow_runner -> planning_subgraph -> execution_review_subgraph -> response_subgraph`
- exploration 侧补一个真实 graph 场景：
  - `coffee_then_dinner` 或 `date_plan`
  - 验证不会污染 `current_shop` / `last_recommendation_list` / `comparison_targets`
  - 验证最终仍能进入 `state_update_plan`

## 16. Final Verdict

`discovery_decision` 和 `exploration_planning` 确实是两个不同粒度的 bounded plan-execute-review workflow，也确实是 `orchestration_router / workflow_runner` 后面的 sibling 分支；但它们绝不是“只换 prompt”。它们共享底层工具网关、证据/回答/状态更新基础设施，却在目标粒度、Plan/Execute/Review 对象、状态字段、以及是否走 discovery 主链上明显不同。当前设计方向是合理的，建议保持拆分，只强化边界文档、状态契约和真实 E2E 测试。
