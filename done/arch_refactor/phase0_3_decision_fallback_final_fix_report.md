# Phase 0-3 Decision Fallback Final Fix Report

## 1. 总体结论

**PASS**

本轮只处理 Phase 0-3 的最后一个 P1 契约问题：`winner_shop_id` 不能再从 `ranking_snapshot` 兜底生成。

当前结论是：

- `decision_planner` 已经切断 `ranking_snapshot -> winner_shop_id` 的运行时 fallback
- winner 只能来自真实 evidence，或显式的 comparison evidence 结构
- 证据不足 / 平局时，返回结构化的不足信息，而不是伪造 winner
- 单店无显式 facet 时，`evidence_planner` 现在会默认补 `detail`

因此，Phase 0-3 的这条残余契约问题已经收口，可以进入下一阶段的独立评审，但本次任务没有扩展到 Phase 4 实现。

## 2. 本轮修复的核心问题

### 2.1 winner fallback 违规

原问题是：

- `local_life_agent/planning/decision/decision_planner.py` 在证据不足或平局时，仍可能从 `ranking_snapshot` 选出 winner

这会破坏契约边界：

- `ranking_snapshot` 只能用于展示 / trace
- `winner_shop_id` 只能来自 decision 层的真实证据

### 2.2 单店无 facet 空计划

原问题是：

- 单店查询没有显式 facet 时，`evidence_planner` 可能产出过空的执行计划

这会让单店基础查询失去稳定的 `detail` 回退能力。

## 3. 已完成修复

### 3.1 Decision 层切断 snapshot fallback

已修改 [local_life_agent/planning/decision/decision_planner.py](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)：

- `_extract_ranking()` 仅保留展示 / trace 信息，不再作为 winner 来源
- `_find_winner_from_evidence()` 只从 evidence item / comparison matrix 的显式 winner 中取值
- 证据不足或平局时，不再回退 `ranking_snapshot`
- `plan_decision()` 额外返回结构化状态字段：
  - `missing_fields`
  - `next_action`
  - `reason`
  - `decision_reason`
  - `insufficient_evidence`
- `winner_evidence_refs` 只收集真实 evidence ref，不再吸收 ranking snapshot

### 3.2 Evidence 层补 detail 默认项

已修改 [local_life_agent/planning/evidence/evidence_planner.py](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py)：

- 对 `single_shop_query` 且未给出明确 facet 的场景，默认补 `detail`
- 这样单店基础查询不会再退化成空计划

### 3.3 测试收口

已同步更新相关测试，覆盖以下契约：

- ranking snapshot 不能单独推出 winner
- 证据不足不能伪造 winner
- tie 场景不能靠 snapshot break tie
- 单店无 facet 时应补 `detail`

涉及测试文件：

- [local_life_agent/tests/test_decision_planner.py](D:/javacode/hm-dianping/local_life_agent/tests/test_decision_planner.py)
- [local_life_agent/tests/test_phase_d_decision_contracts.py](D:/javacode/hm-dianping/local_life_agent/tests/test_phase_d_decision_contracts.py)
- [local_life_agent/tests/test_single_shop_multifacet.py](D:/javacode/hm-dianping/local_life_agent/tests/test_single_shop_multifacet.py)
- [local_life_agent/tests/test_subgraph_core_integration.py](D:/javacode/hm-dianping/local_life_agent/tests/test_subgraph_core_integration.py)
- [local_life_agent/tests/test_p2_end_to_end.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p2_end_to_end.py)
- [local_life_agent/tests/test_e2e_llm_main_path.py](D:/javacode/hm-dianping/local_life_agent/tests/test_e2e_llm_main_path.py)

## 4. 重新验收结论

### CandidateSet

通过。

- 多候选 recommendation / comparison 仍可正常进入 candidate_set 处理
- 没有把多候选误打成 `NOT_FOUND`

### Target

通过。

- `resolved_target` 仍然只表示明确目标解析
- 多候选结果不会直接写成 `current_shop`

### Winner

通过。

- `winner_shop_id` 只来自真实证据
- 不再存在 `ranking_snapshot` 兜底赢家路径

### Answer / Verifier

通过。

- answer 层仍然基于 evidence / decision 结果输出
- verifier 仍然承担最终校验职责

### State Persistence

通过。

- 没有新增绕过主图的状态写回路径
- 现有 state update 门禁仍然有效

## 5. 验证结果

已完成的验证：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_decision_planner.py -q`
- `pytest local_life_agent/tests/test_phase_d_decision_contracts.py -q`
- `pytest local_life_agent/tests/test_evidence_planner.py -q`
- `pytest local_life_agent/tests/test_subgraph_core_integration.py -q`
- `pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `pytest local_life_agent/tests/test_p2_end_to_end.py -q`
- `pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q`
- `pytest local_life_agent/tests/test_phase0_baseline.py -q`
- `pytest local_life_agent/tests/test_phase1_acceptance.py -q`
- `pytest local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_b_runtime_contracts.py local_life_agent/tests/test_phase_c_evidence_contracts.py local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py -q`
- `pytest local_life_agent/tests/test_core_wrappers.py local_life_agent/tests/test_subgraph_core_integration.py local_life_agent/tests/test_strict_guards.py local_life_agent/tests/test_trace_observability.py -q`
- `pytest local_life_agent/tests/test_java_tool_executor.py local_life_agent/tests/test_tool_backend_observability.py local_life_agent/tests/test_real_llm_contract.py -q`
- `pytest local_life_agent/tests/test_answer_verifier.py -q`

## 6. 下一步建议

本次 Phase 0-3 的 P1 契约问题已经修完，下一步建议是：

1. 单独进入 Phase 4 的设计评审或实现评审
2. 如果要继续做代码变更，优先围绕 Phase 4 的职责边界，而不是再扩写 decision fallback
3. 维持当前的最小回归策略，避免重新引入 snapshot 兜底 winner

## 7. 备注

- 本次没有新增平行 workflow
- 本次没有引入 Phase 4 实现
- 本次改动范围控制在契约修复和最小回归
