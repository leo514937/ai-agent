# P6 / P7 状态流转修复验收报告

## 结论

- P6 真实问题已修复：`recommendation_plus_reference_dependency` 现在可以在推荐列表引用解析完成后，稳定写回 `current_shop`。
- P7 真实问题已修复：探索规划在 fallback / verify failure 场景下，会保留 `pending_clarification` 与结构化澄清上下文，而不是丢失恢复入口。
- 已完成针对性回归测试，P0 / P2 / P5 / P6 / P7 相关套件全部通过。

## 事实核查

### P6: recommendation_plus_reference_dependency

根因不是推荐列表本身，而是状态写回层没有把 `target_resolution` 这层更完整的解析结果传进 planner，导致推荐态里的序数引用分支无法命中 `current_shop` 写回。

修复点：
- 在 `local_life_agent/engine/subgraphs/state_update_plan.py` 中补充把 `target_resolution` 传给 `plan_state_update()`
- 在 `local_life_agent/planning/plans/state_update_planner.py` 中增加推荐态引用促写回的窄规则
- 该规则仅针对 `last_recommendation_list` 上的序数引用 / 引用依赖，不会把普通推荐列表误写成当前店

### P7: exploration fallback / verify failure

根因是探索回退逻辑只在 `response_mode == "clarify"` 时才生成 `pending_clarification`，fallback 模式会丢掉可恢复上下文。

修复点：
- 在 `local_life_agent/engine/workflows/exploration_planning_workflow.py` 中统一构造 `workflow_clarification_request`
- fallback 也会写入 `pending_clarification`
- 补充 `workflow_result_status`、`workflow_fallback_reason` 等结构化字段，方便后续恢复与排障
- 同时补了静态回归：源码里不再出现 `run_clarification_fallback_workflow(` 这种直跳过分支

## 测试验证

已通过：

```bash
python -m pytest local_life_agent/tests/test_p5_session_state_writeback.py -q
python -m pytest local_life_agent/tests/test_p6_complex_query_matrix.py -q -k recommendation_plus_reference_dependency
python -m pytest local_life_agent/tests/test_p7_exploration_protocol.py -q
python -m pytest local_life_agent/tests/test_p0_fact_calibration.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p2_end_to_end.py local_life_agent/tests/test_prompt_contract.py -q
python -m pytest local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py -q
python -m compileall local_life_agent
```

结果摘要：
- `test_p5_session_state_writeback.py`: 11 passed
- `test_p6_complex_query_matrix.py -k recommendation_plus_reference_dependency`: 1 passed
- `test_p7_exploration_protocol.py`: 8 passed
- P0 / P2 / P5 / P6 / P7 组合回归：32 passed
- P0 / P2 / P5 / P6 / P7 补充组合回归：40 passed

## 备注

- 我还跑了 `python -m pytest local_life_agent/tests -q` 做全量观察；当前工作区里仍有若干与本次 P6 / P7 修复无关的既有失败，主要集中在上下文恢复、语义 schema 和部分端到端主路径用例。
- 这份修复没有去动那些非本次目标的问题，避免把验收补丁扩散到不相关链路。
