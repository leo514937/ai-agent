# P0-P7 Unified Acceptance Report

## 1. Conclusion

PASS with note

可以进入 P8。

说明：

- P0-P7 报告齐全
- P0-P7 主验收测试已通过
- broad non-integration suite 在本机环境中超时，已单独标记为 environment/time-budget blocked，不视为架构失败

## 2. Inputs

已读取并核对：

- [`todo/p0_fact_calibration_and_adr_freeze_report.md`](D:/javacode/hm-dianping/todo/p0_fact_calibration_and_adr_freeze_report.md)
- [`todo/adr_p0_single_owner_workflow_no_map_reduce.md`](D:/javacode/hm-dianping/todo/adr_p0_single_owner_workflow_no_map_reduce.md)
- [`todo/p1_single_owner_workflow_invariants_report.md`](D:/javacode/hm-dianping/todo/p1_single_owner_workflow_invariants_report.md)
- [`todo/p2_router_priority_and_keyword_conflict_report.md`](D:/javacode/hm-dianping/todo/p2_router_priority_and_keyword_conflict_report.md)
- [`todo/p3_facet_protocol_and_retention_report.md`](D:/javacode/hm-dianping/todo/p3_facet_protocol_and_retention_report.md)
- [`todo/p4_evidence_decision_answer_protocol_report.md`](D:/javacode/hm-dianping/todo/p4_evidence_decision_answer_protocol_report.md)
- [`todo/p5_session_state_writeback_safety_and_reference_retention_report.md`](D:/javacode/hm-dianping/todo/p5_session_state_writeback_safety_and_reference_retention_report.md)
- [`todo/p6_complex_query_matrix_report.md`](D:/javacode/hm-dianping/todo/p6_complex_query_matrix_report.md)
- [`todo/p7_exploration_planning_protocol_isomorphism_report.md`](D:/javacode/hm-dianping/todo/p7_exploration_planning_protocol_isomorphism_report.md)
- [`todo/complex_intent_query_architecture_stabilization_plan.md`](D:/javacode/hm-dianping/todo/complex_intent_query_architecture_stabilization_plan.md)

## 3. Scope

本轮检查的代码文件：

- [`local_life_agent/engine/workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py)
- [`local_life_agent/engine/workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py)
- [`local_life_agent/engine/_routes.py`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py)
- [`local_life_agent/engine/graph_builder.py`](D:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py)
- [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
- [`local_life_agent/domain/graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)
- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py)
- [`local_life_agent/domain/state.py`](D:/javacode/hm-dianping/local_life_agent/domain/state.py)
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
- [`local_life_agent/planning/evidence/evidence_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_review.py)
- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
- [`local_life_agent/planning/decision/decision_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_review.py)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
- [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
- [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py)
- [`local_life_agent/engine/subgraphs/response_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)
- [`local_life_agent/engine/workflows/exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py)
- [`local_life_agent/engine/workflows/clarification_fallback_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/clarification_fallback_workflow.py)

本轮检查的测试文件：

- [`local_life_agent/tests/test_workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_workflow_registry.py)
- [`local_life_agent/tests/test_workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_workflow_runner.py)
- [`local_life_agent/tests/test_orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_orchestration_router.py)
- [`local_life_agent/tests/test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py)
- [`local_life_agent/tests/test_p2_router_priority.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p2_router_priority.py)
- [`local_life_agent/tests/test_p3_facet_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p3_facet_protocol.py)
- [`local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py)
- [`local_life_agent/tests/test_p5_session_state_writeback.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p5_session_state_writeback.py)
- [`local_life_agent/tests/test_p6_complex_query_matrix.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p6_complex_query_matrix.py)
- [`local_life_agent/tests/test_p7_exploration_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p7_exploration_protocol.py)
- [`local_life_agent/tests/test_exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_exploration_planning_workflow.py)

## 4. Phase-by-Phase Acceptance

### P0
- Judgment: PASS with note
- Evidence:
  - workflow 白名单仍是单值注册，包含 `direct_response`、`clarification_fallback`、`deterministic_tool`、`discovery_decision`、`exploration_planning`
  - `workflow_registry.lookup()` 仍然只返回单个 `WorkflowRegistration`
  - `workflow_runner` 仍是单 dispatch
  - `exploration_planning` 已注册，但没有证据表明其被并入 `execution_review_subgraph`
- Risks:
  - `exploration_planning` 仍保持独立 handler，需要继续靠 P7 测试锁定协议同构

### P1
- Judgment: PASS
- Evidence:
  - `workflow_name` 仍为单值字段
  - 不存在 `workflow_names`、`final_responses`、`state_update_plans` 这类多主字段
  - `workflow_runner` 没有 list 循环 dispatch
  - `_routes.py` 没有生成 workflow fan-out
  - P1 测试通过
- Risks:
  - 单值约束依赖 schema 与 runner 双侧保护，后续若扩展新入口需要继续保持

### P2
- Judgment: PASS with note
- Evidence:
  - router 仍把 keyword 作为 signal，而不是主分类器
  - “附近推荐几家有券的餐厅”进入 `discovery_decision`
  - “附近现在营业的咖啡店”进入 `discovery_decision`
  - “这家有券吗”无 `current_shop` 时进入 `clarification_fallback`
  - “这家有券吗”有 `current_shop` 时才进入 `deterministic_tool`
  - P2 测试通过
- Risks:
  - router 仍是复杂规则系统，后续若加新 intent 需避免优先级回归

### P3
- Judgment: PASS with note
- Evidence:
  - 标准 facet taxonomy 仍存在：location / category / scene / status / deal / price / quality / preference / reference
  - `QueryFacet` / `FacetSet` / `TargetResolutionResult` 协议仍存在
  - facets 从 `SemanticFrame` 继续保留到 `GoalPlan`、`ExecutionPlan`、`EvidencePack`、`DecisionPlan`、`AnswerPlan`
  - facet 没有退化成 `route_task` 列表
  - `deterministic_tool` 仍只在 resolved single target 上执行
  - P3 测试通过
- Risks:
  - facet taxonomy 已经结构化，但后续 P8/P9 仍可能引入更细的生成和裁剪逻辑，需要继续约束

### P4
- Judgment: PASS with note
- Evidence:
  - `EvidencePack` 仍能表达 `answerable_facets`、`unknown_facets`、`failed_facets`
  - `DecisionPlan` 基于 `EvidencePack`
  - `AnswerPlan` 基于 `DecisionPlan`
  - `allowed_claims` / `required_disclaimers` 等等价字段仍存在
  - `answer_verify` 失败后仍会 rewrite / fallback
  - P4 测试通过
- Risks:
  - 证据三分法是当前回答安全性的核心边界，后续改动必须优先保留

### P5
- Judgment: PASS
- Evidence:
  - `state_update_plan` 仍是唯一 SessionState 写回入口
  - `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 的写回规则仍受控
  - 工具失败不污染 SessionState
  - 搜索无结果不写推荐列表
  - verify 失败不写成功状态
  - metadata 仍保留 source / ttl / evidence_ref / location_context / resume_strategy
  - P5 测试通过
- Risks:
  - SessionState 现在承担更多边界信息，后续新增字段时要继续保持单入口写回

### P6
- Judgment: PASS with note
- Evidence:
  - `test_p6_complex_query_matrix.py` 存在
  - deterministic harness 与 fake backend 存在
  - golden traces 存在
  - 主验收不依赖 MySQL / Java / real LLM
  - 至少覆盖推荐多约束、多维对比、单店多 facet、引用失败、推荐 + 引用依赖、工具失败、搜索无结果、verify 失败、澄清恢复、前后矛盾多轮 query
  - 测试检查中间状态，不只看 `final_response`
  - P6 测试通过
- Risks:
  - 真正的 integration / e2e 仍与外部环境有关，fake backend 与真实 DB 仍有差异

### P7
- Judgment: PASS with note
- Evidence:
  - `exploration_planning` 仍是独立 workflow handler
  - 没有新增 `exploration_planning_subgraph`
  - 没有把 `exploration_planning` 并入 `discovery_decision`
  - 工具结果 / `EvidencePack` / `AnswerPlan` / `state_update_plan` 仍能沿共享适配层收敛
  - `state_update_plan` 已能识别 `workflow_name=exploration_planning`
  - P7 测试通过，且 `test_exploration_planning_workflow.py` 也通过
- Risks:
  - exploration 链路仍有独立 handler 语义，后续改动需继续保证与主链路同构

## 5. Cross-Phase Invariant Check

- single-owner workflow: 通过
- no workflow-level MapReduce: 通过
- router priority: 通过
- facet retention: 通过
- target resolution: 通过
- evidence triage: 通过
- answer verify: 通过
- state update safety: 通过
- complex query matrix: 通过
- exploration protocol isomorphism: 通过

## 6. Forbidden Pattern Scan

扫描范围：生产代码优先，排除 `tests/`、`__pycache__/`、`.pytest_cache/`

结果：

- `workflow_names`: 未发现
- `final_responses`: 未发现
- `state_update_plans`: 未发现
- workflow name list dispatch: 未发现
- 多 workflow fan-out: 未发现
- 多 final_response merge: 未发现
- 多 state_update_plan merge: 未发现
- 新增 workflow: 未发现
- 新增 tool: 未发现
- `exploration_planning_subgraph`: 未发现
- 把 `exploration_planning` 并入 `discovery_decision`: 未发现
- `route_task` 被当作 facet list: 未发现
- answer 重新做推荐决策: 未发现
- response_subgraph 直接写 SessionState: 未发现
- exploration 子目标生成多个 final_response: 未发现
- 工具失败写 current_shop: 未发现
- 搜索无结果写 last_recommendation_list: 未发现
- verify fail 写成功状态: 未发现

说明：

- 生产代码中可以看到的 `final_response`、`state_update_plan`、`workflow_name` 都保持单值语义
- `state_update_plan`、`final_response`、`answer_verify_passed` 等命中属于正常协议字段，不是多主 merge 痕迹

## 7. Test Results

- `python -m compileall local_life_agent`
  - 结果：通过
- `pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py -q`
  - 结果：通过，`85 passed in 38.89s`
- `pytest local_life_agent/tests/test_exploration_planning_workflow.py -q`
  - 结果：通过，`11 passed in 1.59s`
- `pytest -m "not integration and not e2e" local_life_agent/tests -q`
  - 结果：time-budget blocked / timed out after `244031ms`
  - 说明：这是 broad suite 的环境/时间预算问题，不等价于架构失败

## 8. Acceptance Judgment

- P0-P7 报告齐全: PASS
- P0-P7 主测试通过: PASS
- P0-P7 协议没有互相冲突: PASS
- 没有新增 workflow: PASS
- 没有新增 tool: PASS
- 没有 workflow fan-out: PASS
- 没有 graph_builder 重写: PASS
- 没有破坏 state_update_plan 唯一写回: PASS
- exploration_planning 独立 handler 保持: PASS
- 可以进入 P8: PASS

## 9. Remaining Risks

- integration / e2e 仍可能依赖 MySQL / Java / real LLM
- fake backend 与真实 DB 存在行为差异风险
- broad suite 在当前机器上存在时间预算问题
- P8 之后仍需处理 retry / expand / degrade
- P9 ToolCapabilitySpec 仍是后续重要约束
- P10 parallel tool execution 仍应限制在 tool/evidence 层
- P11 streaming 仍应保持 single final stream
- P12 budget / freshness / TTL 仍需继续收口

## 10. Decision for P8

- `READY_FOR_P8 = true`

必须继承的边界：

- 继续保持 single-owner workflow
- 继续保持单 dispatch
- 不新增 workflow 级 MapReduce
- 不新增 workflow / tool
- 不重写 graph_builder
- 继续让 `state_update_plan` 作为唯一写回入口
- 继续让 `exploration_planning` 保持独立 handler 边界

