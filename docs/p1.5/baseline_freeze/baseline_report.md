# P1.5 Day 0 Baseline Freeze

## Graph Snapshot
- main graph topology: `docs/langgraph/main_graph.mmd`
- rag graph topology: `docs/langgraph/rag_graph.mmd`
- tool graph topology: `docs/langgraph/tool_graph.mmd`
- recommendation graph topology: `docs/langgraph/recommendation_graph.mmd`
- unified topology report: `docs/langgraph/langgraph_topology.md`

### Main Graph Nodes
- load_context
- understand_turn
- route_gate
- plan_execute_subgraph
- rag_subgraph
- recommendation_subgraph
- tool_subgraph
- compose_answer
- persist_session
- emit_final

## Baseline Samples
- direct_chat [direct_chat] -> `你好，我在。你可以直接告诉我想查什么、想解释什么，或者把问题贴出来。`
- single_shop [single_shop] -> `海底捞火锅(水晶城购物中心店）：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。`
- query_merge_pronoun [query_merge] -> `海底捞火锅(水晶城购物中心店）当前有券信息可查，支持继续查看实时券详情。`
- recommendation [recommendation] -> `你方便补充一下城市或商圈吗？`
- mixed_facet [mixed_facet] -> `海底捞火锅(水晶城购物中心店）实时接口暂无可用券。`
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