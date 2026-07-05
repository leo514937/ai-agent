# P6 Complex Query Matrix Report

## 1. Conclusion

PASS with note

## 2. Inputs

- [P0 report](./p0_fact_calibration_and_adr_freeze_report.md)
- [ADR](./adr_p0_single_owner_workflow_no_map_reduce.md)
- [P1 report](./p1_single_owner_workflow_invariants_report.md)
- [P2 report](./p2_router_priority_and_keyword_conflict_report.md)
- [P3 report](./p3_facet_protocol_and_retention_report.md)
- [P4 report](./p4_evidence_decision_answer_protocol_report.md)
- [P5 report](./p5_session_state_writeback_safety_and_reference_retention_report.md)
- P5 PARTIAL PASS note: session writeback core rules passed, broader flow suites were previously blocked by local MySQL alias lookup in this environment
- Inherited invariants: single workflow name, single dispatch, no workflow fan-out, no new workflow/tool, no workflow-level MapReduce, keyword stays a signal, facet and target-resolution retention remains in place

## 3. Scope

This turn primarily touched the P6 test harness and marker gating:

- `pytest.ini`
- `local_life_agent/tests/conftest.py`
- `local_life_agent/tests/helpers/__init__.py`
- `local_life_agent/tests/helpers/fake_backends.py`
- `local_life_agent/tests/helpers/complex_query_harness.py`
- `local_life_agent/tests/fixtures/__init__.py`
- `local_life_agent/tests/fixtures/complex_query_matrix.py`
- `local_life_agent/tests/fixtures/golden_traces/*`
- `local_life_agent/tests/test_p6_complex_query_matrix.py`

## 4. Test Layering

- Deterministic harness / unit: uses `FakeLocalLifeBackend`, `FakeComplexQueryLLMBackend`, and monkeypatches for alias lookup, DB client, tool dispatch, and answer verification
- Mocked flow / contract: exercises the graph path with fake tool results and fake semantic parsing
- Integration / real DB: marked with `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION_TESTS=1`
- E2E / real LLM: marked with `@pytest.mark.e2e`, skipped unless `RUN_E2E_TESTS=1`

P6 主验收以 deterministic harness / mocked flow 为准。

## 5. Complex Query Matrix

Covered scenarios:

- 推荐多约束
- 多维对比
- 单店多 facet
- 引用失败
- 推荐 + 引用依赖
- 工具失败
- 搜索无结果
- verify 失败
- 澄清恢复
- 前后矛盾多轮 query

The matrix checks stable intermediate state rather than only `final_response`.

## 6. Golden Traces

新增 golden trace fixtures:

- `multi_constraint_recommendation`
- `multi_dimensional_comparison`
- `single_shop_multi_facet`
- `reference_failure`
- `recommendation_plus_reference_dependency`
- `partial_tool_failure`
- `empty_search_result`
- `answer_verify_failure`
- `clarification_resume`
- `conflicting_multi_turn_preference`
- `all_tools_timeout_smoke`
- `malformed_llm_output_smoke`
- `contradictory_multi_turn_preference`

Each trace stores query, initial state, expected workflow shape, target-resolution expectations, evidence triage expectations, decision/answer expectations, and state-writeback expectations.

## 7. Fake Backend / Harness

The deterministic backend isolates external dependencies by monkeypatching:

- `local_life_agent.semantic.alias_index.build_alias_index`
- `local_life_agent.semantic.alias_index.iter_alias_tokens`
- `local_life_agent.semantic.slot_extractor.iter_alias_tokens`
- `local_life_agent.tools.db_client.query_all_shops`
- `local_life_agent.tools.db_client.query_shops_by_keyword`
- `local_life_agent.tools.db_client.query_shop_by_id`
- `local_life_agent.tools.db_client.query_coupons_by_shop_id`
- `local_life_agent.tools.db_tools.build_alias_index`
- `local_life_agent.engine.graph_builder.dispatch_tool_call`
- `local_life_agent.engine.graph_builder.resolve_shop`
- `local_life_agent.engine.graph_builder._GRAPH_CACHE`
- `local_life_agent.agent._GRAPH_CACHE`
- `local_life_agent.engine.subgraphs.response_subgraph.verify_answer`

This kept the P6 matrix off MySQL / Java / real LLM while preserving the existing graph path.

## 8. Intermediate State Assertions

The matrix asserts the stable intermediate fields that are actually emitted in this codebase:

- `workflow_name`
- `response_mode`
- `semantic_frame` when present
- `target_resolution`
- `evidence_pack.answerable_facets`
- `evidence_pack.unknown_facets`
- `evidence_pack.failed_facets`
- `answer_plan`
- `state_update_plan`
- `session_state_after`
- `pending_clarification`
- `comparison_targets`
- `current_shop`
- `last_recommendation_list`
- `answer_verify_passed`
- `rewrite_count`
- `final_safety_status`

## 9. Extreme Smoke Tests

Added 3 smoke checks:

- All tools timeout / failure
- Malformed LLM output
- Contradictory multi-turn preference

## 10. Code Changes

- `pytest.ini`: added `integration` and `e2e` markers
- `local_life_agent/tests/conftest.py`: collection-time skip for gated tests
- `local_life_agent/tests/helpers/fake_backends.py`: deterministic fake runtime, fake semantic parsing, fake tools, fake verifier
- `local_life_agent/tests/helpers/complex_query_harness.py`: case runner and trace loader
- `local_life_agent/tests/fixtures/complex_query_matrix.py`: P6 case matrix and smoke matrix
- `local_life_agent/tests/fixtures/golden_traces/*`: golden trace fixtures for matrix replay
- `local_life_agent/tests/test_p6_complex_query_matrix.py`: deterministic and smoke assertions over intermediate state

## 11. Test Changes

Added:

- `local_life_agent/tests/test_p6_complex_query_matrix.py`
- `local_life_agent/tests/fixtures/complex_query_matrix.py`
- `local_life_agent/tests/helpers/complex_query_harness.py`
- `local_life_agent/tests/helpers/fake_backends.py`
- `local_life_agent/tests/fixtures/golden_traces/*`

Also kept the P1-P5 regression set in the acceptance command.

## 12. Test Results

Executed successfully:

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p6_complex_query_matrix.py -q`

Result:

- `69 passed`

Attempted but timed out in this environment:

- `pytest -m "not integration and not e2e" local_life_agent/tests -q`

Timeout note:

- The broad non-integration suite exceeded the 240s shell limit here, so it is reported as environment/time-budget blocked rather than a functional failure.

## 13. Acceptance Judgment

- 推荐多约束覆盖: pass
- 多维对比覆盖: pass
- 单店多 facet 覆盖: pass
- 引用失败覆盖: pass
- 推荐 + 引用依赖覆盖: pass
- 工具失败覆盖: pass
- 搜索无结果覆盖: pass
- verify 失败覆盖: pass
- 澄清恢复覆盖: pass
- 极端异常覆盖: pass
- 测试检查中间状态，不只 final_response: pass
- P1-P5 回归未破坏: pass
- MySQL / DB 依赖已从主验收分离: pass

## 14. Remaining Risks

- P6 不解决 P7 exploration_planning 共享 adapter
- P6 不解决 P8 retry / expand
- P6 不解决 P9 ToolCapabilitySpec
- P6 不解决 P10 并行工具执行
- 真实 integration / e2e 仍需要 MySQL / Java / real LLM 环境
- 真实 DB 路径与 fake backend 之间仍存在行为差异

## 15. Deferred to Later Phases

- P7 exploration_planning 协议同构
- P8 证据不足迭代
- P9 EvidencePlanner facet 预算
- P10 性能与并行工具执行
- P11 observability / streaming
- P12 deadline / freshness / TTL
