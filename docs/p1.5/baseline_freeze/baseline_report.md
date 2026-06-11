# P1.5 Day 0 Baseline Freeze

## Graph Snapshot
- main graph topology: `docs/langgraph/main_graph.mmd`
- rag graph topology: `docs/langgraph/rag_graph.mmd`
- tool graph topology: `docs/langgraph/tool_graph.mmd`
- recommendation graph topology: `docs/langgraph/recommendation_graph.mmd`
- unified topology report: `docs/langgraph/langgraph_topology.md`

### Main Graph Nodes
- load_context
- request_legality
- illegal_request_response
- hard_guard
- clarification_or_reject
- query_safety
- safety_reject_response
- query_merge_for_local_life
- merged_query_safety
- top_level_intent_router
- identity_answer
- capability_answer
- direct_chat_answer
- out_of_scope_response
- understand_turn
- resolve_target_shop
- build_answer_contract
- build_source_contract
- complexity_router
- clarification_node
- direct_executor
- rule_review
- workflow_executor
- select_required_sources
- rag_executor
- tool_executor
- recommendation_executor
- merge_or_rank
- contract_review
- planner_node
- plan_validator
- plan_executor
- execute_plan_step
- collect_step_result
- complex_review
- final_answer
- final_answer_safety
- final_safety_fallback
- repair_answer
- final_with_limitations
- persist_session
- emit_final

## Baseline Samples
- direct_chat [direct_chat] -> `你好：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。`
- single_shop [single_shop] -> `海底捞水晶城店怎么样：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。`
- query_merge_pronoun [query_merge] -> `它有券吗：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。`
- recommendation [recommendation] -> `我先帮你推荐以下这几家店铺：  1. 你附近候选店A - 推荐理由：当前候选里它的综合信息比较靠前，值得优先查看。 - 适合场景：适合约会、聊天或轻松聚餐。 - 注意事项：建议先确认营业状态、预算和是否需要排队。  2. 你附近候选店B -`
- mixed_facet [mixed_facet] -> `海底捞水晶城店有券吗，现在营业吗：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。`
- plan_execute [planning] -> `Plan execution completed successfully.`

## Test Summary
- learning-agent-service/tests/test_routing_decision_matrix.py: passed
- learning-agent-service/tests/test_phase4_answer_verifier.py: passed
- learning-agent-service/tests/test_streaming_behavior.py: passed
- learning-agent-service/tests/test_sse.py: passed
- learning-agent-service/tests/test_langgraph_checkpointing.py: skipped (langgraph is not installed in this environment)
- learning-agent-service/tests/local_life/test_day1_target_shop_chat.py: passed
- learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py: passed
- learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py: passed
- learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py: passed
- learning-agent-service/tests/local_life/test_day7_golden_cases_chat.py: passed

## Case List
- direct_chat: direct_chat -> learning-agent-service/tests/test_phase4_answer_verifier.py
- single_shop: single_shop -> learning-agent-service/tests/local_life/test_day1_target_shop_chat.py::test_day1_1_explicit_single_shop
- query_merge_pronoun: query_merge -> learning-agent-service/tests/local_life/test_day1_target_shop_chat.py::test_day1_3_pronoun_inheritance
- coupon_only: coupon_only -> learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py::test_day3_4_no_target_shop_clarify
- recommendation: recommendation -> learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py::test_day5_graph_runner_keeps_recommendation_default_count
- comparison: comparison -> learning-agent-service/tests/rag/test_local_life_query_router.py::test_comparison_query_routes_to_multi_parent
- planning: planning -> learning-agent-service/tests/test_plan_execution_runtime.py::test_plan_execute_success_emits_plan_events_and_final_summary
- unsafe_prompt_injection: unsafe_prompt_injection -> learning-agent-service/tests/test_rag_gate.py

## Notes
- These files freeze the current baseline only; later days should diff against them instead of redefining the behavior.
- The repo currently stores Mermaid snapshots as the authoritative graph artifact. A PNG renderer is not required for this freeze step.