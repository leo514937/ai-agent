# P4 Evidence / Decision / Answer Protocol Report

## 1. Conclusion

PASS with note

## 2. Inputs

- P0 report: [`todo/p0_fact_calibration_and_adr_freeze_report.md`](D:/javacode/hm-dianping/todo/p0_fact_calibration_and_adr_freeze_report.md)
- ADR: [`todo/adr_p0_single_owner_workflow_no_map_reduce.md`](D:/javacode/hm-dianping/todo/adr_p0_single_owner_workflow_no_map_reduce.md)
- P1 report: [`todo/p1_single_owner_workflow_invariants_report.md`](D:/javacode/hm-dianping/todo/p1_single_owner_workflow_invariants_report.md)
- P2 report: [`todo/p2_router_priority_and_keyword_conflict_report.md`](D:/javacode/hm-dianping/todo/p2_router_priority_and_keyword_conflict_report.md)
- P3 report: [`todo/p3_facet_protocol_and_retention_report.md`](D:/javacode/hm-dianping/todo/p3_facet_protocol_and_retention_report.md)
- Inherited invariants:
  - `workflow_name` 仍是单值
  - `workflow_runner` 仍是单 dispatch
  - registry 仍是单 lookup
  - 没有 workflow 级 Map-Reduce
  - facet 协议已经贯穿 `SemanticFrame` -> `GoalPlan` -> `ExecutionPlan`
  - P4 只收敛 evidence / decision / answer 协议，不进入 P5 写回安全

## 3. Scope

本轮修改 / 检查的文件：

- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [`local_life_agent/domain/decision.py`](D:/javacode/hm-dianping/local_life_agent/domain/decision.py)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
- [`local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py)

## 4. Evidence Protocol

`EvidencePack` 现在显式携带：

- `answerable_facets`
- `unknown_facets`
- `failed_facets`

语义：

- `answerable_facets` 表示当前轮已有证据可直接回答的 facets
- `unknown_facets` 表示暂无法确认的 facets
- `failed_facets` 表示工具失败或证据获取失败的 facets

同时保留：

- `facet_results`
- `ranking_snapshot`
- `comparison_matrix`
- `forbidden_claims`
- `target_resolution`

说明：

- P4 只要求三分法可表达
- 不要求 P5 的状态写回防污染
- 不要求 P6 的全矩阵覆盖

## 5. Decision Protocol

`DecisionPlan` 现在可以把 evidence triage 保留下来：

- `answerable_facets`
- `unknown_facets`
- `failed_facets`
- `required_disclaimers`

`decision_to_answer_plan()` 也会把这些字段透传到 answer plan 字典中。

说明：

- `DecisionPlan` 仍然是单一决策对象
- 没有引入多主 merge
- 没有改 `workflow_runner`
- 没有把 decision 变成 workflow 列表

## 6. Answer Protocol

`AnswerPlan` 现在显式携带：

- `answerable_facets`
- `unknown_facets`
- `failed_facets`
- `required_disclaimers`

同时保留：

- `facets`
- `target_resolution`
- `conflicting_facets`
- `ranking_policy`
- `allowed_claims`
- `required_claims`
- `must_mention_unknowns`
- `forbidden_claims`

`build_answer_plan()` 现在会根据 evidence 的 facet triage 生成最小免责声明，避免把 unknown / failed facet 当成已确认事实输出。

## 7. Code Changes

- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
  - `EvidencePack` 增加三分法字段
  - `AnswerPlan` 增加三分法字段与 `required_disclaimers`
  - `schemas.DecisionPlan` 增加三分法字段与 `required_disclaimers`
- [`local_life_agent/domain/decision.py`](D:/javacode/hm-dianping/local_life_agent/domain/decision.py)
  - `decision_to_answer_plan()` 现在透传三分法与免责声明
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
  - 从 `facet_results` 生成三分法，并写回 `EvidencePack`
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
  - 从 evidence 生成三分法与最小免责声明
- [`local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py)
  - 新增 P4 协议链测试

## 8. Test Changes

新增测试覆盖：

- `EvidencePack` 三分法字段
- `DecisionPlan` 三分法透传
- `AnswerPlan` 三分法与免责声明透传
- 部分证据成功、部分 unknown、部分 failed 的混合场景
- `AnswerPlan.model_validate(...)` 兼容性

## 9. Test Results

执行命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_p1_single_owner_invariants.py \
       local_life_agent/tests/test_p2_router_priority.py \
       local_life_agent/tests/test_orchestration_router.py \
       local_life_agent/tests/test_p3_facet_protocol.py \
       local_life_agent/tests/test_phase_c_evidence_contracts.py \
       local_life_agent/tests/test_phase_d_decision_contracts.py \
       local_life_agent/tests/test_answer_verifier.py \
       local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q
```

结果：

- `compileall` 成功
- `pytest` 通过：`69 passed in 35.28s`

## 10. Acceptance Judgment

- `EvidencePack` 能表达 `answerable_facets` / `unknown_facets` / `failed_facets`：PASS
- `DecisionPlan` 基于 `EvidencePack` 保留三分法：PASS
- `AnswerPlan` 基于决策 / 证据保留三分法和免责声明：PASS
- 证据不足不再被当作已确认事实：PASS
- P1 / P2 / P3 回归未破坏：PASS

## 11. Remaining Risks

- P4 只完成 evidence / decision / answer 协议收敛
- 状态写回防污染仍留到 P5
- 复杂 query 全矩阵仍留到 P6
- exploration_planning 共享 adapter 仍留到 P7
- 预算 / deadline / freshness 仍留到 P12

## 12. Deferred to Later Phases

- P5 SessionState 写回安全
- P6 复杂 query 测试矩阵
- P7 exploration_planning 协议同构
- P8 证据不足迭代
- P9 EvidencePlanner facet 预算
- P10-P14 体验、观测、预算与冻结项
