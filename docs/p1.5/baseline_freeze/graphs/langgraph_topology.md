# LangGraph Topology

## Main Graph
- entry_point: load_context
- terminal: END

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	load_context(load_context)
	request_legality(request_legality)
	illegal_request_response(illegal_request_response)
	hard_guard(hard_guard)
	clarification_or_reject(clarification_or_reject)
	query_safety(query_safety)
	safety_reject_response(safety_reject_response)
	query_merge_for_local_life(query_merge_for_local_life)
	merged_query_safety(merged_query_safety)
	top_level_intent_router(top_level_intent_router)
	identity_answer(identity_answer)
	capability_answer(capability_answer)
	direct_chat_answer(direct_chat_answer)
	out_of_scope_response(out_of_scope_response)
	understand_turn(understand_turn)
	resolve_target_shop(resolve_target_shop)
	build_answer_contract(build_answer_contract)
	build_source_contract(build_source_contract)
	complexity_router(complexity_router)
	clarification_node(clarification_node)
	direct_executor(direct_executor)
	rule_review(rule_review)
	workflow_executor(workflow_executor)
	select_required_sources(select_required_sources)
	rag_executor(rag_executor)
	tool_executor(tool_executor)
	recommendation_executor(recommendation_executor)
	merge_or_rank(merge_or_rank)
	contract_review(contract_review)
	planner_node(planner_node)
	plan_validator(plan_validator)
	plan_executor(plan_executor)
	execute_plan_step(execute_plan_step)
	collect_step_result(collect_step_result)
	complex_review(complex_review)
	final_answer(final_answer)
	final_answer_safety(final_answer_safety)
	final_safety_fallback(final_safety_fallback)
	repair_answer(repair_answer)
	final_with_limitations(final_with_limitations)
	persist_session(persist_session)
	emit_final(emit_final)
	__end__([<p>__end__</p>]):::last
	__start__ --> load_context;
	build_answer_contract --> build_source_contract;
	build_source_contract --> complexity_router;
	capability_answer --> final_answer;
	clarification_node --> final_answer;
	clarification_or_reject --> final_answer;
	collect_step_result --> complex_review;
	complex_review -.-> merge_or_rank;
	complex_review -.-> plan_executor;
	complexity_router -.-> clarification_node;
	complexity_router -.-> direct_executor;
	complexity_router -.-> planner_node;
	complexity_router -.-> workflow_executor;
	contract_review --> final_answer;
	direct_chat_answer --> final_answer;
	direct_executor --> rule_review;
	execute_plan_step --> collect_step_result;
	final_answer --> final_answer_safety;
	final_answer_safety --> final_safety_fallback;
	final_safety_fallback --> repair_answer;
	final_with_limitations --> persist_session;
	hard_guard -.-> clarification_or_reject;
	hard_guard -.-> query_safety;
	identity_answer --> final_answer;
	illegal_request_response --> final_answer;
	load_context --> request_legality;
	merge_or_rank --> contract_review;
	merged_query_safety --> top_level_intent_router;
	out_of_scope_response --> final_answer;
	persist_session --> emit_final;
	plan_executor --> execute_plan_step;
	plan_validator --> plan_executor;
	planner_node --> plan_validator;
	query_merge_for_local_life -.-> merged_query_safety;
	query_merge_for_local_life -.-> top_level_intent_router;
	query_safety -.-> query_merge_for_local_life;
	query_safety -.-> safety_reject_response;
	rag_executor -.-> merge_or_rank;
	rag_executor -.-> recommendation_executor;
	rag_executor -.-> tool_executor;
	recommendation_executor --> merge_or_rank;
	repair_answer --> final_with_limitations;
	request_legality -.-> hard_guard;
	request_legality -.-> illegal_request_response;
	resolve_target_shop --> build_answer_contract;
	rule_review --> final_answer;
	safety_reject_response --> final_answer;
	select_required_sources -.-> merge_or_rank;
	select_required_sources -.-> planner_node;
	select_required_sources -.-> rag_executor;
	select_required_sources -.-> recommendation_executor;
	select_required_sources -.-> tool_executor;
	tool_executor -.-> merge_or_rank;
	tool_executor -.-> recommendation_executor;
	top_level_intent_router -.-> capability_answer;
	top_level_intent_router -.-> direct_chat_answer;
	top_level_intent_router -.-> identity_answer;
	top_level_intent_router -.-> out_of_scope_response;
	top_level_intent_router -.-> understand_turn;
	understand_turn --> resolve_target_shop;
	workflow_executor --> select_required_sources;
	emit_final --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Full Graph

```mermaid
graph TD
  subgraph main[Main Graph]
    main_load_context[load_context]
    main_request_legality[request_legality]
    main_illegal_request_response[illegal_request_response]
    main_hard_guard[hard_guard]
    main_clarification_or_reject[clarification_or_reject]
    main_query_safety[query_safety]
    main_safety_reject_response[safety_reject_response]
    main_query_merge_for_local_life[query_merge_for_local_life]
    main_merged_query_safety[merged_query_safety]
    main_top_level_intent_router[top_level_intent_router]
    main_identity_answer[identity_answer]
    main_capability_answer[capability_answer]
    main_direct_chat_answer[direct_chat_answer]
    main_out_of_scope_response[out_of_scope_response]
    main_understand_turn[understand_turn]
    main_resolve_target_shop[resolve_target_shop]
    main_build_answer_contract[build_answer_contract]
    main_build_source_contract[build_source_contract]
    main_complexity_router[complexity_router]
    main_clarification_node[clarification_node]
    main_direct_executor[direct_executor]
    main_rule_review[rule_review]
    main_workflow_executor[workflow_executor]
    main_select_required_sources[select_required_sources]
    main_rag_executor[rag_executor]
    main_tool_executor[tool_executor]
    main_recommendation_executor[recommendation_executor]
    main_merge_or_rank[merge_or_rank]
    main_contract_review[contract_review]
    main_planner_node[planner_node]
    main_plan_validator[plan_validator]
    main_plan_executor[plan_executor]
    main_execute_plan_step[execute_plan_step]
    main_collect_step_result[collect_step_result]
    main_complex_review[complex_review]
    main_final_answer[final_answer]
    main_final_answer_safety[final_answer_safety]
    main_final_safety_fallback[final_safety_fallback]
    main_repair_answer[repair_answer]
    main_final_with_limitations[final_with_limitations]
    main_persist_session[persist_session]
    main_emit_final[emit_final]
  end
  subgraph rag[RAG Subgraph]
    rag_build_plan[build_retrieval_plan]
    rag_execute[rag_executor]
    rag_finalize[finalize_rag]
  end
  subgraph tool[Tool Subgraph]
    tool_plan[tool_plan]
    tool_execute[tool_executor]
    tool_finalize[finalize_tool]
  end
  subgraph recommendation[Recommendation Subgraph]
    rec_prepare[prepare_recommendation]
    rec_dispatch[recommendation_executor]
    rec_finalize[finalize_recommendation]
  end
  subgraph stages[Workflow Stages]
    stage_load_context[load_context]
    stage_parse_intent_slots[parse_intent_slots]
    stage_rag_gate[rag_gate]
    stage_query_rewrite[query_rewrite]
    stage_embedding[embedding]
    stage_qdrant_search[qdrant_search]
    stage_rerank[rerank]
    stage_hybrid_retrieve[hybrid_retrieve]
    stage_evaluate_evidence[evaluate_evidence]
    stage_citation_builder[citation_builder]
    stage_tool_planner[tool_planner]
    stage_tool_executor[tool_executor]
    stage_tool_result_normalizer[tool_result_normalizer]
  end
  main_load_context --> main_request_legality
  main_request_legality --> main_illegal_request_response
  main_request_legality --> main_hard_guard
  main_illegal_request_response --> main_final_answer
  main_hard_guard --> main_clarification_or_reject
  main_hard_guard --> main_query_safety
  main_clarification_or_reject --> main_final_answer
  main_query_safety --> main_safety_reject_response
  main_query_safety --> main_query_merge_for_local_life
  main_safety_reject_response --> main_final_answer
  main_query_merge_for_local_life --> main_merged_query_safety
  main_query_merge_for_local_life --> main_top_level_intent_router
  main_merged_query_safety --> main_top_level_intent_router
  main_top_level_intent_router --> main_identity_answer
  main_top_level_intent_router --> main_capability_answer
  main_top_level_intent_router --> main_direct_chat_answer
  main_top_level_intent_router --> main_out_of_scope_response
  main_top_level_intent_router --> main_understand_turn
  main_identity_answer --> main_final_answer
  main_capability_answer --> main_final_answer
  main_direct_chat_answer --> main_final_answer
  main_out_of_scope_response --> main_final_answer
  main_understand_turn --> main_resolve_target_shop
  main_resolve_target_shop --> main_build_answer_contract
  main_build_answer_contract --> main_build_source_contract
  main_build_source_contract --> main_complexity_router
  main_complexity_router --> main_clarification_node
  main_complexity_router --> main_direct_executor
  main_complexity_router --> main_workflow_executor
  main_complexity_router --> main_planner_node
  main_clarification_node --> main_final_answer
  main_direct_executor --> main_rule_review
  main_rule_review --> main_final_answer
  main_workflow_executor --> main_select_required_sources
  main_select_required_sources --> main_planner_node
  main_select_required_sources --> main_rag_executor
  main_select_required_sources --> main_tool_executor
  main_select_required_sources --> main_recommendation_executor
  main_select_required_sources --> main_merge_or_rank
  main_planner_node --> main_plan_validator
  main_plan_validator --> main_plan_executor
  main_plan_executor --> main_execute_plan_step
  main_execute_plan_step --> main_collect_step_result
  main_collect_step_result --> main_complex_review
  main_complex_review --> main_plan_executor
  main_complex_review --> main_merge_or_rank
  main_rag_executor --> main_tool_executor
  main_rag_executor --> main_recommendation_executor
  main_rag_executor --> main_merge_or_rank
  main_tool_executor --> main_recommendation_executor
  main_tool_executor --> main_merge_or_rank
  main_recommendation_executor --> main_merge_or_rank
  main_merge_or_rank --> main_contract_review
  main_contract_review --> main_final_answer
  main_final_answer --> main_final_answer_safety
  main_final_answer_safety --> main_final_safety_fallback
  main_final_safety_fallback --> main_repair_answer
  main_repair_answer --> main_final_with_limitations
  main_final_with_limitations --> main_persist_session
  main_persist_session --> main_emit_final
  rag_build_plan --> rag_execute
  rag_execute --> rag_finalize
  rag_finalize --> main_final_answer
  tool_plan --> tool_execute
  tool_execute --> tool_finalize
  tool_finalize --> main_final_answer
  rec_prepare --> rec_dispatch
  rec_dispatch --> rec_finalize
  rec_finalize --> main_final_answer
  stage_load_context --> stage_parse_intent_slots
  stage_parse_intent_slots --> stage_rag_gate
  stage_rag_gate --> stage_query_rewrite
  stage_query_rewrite --> stage_embedding
  stage_embedding --> stage_qdrant_search
  stage_qdrant_search --> stage_rerank
  stage_rerank --> stage_hybrid_retrieve
  stage_hybrid_retrieve --> stage_evaluate_evidence
  stage_evaluate_evidence --> stage_citation_builder
  stage_citation_builder --> stage_tool_planner
  stage_tool_planner --> stage_tool_executor
  stage_tool_executor --> stage_tool_result_normalizer
```

## Rag Graph
- entry_point: build_retrieval_plan

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	build_retrieval_plan(build_retrieval_plan)
	rag_executor(rag_executor)
	filter_rag(filter_rag)
	rerank_rag(rerank_rag)
	build_evidence_pack(build_evidence_pack)
	finalize_rag(finalize_rag)
	__end__([<p>__end__</p>]):::last
	__start__ --> build_retrieval_plan;
	build_evidence_pack --> finalize_rag;
	build_retrieval_plan --> rag_executor;
	filter_rag --> rerank_rag;
	rag_executor --> filter_rag;
	rerank_rag --> build_evidence_pack;
	finalize_rag --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Tool Graph
- entry_point: tool_plan

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	tool_plan(tool_plan)
	tool_executor(tool_executor)
	finalize_tool(finalize_tool)
	__end__([<p>__end__</p>]):::last
	__start__ --> tool_plan;
	tool_executor --> finalize_tool;
	tool_plan --> tool_executor;
	finalize_tool --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Recommendation Graph
- entry_point: prepare_recommendation

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	prepare_recommendation(prepare_recommendation)
	recommendation_executor(recommendation_executor)
	finalize_recommendation(finalize_recommendation)
	__end__([<p>__end__</p>]):::last
	__start__ --> prepare_recommendation;
	prepare_recommendation --> recommendation_executor;
	recommendation_executor --> finalize_recommendation;
	finalize_recommendation --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```
