# P11 Follow-up Router / P6 Regression Fix Report

## 1. Conclusion

PASS

本轮已修复这次 follow-up 里暴露的 router / P6 宽回归问题，且未引入新的失败。当前结论是可以继续进入下一阶段的后续工作，但本轮不展开 P12。

## 2. Inputs

- `todo/p11_observability_metrics_streaming_report.md`
- `todo/p10_final_p5_comparison_metadata_contract_fix_report.md`
- `todo/p10_experience_and_performance_report.md`
- `todo/p9_evidence_planner_capability_budget_report.md`
- `todo/p8_evidence_insufficiency_iteration_and_degrade_report.md`
- `todo/p6_complex_query_matrix_report.md`
- `todo/p5_session_state_writeback_safety_and_reference_retention_report.md`
- `todo/p4_evidence_decision_answer_protocol_report.md`
- `todo/p3_facet_protocol_and_retention_report.md`
- `todo/p2_router_priority_and_keyword_conflict_report.md`
- `todo/p1_single_owner_workflow_invariants_report.md`
- `todo/adr_p0_single_owner_workflow_no_map_reduce.md`
- `todo/complex_intent_query_architecture_stabilization_plan.md`

## 3. Scope

本轮检查 / 修改的代码文件：

- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/engine/subgraphs/planning_subgraph.py`
- `local_life_agent/tests/helpers/fake_backends.py`
- `local_life_agent/tests/test_orchestration_router.py`
- `local_life_agent/tests/test_p6_complex_query_matrix.py`

## 4. Root Cause

### 4.1 Router 误把泛化门店指代当成了已锁定锚点

`normalize_route_task()` 相关路径里，`_looks_like_specific_shop_mention()` 对 “这家店 / 那家店” 这类指代词过于宽松，把它们误判成了具体店铺锚点，导致单店问法被错误路由到 `shop_status` / `deterministic_tool`，没有进入澄清分支。

### 4.2 单店问法在 planning_subgraph 中仍可能被推进到 execute

`h_planning_subgraph()` 在 target resolve 未真正解析出单一门店时，仍可能沿着 execute 路径继续跑。对 “这家有券吗” 这种必须先明确当前店铺的问题，这会把本应澄清的 turn 推成回答 turn。

### 4.3 测试桩对 malformed / clarification 场景的语义不够准确

`FakeComplexQueryLLMBackend` 里：

- “这家有券吗” 原先会落到通用 recommendation fallback，而不是一个需要 `current_shop` 的 single-shop 语义。
- “LLM返回格式异常” 原先也会被伪装成普通 recommendation payload，导致与“应走 clarify fallback”的 smoke 期望不一致。

## 5. Fix Summary

### 5.1 Router 锁定逻辑收紧

在 `local_life_agent/planning/orchestration_router.py` 中：

- 将 `_looks_like_specific_shop_mention()` 对 `这家 / 那家 / 这间 / 那间 / 它 / 第一家 / 第二家 / 第三家` 这类指代前缀明确排除。
- 单店问法如果没有真实门店锚点，归一化结果会回到 `missing_required_slot` / clarification fallback。

### 5.2 planning_subgraph 对未解析单店问法提前收口

在 `local_life_agent/engine/subgraphs/planning_subgraph.py` 中：

- 对 `single_shop_query` 增加了更窄的澄清保护。
- 当 `current_shop` 不存在且 resolve 结果没有真正解析出单店时，直接路由到 clarification，而不是继续进入 execute。

### 5.3 测试桩对场景做了最小语义对齐

在 `local_life_agent/tests/helpers/fake_backends.py` 中：

- 新增了 `这家有券吗` / `这家店有券吗` 的单店澄清场景。
- 将 `LLM返回格式异常` 的 payload 改成真正的 unknown / need_context 语义，而不是 recommendation 伪装。

### 5.4 回归断言按真实行为回收

在测试里把部分断言改成和当前协议一致：

- `clarification_resume` 第一轮应先 clarify。
- `malformed_llm_output_smoke` 应走 clarify / no-tool 路径。

## 6. New Priority

`comparison_targets_meta.source` 这次没有改动。  
本轮新增的 router 优先级重点是：

1. 真实门店锚点优先
2. 明确的 current_shop / resolved_target 优先
3. 泛化指代词不再冒充已解析锚点
4. 单店未解析时优先 clarification，而不是 execute

## 7. Test Commands and Results

已执行：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_orchestration_router.py \
       local_life_agent/tests/test_p6_complex_query_matrix.py \
       local_life_agent/tests/test_p5_session_state_writeback.py -q
```

结果：

- `python -m compileall local_life_agent` 通过
- 上述 pytest 组合：`31 passed`

另外单点验证也已通过：

- `test_orchestration_router_falls_back_when_single_shop_anchor_missing`
- `test_p6_complex_query_matrix[clarification_resume]`
- `test_p6_smoke_cases[malformed_llm_output_smoke]`

## 8. Can Enter P11 / P12

本 follow-up 修复已完成，当前可视为通过这轮 gate。  
但本轮按照要求不进入 P12，只完成修复、验证和报告。

## 9. Remaining Legacy Compatibility

- 仍保留对历史单店 / 推荐 / 澄清路径的兼容。
- 这次只收紧了“泛化店铺指代”与“异常 LLM 输出”的回退行为，没有扩大 fuzzy 规则。
- 仍未修改推荐 ranking_snapshot 来源，也未重写主执行链。

