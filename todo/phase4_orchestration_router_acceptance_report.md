# Phase 4 OrchestrationRouter Acceptance Report

## 1. 总体结论

**FAIL**

结论要点：

- 已有 `OrchestrationDecision` schema 和 `planning/orchestration_router.py` 的影子路由逻辑。
- 已有 shadow mode 记录，且 `orchestration_decision` 只写入 `GraphState`，没有进入 `SessionState`。
- 但当前实现没有把 `orchestration_router` 作为独立图节点接入 `understanding_subgraph` 和 `planning_subgraph` 之间。
- 当前 policy 覆盖与验收要求不完全一致，尤其是单店确定性任务的任务类型口径仍以 `TaskType.single_shop_query` / `coupon_query` 为主，没有按验收清单逐项落到 `shop_status` / `shop_distance` / `shop_price` / `shop_coupon` / `shop_review_summary` / `shop_scene_fit`。
- 主链路回归里仍有失败用例，不能把 Phase 4 直接判为 PASS。

结论判断：

- 是否只完成 OrchestrationRouter：**部分完成**
- 是否 shadow mode：**是**
- 是否未引入 workflow_runner：**是**
- 是否未引入 workflow registry：**是**
- 是否未真实拆多 workflow：**是**
- 是否未改变主链路：**大体未改变，但未达到独立节点接入要求**
- 是否可以进入 Phase 5 设计：**可以，但要先收口本轮 Phase 4 缺口**
- 是否可以进入 Phase 5 实现：**不可以**

## 2. Phase 4 实现报告复核

复核对象是 `todo/phase4_orchestration_router_report.md`。

复核结论：

- 报告声称已完成 shadow mode 二级路由接入，这一点部分成立。
- 报告声称 `orchestration_decision` 仅存在于 `GraphState` 且不写入 `SessionState`，这一点与源码一致。
- 报告声称保持主链路 conditional edge 不变，这一点与 `graph_builder.py` 一致。
- 但报告把实现描述得过于完整，容易让人误以为 `orchestration_router` 已经是独立图节点并按验收位置接入；源码里实际是嵌在 `planning_subgraph` 内部做影子写入。
- 报告提到的测试通过情况与当前仓库现状不完全一致，当前关键回归里仍有失败。

## 3. Schema 验收

结论：**基本通过，但不是完整验收通过**

源码证据：

- `local_life_agent/domain/schemas.py` 中存在 `OrchestrationDecision`。
- 字段包括 `orchestration_pattern`、`workflow_name`、`workflow_reason`、`task_complexity`、`requires_tool`、`requires_clarification`、`response_mode`、`confidence`、`missing_fields`、`next_action`。
- `confidence` 有范围约束，`missing_fields` 是 list，枚举值做了基础校验。
- `local_life_agent/domain/graph_state.py` 中 `orchestration_decision` 只放在 `GraphState`，没有出现在 `SessionState`。

不足：

- `OrchestrationDecision` 的验证是字符串集合 + field validator 方式，不是独立 policy table + validator 模块的完整形态。
- `TaskType` 仍然是现有主链路口径，未按本次验收清单把单店确定性任务枚举逐项落成独立 routing schema。
- 当前 schema 虽可序列化，但与验收要求的“policy table 覆盖完整”还差一步。

## 4. Router / Policy / Validator 验收

结论：**部分通过**

已满足：

- `route_orchestration` 的等价入口存在，实际实现是 `build_orchestration_decision(state)`。
- router 不调用工具。
- router 不访问 DB。
- router 不写 session。
- router 不生成最终自然语言回答。
- router 不选 winner。
- router 不构建 `EvidencePack`、`DecisionPlan` 或 `AnswerPlan`。

主要问题：

- 当前 router 逻辑更像一组硬编码分支 + 小型 helper，不是验收要求里希望看到的完整 policy table / validator 组合。
- `deterministic_tool` 的分流仍然依赖 `single_shop_query` / `coupon_query` 等现有任务口径，而不是验收清单中的 `shop_status`、`shop_distance` 等独立任务语义。
- 对 `reference_failed`、`low_confidence`、`missing_required_slot` 等场景的覆盖不够完整，缺少一套显式、可测试的统一 validator 层。
- router 失败时的显式兜底与错误元数据写入没有单独的异常保护层，存在风险。

## 5. Graph Shadow Mode 验收

结论：**未完全通过**

源码事实：

- `local_life_agent/engine/graph_builder.py` 仍然只有 `understanding_subgraph -> planning_subgraph` 的主链路。
- 没有独立的 `orchestration_router` 图节点被 `add_node` / `add_conditional_edges` 接入。
- 现在的影子路由是通过 `local_life_agent/engine/subgraphs/planning_subgraph.py` 内部调用 `build_orchestration_shadow_patch()` 实现的。

判断：

- shadow mode 记录是存在的。
- 但验收要求的“在 understanding_subgraph 之后、planning_subgraph 之前”作为独立 shadow node 接入，没有达成。
- 所以这一项不能算 PASS。

## 6. 越权检查

结论：**router 自身没有越权，整体链路仍有主流程上的历史风险**

router 文件检查结果：

- `local_life_agent/planning/orchestration_router.py` 没有 `dispatch_tool_call`、`db_session`、`save_session`、`update_session`、`final_response`、`winner_shop_id`、`EvidencePack`、`DecisionPlan`、`AnswerPlan` 等越权调用。
- 该文件只做状态读取、pattern 选择、决策组装和 patch 构造。

shadow 接入检查结果：

- `planning_subgraph.py` 只是把影子决策写回 `GraphState` 并打日志。
- 没有根据 `workflow_name` 调度真实 workflow。
- 没有新增 workflow runner / registry。

## 7. 日志与 Trace 验收

结论：**基本通过**

证据：

- 实际日志里能看到 `ORCHESTRATION_SHADOW` 记录。
- 日志包含 `session_id`、`turn_id`、`node` / `node_name`、`orchestration_pattern`、`workflow_name`、`response_mode`、`next_action`、`confidence` 等字段。
- `trace.py` 与 `file_logger.py` 使用了统一的摘要和脱敏策略，敏感字段会被截断或屏蔽。

观察到的风险：

- 目前看到的日志字段覆盖主要来自 shadow 记录和统一 node wrapper，不代表这个 shadow node 已经是图上的独立节点。
- 本次抽查日志没有看到手机号、token、支付信息或完整隐私明文。

## 8. 静态搜索结果

### 8.1 Phase 5 越界

搜索结果显示：

- `workflow_runner`、`WORKFLOW_REGISTRY`、`DiscoveryDecisionWorkflow`、`DeterministicToolWorkflow`、`DirectResponseWorkflow`、`ClarificationFallbackWorkflow`、`ExplorationPlanningWorkflow` 这些词主要出现在文档和测试里。
- 运行时代码里没有找到真正的 workflow runner 或 registry 实现。

结论：

- 没有 Phase 5 运行时代码越界。
- 只有文档和测试层面的目标描述。

### 8.2 Router 越权

搜索结果显示：

- `local_life_agent/planning/orchestration_router.py` 只包含状态读取和路由决策组装。
- 没有工具调用、DB 查询、最终回答生成、winner 选择、会话写入。

结论：

- router 自身没有越权。

### 8.3 工具 / DB / Answer 越权

搜索结果显示：

- `dispatch_tool_call`、`DecisionPlan`、`EvidencePack`、`AnswerPlan`、`final_response` 等词在全仓库很多地方都有出现，这是正常的主链路能力。
- 但在 `planning/orchestration_router.py` 中没有这些调用。

结论：

- shadow router 没有触碰这些能力。

### 8.4 State persistence

搜索结果显示：

- `orchestration_decision` 只出现在 `GraphState`、schema、shadow router、测试和日志相关代码里。
- `SessionState` 不包含 `orchestration_decision`。
- `state_update_plan` 也没有把它作为持久化字段写回。

结论：

- 没有进入 SessionState 持久化。

## 9. 测试结果

已执行命令与结果：

- `pytest local_life_agent/tests/test_orchestration_router.py -q`
  - 结果：`5 passed`
- `pytest local_life_agent/tests/test_phase_e_state_contracts.py local_life_agent/tests/test_trace_observability.py local_life_agent/tests/test_strict_guards.py local_life_agent/tests/test_core_wrappers.py -q`
  - 结果：`30 passed`
- `pytest local_life_agent/tests/test_target_resolve_candidate_set.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_single_shop_multifacet.py local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_p2_end_to_end.py local_life_agent/tests/test_comprehensive_graph_e2e.py -q`
  - 结果：`3 failed, 96 passed, 1 xfailed, 1 xpassed`
- `python -m compileall local_life_agent`
  - 结果：通过

失败项简述：

- `test_comparison_flow.py::test_compare_first_item_and_explicit_shop`
- `test_recommendation_flow.py::test_recommendation_failure_does_not_pollute_session`
- `test_single_coupon_flow.py::test_fuzzy_shop_does_not_call_coupon_tool`

说明：

- 这些失败阻止了本轮 Phase 4 进入 PASS。
- 其中一部分看起来更像主链路回归问题，但验收结论仍然不能忽略它们。

## 10. 行为级反例检查

### 10.1 Router 不调工具

结果：

- 通过源码检查，router 本身没有工具调用。
- 未发现 `call_tool` / `execute_tool` / `ToolExecutor` / `dispatch_tool_call` 之类的调用。

### 10.2 Router 不生成回答

结果：

- router 本身没有 `final_response` 生成逻辑。
- 该职责仍在 response 子图。

### 10.3 Router 不选 winner

结果：

- router 本身没有 winner 决策逻辑。
- `winner_shop_id` 仍属于 `DecisionPlan` / answer 链路。

### 10.4 Shadow mode 不改变主链路

结果：

- 主链路仍会继续进入 `planning_subgraph`。
- 但 shadow node 不是独立图节点，因此不满足验收里对接入位置的严格要求。

### 10.5 Router 失败不阻断主链路

结果：

- 当前没有看到独立的异常兜底层来专门把 router 异常转成 fallback decision。
- 这是一个残余风险，不建议当作已完全通过。

### 10.6 不持久化 orchestration_decision

结果：

- `SessionState` 中没有 `orchestration_decision`。
- `state_update_plan` 没有写 orchestration 字段。
- 这一项通过。

## 11. 文档回写验收

检查对象：

- `todo/phase4_orchestration_router_report.md`
- `todo/0000_execution_order_and_progress.md`
- `todo/03_workflow_design.md`
- `todo/05_state_and_schema_design.md`
- `todo/07_testing_and_acceptance.md`
- `todo/09_implementation_todo.md`
- `todo/10_orchestration_router_design.md`

结论：

- 文档整体已经开始反映 Phase 4 shadow mode 这个事实。
- 但 `todo/phase4_orchestration_router_report.md` 的语气偏乐观，容易让人误以为接入位置、测试结果和覆盖程度都已经完全满足验收。
- 现有文档没有声称已实现 workflow_runner 或 workflow registry，这一点是对的。
- 但文档没有把当前的缺口讲得足够清楚，特别是 graph 接入位置和测试失败。

## 12. 剩余风险

### P0

- `orchestration_router` 没有作为独立图节点接入 `understanding_subgraph` 和 `planning_subgraph` 之间，这是最主要的验收缺口。

### P1

- policy 覆盖不完全，单店确定性任务的验收口径没有完整落到清单中的 task 类型。
- 缺少一个更明确的 validator / fallback 异常保护层，router 失败的兜底不够硬。

### P2

- 主链路回归仍有 3 条失败，需要继续区分是 Phase 4 回归还是既有问题。
- 文档对当前实现状态描述偏乐观，容易误导后续阶段判断。

### P3

- 日志与 trace 虽然已经能观测 shadow 结果，但独立性还可以更强，便于后续 Phase 5 迁移。

## 13. 下一步建议

**Phase 4 FAIL，不进入 Phase 5，继续修 Phase 4。**
