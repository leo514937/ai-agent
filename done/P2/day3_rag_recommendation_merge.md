# P2-Day3：RAG 与 Recommendation 公共层梳理

源文档：[./P2_graph_topology_refactor_plan.md](./P2_graph_topology_refactor_plan.md)

## 本日目标

- 梳理 `rag_subgraph` / `recommendation_subgraph` 的公共检索层
- 消除重复的 Dense / Sparse / Metadata 组装逻辑

## 必须避免的架构冗余

- 不要在顶层同时暴露两条几乎相同的检索路线
- 不要让 RAG 和 Recommendation 各自维护一套重叠实现

## 完成标准

- 公共检索逻辑收敛
- 场景差异只保留在证据装配和模板层
- 拓扑更扁平
