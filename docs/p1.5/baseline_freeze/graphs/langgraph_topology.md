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
	__start__(<p>__start__</p>)
	load_context(load_context)
	understand_turn(understand_turn)
	route_gate(route_gate)
	rag_subgraph(rag_subgraph)
	recommendation_subgraph(recommendation_subgraph)
	tool_subgraph(tool_subgraph)
	compose_answer(compose_answer)
	persist_session(persist_session)
	emit_final(emit_final)
	__end__(<p>__end__</p>)
	__start__ --> load_context;
	load_context --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Full Graph

```mermaid
graph TD
  subgraph main[Main Graph]
    main_load_context[load_context]
    main_understand_turn[understand_turn]
    main_route_gate[route_gate]
    main_rag_subgraph[rag_subgraph]
    main_recommendation_subgraph[recommendation_subgraph]
    main_tool_subgraph[tool_subgraph]
    main_compose_answer[compose_answer]
    main_persist_session[persist_session]
    main_emit_final[emit_final]
  end
  subgraph rag[RAG Subgraph]
    rag_build_plan[build_retrieval_plan]
    rag_execute[execute_rag_pipeline]
    rag_finalize[finalize_rag]
  end
  subgraph tool[Tool Subgraph]
    tool_plan[tool_plan]
    tool_execute[execute_tool_pipeline]
    tool_finalize[finalize_tool]
  end
  subgraph recommendation[Recommendation Subgraph]
    rec_prepare[prepare_recommendation]
    rec_dispatch[dispatch_shop_analysis]
    rec_analyze[analyze_one_shop]
    rec_reduce[reduce_shop_results]
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
  main_load_context --> main_understand_turn
  main_understand_turn --> main_route_gate
  main_route_gate --> main_rag_subgraph
  main_route_gate --> main_recommendation_subgraph
  main_route_gate --> main_tool_subgraph
  main_understand_turn --> main_compose_answer
  main_rag_subgraph --> main_compose_answer
  main_recommendation_subgraph --> main_compose_answer
  main_tool_subgraph --> main_compose_answer
  main_compose_answer --> main_persist_session
  main_persist_session --> main_emit_final
  rag_build_plan --> rag_execute
  rag_execute --> rag_finalize
  rag_finalize --> main_compose_answer
  tool_plan --> tool_execute
  tool_execute --> tool_finalize
  tool_finalize --> main_compose_answer
  rec_prepare --> rec_dispatch
  rec_dispatch --> rec_analyze
  rec_analyze --> rec_reduce
  rec_reduce --> rec_finalize
  rec_finalize --> main_compose_answer
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
	execute_rag_pipeline(execute_rag_pipeline)
	finalize_rag(finalize_rag)
	__end__([<p>__end__</p>]):::last
	__start__ --> build_retrieval_plan;
	build_retrieval_plan --> execute_rag_pipeline;
	execute_rag_pipeline --> finalize_rag;
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
	execute_tool_pipeline(execute_tool_pipeline)
	finalize_tool(finalize_tool)
	__end__([<p>__end__</p>]):::last
	__start__ --> tool_plan;
	execute_tool_pipeline --> finalize_tool;
	tool_plan --> execute_tool_pipeline;
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
	__start__(<p>__start__</p>)
	prepare_recommendation(prepare_recommendation)
	dispatch_shop_analysis(dispatch_shop_analysis)
	analyze_one_shop(analyze_one_shop)
	reduce_shop_results(reduce_shop_results)
	finalize_recommendation(finalize_recommendation)
	__end__(<p>__end__</p>)
	__start__ --> prepare_recommendation;
	dispatch_shop_analysis --> finalize_recommendation;
	prepare_recommendation --> dispatch_shop_analysis;
	finalize_recommendation --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```
