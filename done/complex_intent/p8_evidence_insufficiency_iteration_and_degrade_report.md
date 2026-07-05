# P8 Evidence Insufficiency Iteration and Degrade Report

## 1. Conclusion

PASS

本轮已完成 P8 证据不足迭代与降级策略的最小协议接入，`EvidenceReview` 现在会输出结构化 `action` / `tool_failures` / budget / `next_step` 信息，并且决策与路由层可以识别这些动作。

可以进入 P9。

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
- [`todo/p0_p7_unified_acceptance_report.md`](D:/javacode/hm-dianping/todo/p0_p7_unified_acceptance_report.md)
- [`todo/complex_intent_query_architecture_stabilization_plan.md`](D:/javacode/hm-dianping/todo/complex_intent_query_architecture_stabilization_plan.md)

## 3. Scope

本轮修改的代码文件：

- [`local_life_agent/domain/evidence.py`](D:/javacode/hm-dianping/local_life_agent/domain/evidence.py)
- [`local_life_agent/planning/evidence/evidence_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_review.py)
- [`local_life_agent/planning/decision/decision_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_review.py)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
- [`local_life_agent/engine/_routes.py`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py)

本轮新增测试文件：

- [`local_life_agent/tests/test_p8_evidence_review_iteration.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p8_evidence_review_iteration.py)

## 4. EvidenceReview Protocol

本轮在现有 `EvidenceReviewResult` 上补齐了 P8 结构化字段，并保留旧的 `next_action` 兼容层。

新增 / 补齐内容：

- `EvidenceReviewAction`
- `ToolFailureType`
- `ToolFailure`
- `EvidenceReviewResult.action`
- `retryable_facets`
- `missing_facets`
- `unknown_facets`
- `failed_facets`
- `answerable_facets`
- `tool_failures`
- `retry_budget_remaining`
- `expand_search_budget_remaining`
- `replan_budget_remaining`
- `degrade_reason`
- `fallback_reason`
- `clarification_reason`
- `next_step`

说明：

- `action` 是 P8 的结构化下一步
- `next_action` 保留给现有图路由和旧测试
- `ToolFailure` 只做最小分类，不进入 P9 的完整能力建模

## 5. Action Decision Rules

- `proceed`
  - 必要 facets 已可回答，且没有需要继续处理的失败 / 缺失 / 澄清条件
  - 仍保留旧的 `next_action=FINISH`

- `retry`
  - 存在可重试的工具失败
  - `retry_budget_remaining > 0`
  - 该动作会映射到现有路由的重规划路径

- `replan_missing_facets`
  - 当前结果缺少 required facets
  - `replan_budget_remaining > 0`
  - 不把缺失 facet 编造成已回答

- `expand_search`
  - 结果为空或搜索不足
  - `expand_search_budget_remaining > 0`
  - 不生成假候选，不写伪推荐列表

- `clarify`
  - 缺必要上下文或缺目标
  - 不 retry 工具
  - 写澄清语义而不是硬猜

- `degrade`
  - 存在部分可回答 facets
  - 其余 facets 进入 disclaimer
  - 不编造不可证事实

- `fallback`
  - 无法安全输出
  - 所有预算耗尽或无 answerable facets
  - verify fail / 重写失败时也走该路径

## 6. Budget Guard

本轮实现了最小预算字段：

- `retry_budget_remaining`
- `expand_search_budget_remaining`
- `replan_budget_remaining`

规则：

- 预算默认按小值处理，避免无界循环
- 预算耗尽后只允许 degrade / fallback
- P8 只做结构化 next step，不在 review 层自行展开无限迭代

## 7. Decision / Answer Integration

已接入的配合点：

- `DecisionReview` 可以读取 `EvidenceReviewResult.action`
- `review_decision` 会把 `clarify / fallback / degrade / retry / replan_missing_facets / expand_search` 显式映射成对应的 next_action
- `AnswerPlan` builder 支持可选 `review_action`
- `degrade` 与 `fallback` 会保留免责声明语义，不会把 unknown / failed facets 写成确定性 claim

说明：

- 现有 `next_action` 仍保持兼容
- P8 的结构化动作已进入决策链，但没有引入新 workflow

## 8. StateUpdate Safety

本轮保持了 P5 的写回安全边界：

- retry / expand / replan 不写成功状态
- clarify 写 pending_clarification
- degrade 只表达安全可写入信息
- fallback 不写成功状态
- verify fail 不写成功状态

补充：

- `engine/_routes.py` 现在可识别 `EvidenceReviewResult.action`
- 旧的 `next_action` 路由仍然可用

## 9. Exploration Planning Coverage

本轮新增了 P8 探索覆盖测试，验证：

- `proceed`
- `retry`
- `replan_missing_facets`
- `expand_search`
- `clarify`
- `degrade`
- `fallback`
- exploration 部分成功时仍保留免责声明，不伪装为完整成功

探索工作流仍然保持独立 handler，没有新增 `exploration_planning_subgraph`，也没有并入 `discovery_decision`。

## 10. Golden Trace Updates

本轮没有新增 golden trace 文件。

原因：

- P8 先完成结构化 review / action 接入
- 现阶段优先保障协议与回归测试稳定
- golden trace 可在后续阶段补齐，不影响本轮 P8 结论

## 11. Code Changes

- [`local_life_agent/domain/evidence.py`](D:/javacode/hm-dianping/local_life_agent/domain/evidence.py)
  - 新增 `EvidenceReviewAction`
  - 新增 `ToolFailureType`
  - 新增 `ToolFailure`
  - 给 `EvidenceReviewResult` 补齐 action / facets / failure / budget / next_step 字段

- [`local_life_agent/planning/evidence/evidence_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_review.py)
  - 生成结构化 `EvidenceReviewResult.action`
  - 分类 retryable / non-retryable tool failures
  - 读取 retry / expand / replan 预算
  - 保持旧 `next_action` 兼容

- [`local_life_agent/planning/decision/decision_review.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_review.py)
  - 读取 `EvidenceReviewResult.action`
  - 将 P8 action 映射到现有 `DecisionReviewResult.next_action`

- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
  - 增加可选 `review_action`
  - 让 clarification / degrade / fallback 的 answer plan 更容易表达

- [`local_life_agent/engine/_routes.py`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py)
  - evidence review 路由开始识别 `action`
  - 仍保留旧 `next_action` 兜底

## 12. Test Changes

新增测试：

- [`local_life_agent/tests/test_p8_evidence_review_iteration.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p8_evidence_review_iteration.py)

覆盖点：

- `proceed`
- `retry`
- `replan_missing_facets`
- `expand_search`
- `clarify`
- `degrade`
- `fallback`
- exploration 部分成功降级语义

## 13. Test Results

已通过：

- `python -m compileall local_life_agent`
  - `PASS`

- `pytest local_life_agent/tests/test_p8_evidence_review_iteration.py -q`
  - `PASS`
  - `9 passed`

- `pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py local_life_agent/tests/test_p8_evidence_review_iteration.py -q`
  - `PASS`
  - `94 passed`

- `pytest local_life_agent/tests/test_exploration_planning_workflow.py -q`
  - `PASS`
  - `11 passed`

- `pytest local_life_agent/tests/test_evidence_review.py -q`
  - `PASS`
  - `19 passed`

- `pytest local_life_agent/tests/test_decision_planner.py -q`
  - `PASS`
  - `25 passed`

- `pytest local_life_agent/tests/test_05_graph.py -k evidence_review -q`
  - `PASS`
  - `8 passed`

- `pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`
  - `PASS`

- `pytest local_life_agent/tests/test_p5_session_state_writeback.py -q`
  - `PASS`

未执行的 broad non-integration suite：

- 本轮没有重新跑 `pytest -m "not integration and not e2e" local_life_agent/tests -q`

## 14. Acceptance Judgment

- `EvidenceReviewResult` 存在: PASS
- `proceed / retry / replan_missing_facets / expand_search / clarify / degrade / fallback` 覆盖: PASS
- `retry / expand / replan` 有预算保护: PASS
- 部分成功可以 degrade: PASS
- unknown / failed facets 不编造: PASS
- 搜索无结果不生成 fake candidates: PASS
- 缺上下文 clarify，不 retry: PASS
- verify fail rewrite / fallback: PASS
- `state_update_plan` 安全: PASS
- exploration 覆盖: PASS
- P1-P7 回归未破坏: PASS
- 可以进入 P9: PASS

## 15. Remaining Risks

- P8 只做最小 ToolFailure / ReviewAction 分类，没有进入 P9 的完整 `ToolCapabilitySpec`
- P8 没有实现更重的多轮自动迭代闭环，当前仍是结构化 next_step + 路由接入
- P10 的并行工具执行仍应限制在 tool/evidence 层
- P11 还需要继续保持单 final stream
- P12 的 deadline / freshness / TTL 仍未展开

## 16. Deferred to Later Phases

- P9 ToolCapabilitySpec / EvidencePlanner facet 预算
- P10 并行工具执行
- P11 observability / streaming
- P12 deadline / freshness / TTL
- P13 BaseModel 全量迁移评估
- P14 长期冻结项
