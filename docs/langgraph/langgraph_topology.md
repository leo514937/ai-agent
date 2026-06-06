# LangGraph Topology

## Main Graph
- entry_point: load_context
- terminal: END

```mermaid
graph TD
  START --> load_context
  load_context --> understand_turn
  load_context --> compose_answer
  understand_turn --> plan_execute_subgraph
  understand_turn --> route_gate
  understand_turn --> compose_answer
  understand_turn --> rag_subgraph
  understand_turn --> tool_subgraph
  route_gate --> compose_answer
  route_gate --> tool_subgraph
  route_gate --> rag_subgraph
  route_gate --> recommendation_subgraph
  rag_subgraph --> tool_subgraph
  rag_subgraph --> compose_answer
  recommendation_subgraph --> compose_answer
  tool_subgraph --> compose_answer
  plan_execute_subgraph --> compose_answer
  compose_answer --> persist_session
  persist_session --> emit_final
  emit_final --> END
```

## Rag Graph
- entry_point: build_retrieval_plan

```mermaid
graph TD
  build_retrieval_plan --> execute_rag_pipeline
  execute_rag_pipeline --> finalize_rag
  finalize_rag --> END
```

## Tool Graph
- entry_point: tool_plan

```mermaid
graph TD
  tool_plan --> execute_tool_pipeline
  execute_tool_pipeline --> finalize_tool
  finalize_tool --> END
```

## Recommendation Graph
- entry_point: prepare_recommendation

```mermaid
graph TD
  prepare_recommendation --> dispatch_shop_analysis
  dispatch_shop_analysis --> analyze_one_shop
  analyze_one_shop --> reduce_shop_results
  reduce_shop_results --> finalize_recommendation
  finalize_recommendation --> END
```
