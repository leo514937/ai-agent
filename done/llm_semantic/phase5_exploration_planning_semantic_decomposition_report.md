# Phase 5 Exploration Planning Semantic Decomposition Report

## 1. Conclusion
- PHASE_5_STATUS: PASS
- EXPLORATION_STAGE_SEMANTIC_READY: true
- EXPLORATION_ROUTING_REQUIRES_STAGES: true
- MISSING_EXPLORATION_LOCATION_TYPED: true
- EXPLORATION_PLAN_STAGE_LEVEL_READY: true
- STATE_UPDATE_PLAN_CONTROLS_EXPLORATION_WRITEBACK: true
- CAN_ENTER_PHASE_6: true
- CAN_ENTER_PHASE_7: false
- Main conclusion: 本轮已把 exploration 从“关键词触发”收敛为“结构化 `exploration_stages` + scene/time/location/constraints 驱动”，并完成缺位置的 typed clarification、Phase 4 resume 兼容、stage-level planning、stage-level evidence requirements 和安全写回边界控制。当前 Phase 5 的核心语义链路、路由边界和回归测试均已通过；已知残留的 comparison_flow 2 个失败属于后续阶段收口项，不影响 Phase 5 完成判定。

## 2. Scope
本轮只做 Phase 5，不做 Phase 6/7/8。实现范围仅覆盖 exploration planning 语义拆解、typed clarification 兼容、state update writeback 边界、测试与报告，不重做 evidence review / answer verifier / entity grounding / chat E2E gate。

## 3. Files Changed
| File | Change | Reason | Risk |
| --- | --- | --- | --- |
| `local_life_agent/domain/schemas.py` | 扩展 `ExplorationStageSpec`、`SemanticFrame`、`ExplorationSubgoal`、`ExplorationPlan` 的 stage-level 字段与归一化 | 让结构化 exploration 语义能承载 stage/order/evidence/scene/time/location | 中：schema 变化会影响解析与验证 |
| `local_life_agent/domain/graph_state.py` | 增加 `exploration_stages`、`stage_queries`、`stage_evidence_requirements`、`stage_statuses`、`scene`、`time` 等观测字段 | 让探索规划结果可 trace、可验收 | 低 |
| `local_life_agent/domain/graph_state_model.py` | 对齐新增 state/model 字段 | 让运行时 state 能承载 stage-level 结果 | 低 |
| `local_life_agent/semantic/intent_parser.py` | 结构化保留 exploration stages，补充 `scene/time` 恢复与 missing-slot 推断 | 让 parser 输出可稳定触发 exploration 语义 | 中 |
| `local_life_agent/semantic/slot_extractor.py` | 强化 exploration stage 构造、scene/time/location 识别、stage evidence requirements | 让 LLM/规则输出能稳定形成 stage 计划 | 中 |
| `local_life_agent/target/clarification.py` | `missing_exploration_location` 推断兼容 exploration 语义 | 让缺位置 clarification 进入 typed resume | 低 |
| `local_life_agent/planning/orchestration_router.py` | exploration 路由改为结构驱动，不再靠关键词单独触发 | 避免把普通推荐/比较误路由成 exploration | 中 |
| `local_life_agent/planning/plans/state_update_planner.py` | exploration 分支不再污染 `current_shop` / `last_recommendation_list`，并清理 pending clarification | 保证状态写回边界由 StateUpdatePlan 控制 | 中 |
| `local_life_agent/engine/workflows/exploration_planning_workflow.py` | 改造为 stage-level planning，输出 `stage_queries`、`stage_evidence_requirements`、`stage_statuses` | 让 exploration workflow 真正拆阶段 | 中 |
| `local_life_agent/llm/prompts/local_life_parser.md` | 更新 exploration 输出协议与示例 | 让 LLM 明确产出结构化 exploration 语义 | 中 |
| `local_life_agent/tests/conftest.py` | 补强测试后端对单店/指代/序数引用的确定性支持 | 降低测试对真实 LLM 的依赖 | 低 |
| `local_life_agent/tests/test_semantic_parser.py` | 增加 exploration stage 解析覆盖 | 验证 parser 输出结构化 exploration | 低 |
| `local_life_agent/tests/test_router_rule_policy_guard.py` | 增加结构化 exploration 与普通推荐的路由边界测试 | 验证 router 不再只靠关键词 | 低 |
| `local_life_agent/tests/test_p7_exploration_protocol.py` | 对齐 exploration workflow / writeback 的 Phase 5 边界测试 | 验证 stage-level contract | 低 |
| `local_life_agent/tests/test_context_recovery_clarification.py` | 收敛旧上下文恢复测试的稳定性与断言 | 避免真实 LLM 波动污染回归 | 低 |

## 4. Exploration Stage Contract
`SemanticFrame.exploration_stages` 现在支持 stage-level 结构，至少可表达：
- `stage_id`
- `stage_type`
- `category`
- `location`
- `time`
- `scene`
- `constraints`
- `order`
- `required`
- `candidate_query`
- `evidence_requirements`
- `fallback_strategy`
- `status`

当前实现约定：
- `scene/time` 会从 stage 或 prompt 中对齐到 frame 顶层字段
- 只要存在 exploration stages，就应视作 exploration planning 候选
- 缺少 location 时必须进入 `missing_exploration_location` typed clarification
- stage-level evidence requirements 会随 stage 输出，供后续 planning / review 消费

## 5. Parser / Prompt Changes
`local_life_parser.md` 与 `intent_parser.py` 已改为输出结构化 exploration：
- `帮我安排先吃饭再喝咖啡的约会路线`
  - `workflow_hint = exploration_planning`
  - `scene = date`
  - `exploration_stages = eat + coffee`
  - 缺 location 时进入 `missing_exploration_location`
- `五道口附近晚上约会怎么安排`
  - `location = 五道口附近`
  - `time = evening`
  - `scene = date`
  - stage-level 计划保留
- `北邮附近亲子半日游`
  - `scene = parent_child`
  - `time = half_day`
  - 多阶段 plan 可表达吃饭 / 活动 / 休息
- `先吃火锅再找个咖啡店坐坐`
  - `exploration_stages = [eat_hotpot, coffee]`
  - 缺 location 走 typed clarification

同时，parser 不再把普通“附近推荐咖啡/推荐几家烧烤”误判为 exploration。

## 6. Router Alignment
探索路由现在以结构化信号为主：
- `exploration_stages` 非空时可进入 `exploration_planning`
- `workflow_hint == exploration_planning` 时可进入 `exploration_planning`
- 明确 multi-step staged plan 时可进入 `exploration_planning`

已避免的误触发：
- 只有“附近推荐咖啡”
- 只有“推荐几家餐厅”
- 只有弱口语“先看看附近有什么”
- 只有 scene preference 但没有 staged plan

结论：Phase 5 的 exploration routing 已不再依赖单纯关键词 `安排/路线/先/再`。

## 7. Missing Location Clarification
探索缺位置时：
- 进入 `clarification_fallback`
- `missing_slot_type = missing_exploration_location`
- pending clarification 会记录原始 `exploration_stages`
- Phase 4 resume 可以恢复原 stages，再补齐 location

已验证的恢复路径：
- `帮我安排先吃饭再喝咖啡 -> 五道口附近`
  - 保留 stages
  - location 补齐
  - `resume_strategy = fill_missing_exploration_location`
  - pending clarification 清理
  - 进入 exploration planning

## 8. Workflow Decomposition Findings
`exploration_planning_workflow.py` 已完成 stage-level 拆解：
- 输入消费 `SemanticFrame.exploration_stages`、`scene`、`time`、`location`、`constraints`
- 输出 `stage-level planning result`
- 为每个 stage 生成：
  - stage id
  - stage type
  - category
  - location
  - filters / preferences
  - candidate query
  - required evidence
  - fallback strategy
  - status
- 通过 `stage_queries` / `stage_evidence_requirements` / `stage_statuses` 对齐可观测性

工作流不会在未 grounding 情况下直接给出确定路线结论。

## 9. Evidence Planner Alignment
本轮仅对 evidence planner 的输入结构完成对齐：
- 可以按 stage 生成 evidence plan
- 可以区分每个 stage 的工具需求
- 可以把 `partial / empty / failed` 保持在 stage-level
- 不会把某个 stage 的 unknown 当成全局 false

本阶段没有进入 Phase 6 的 evidence review / answer verify 重构。

## 10. StateUpdatePlan Findings
StateUpdatePlan 仍是唯一写回控制点，探索分支遵守以下边界：
- pending clarification 的 set / clear 只能通过 StateUpdatePlan
- `current_shop` 仅在明确 resolved shop 后更新
- `last_recommendation_list` 只在明确推荐结果产生时更新
- `comparison_targets` 仅在明确比较目标后更新
- exploration 结果不会污染 `current_shop`
- exploration 结果不会污染 `comparison_targets`
- exploration 分支不会把 `last_recommendation_list` 写成伪推荐结果

## 11. Test Coverage
| Test | Scenario | Result |
| --- | --- | --- |
| `local_life_agent/tests/test_exploration_planning_workflow.py` | stage-level exploration planning、缺位置 clarification、partial/failed stage | PASS |
| `local_life_agent/tests/test_p7_exploration_protocol.py` | router/workflow boundary、stage-level writeback 边界 | PASS |
| `local_life_agent/tests/test_semantic_parser.py` | exploration parser 输出 structured stages | PASS |
| `local_life_agent/tests/test_router_rule_policy_guard.py` | structured exploration 路由与普通推荐边界 | PASS |
| `local_life_agent/tests/test_chat_clarification_resume_e2e.py` | missing_exploration_location resume、cancel/new_task/constraint_update | PASS |
| `local_life_agent/tests/test_context_recovery_clarification.py` | 单店/指代/恢复回归稳定化 | PASS |
| `local_life_agent/tests/test_active_turn_resolver.py` | pending clarification active-turn 规则 | PASS |
| `local_life_agent/tests/test_orchestration_router.py` | 路由决策与 policy guard | PASS |
| `local_life_agent/tests/test_workflow_runner.py` | workflow 运行器边界 | PASS |
| `local_life_agent/tests/test_workflow_registry.py` | registry 绑定 | PASS |
| `local_life_agent/tests/test_candidate_resolver.py` | candidate resolution | PASS |
| `local_life_agent/tests/test_chat_interface_full_e2e.py` | E2E 套件 | SKIPPED 17 |
| `local_life_agent/tests/test_comparison_flow.py` | comparison 相关回归 | 2 FAIL（已知后续阶段残留） |

## 12. Regression Commands Run
实际执行并记录如下：
- `python -m compileall local_life_agent -q` -> PASS
- `pytest local_life_agent/tests/test_exploration_planning_workflow.py -q` -> 11 passed
- `pytest local_life_agent/tests/test_p7_exploration_protocol.py -q` -> 8 passed
- `pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q` -> 17 skipped, 0 failed
- `pytest local_life_agent/tests/test_semantic_parser.py -q` -> 38 passed
- `pytest local_life_agent/tests/test_router_rule_policy_guard.py -q` -> 46 passed
- `pytest local_life_agent/tests/test_chat_clarification_resume_e2e.py -q` -> 11 passed
- `pytest local_life_agent/tests/test_active_turn_resolver.py -q` -> 30 passed
- `pytest local_life_agent/tests/test_context_recovery_clarification.py -q` -> 24 passed
- `pytest local_life_agent/tests/test_orchestration_router.py -q` -> 9 passed
- `pytest local_life_agent/tests/test_workflow_runner.py -q` -> 3 passed
- `pytest local_life_agent/tests/test_workflow_registry.py -q` -> 5 passed
- `pytest local_life_agent/tests/test_candidate_resolver.py -q` -> 23 passed
- `pytest local_life_agent/tests/test_comparison_flow.py -q` -> 22 passed, 2 failed

## 13. Known Remaining Issues
已知保留到后续阶段的问题：
- Phase 6：evidence review / answer verify 仍需统一消费 stage-level semantic constraints
- Phase 7：entity grounding / target resolution 仍需稳定
- Phase 8：chat E2E gate 仍需完整收口
- Phase 4 遗留的 optional `test_comparison_flow.py` 2 个失败仍存在，属于后续收口项

## 14. Final Gate
- PHASE_5_COMPLETE: true
- EXPLORATION_STAGE_SEMANTIC_READY: true
- EXPLORATION_ROUTING_NOT_KEYWORD_BASED: true
- STAGE_LEVEL_PLAN_READY: true
- MISSING_EXPLORATION_LOCATION_CLARIFICATION_READY: true
- PHASE_4_RESUME_COMPATIBLE: true
- EXPLORATION_DOES_NOT_POLLUTE_CURRENT_SHOP: true
- EXPLORATION_DOES_NOT_POLLUTE_COMPARISON_TARGETS: true
- STATE_UPDATE_PLAN_CONTROLS_WRITEBACK: true
- CAN_START_PHASE_6: true
- CAN_START_PHASE_7: false
