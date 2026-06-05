# P2 图拓扑瘦身

源文档： [../P2_graph_topology_refactor_plan.md](../P2_graph_topology_refactor_plan.md)

预计工期：3 天

## 目标

把图拓扑从“能跑但偏重”收敛成“职责最小化”。

## 必须避免的冗余

- 不要让 `route_gate` 继续做半个编排层
- 不要让 `compose_answer` 继续做 God Node
- 不要让 `rag_subgraph` 和 `recommendation_subgraph` 重复实现同一套检索逻辑

## 分天文档

1. [day1_remove_plan_execute_and_route_gate.md](./day1_remove_plan_execute_and_route_gate.md)
2. [day2_compose_verify_and_clarify.md](./day2_compose_verify_and_clarify.md)
3. [day3_rag_recommendation_merge.md](./day3_rag_recommendation_merge.md)
