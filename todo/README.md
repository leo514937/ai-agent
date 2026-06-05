# Todo 索引

这份索引按当前项目状态下的**实际执行顺序**排列。

原则只有三个：

- 更快搭起稳定架构
- 少 bug、少返工
- 少 token、少重复修补

## 推荐顺序

### P0: [P0/README.md](./P0/README.md)
- 路由链路钉死
- 分天拆解为 2 天
- 重点：先稳决策链，避免后续反复串店、误路由、错分支

### P1: [P1/README.md](./P1/README.md)
- LangGraph 能力补全
- 分天拆解为 7 天
- 重点：先补 Typed State / Command / Checkpointer，再补回放、并发和流式能力

### P2: [P2/README.md](./P2/README.md)
- 图拓扑瘦身
- 分天拆解为 3 天
- 重点：收敛 `route_gate`、`compose_answer` 和重复子图边界

### P3: [P3/README.md](./P3/README.md)
- 代码体积和基础设施现代化
- 分天拆解为 4 天
- 重点：最后再做 settings / DI / retrieval / signals / stub 清理

## 源文档保留

根目录下的原始方案文档仍然保留，作为总览和历史记录：

- [P0_intent-routing-4-stage-architecture.md](./P0_intent-routing-4-stage-architecture.md)
- [P1_langgraph_capability_completion_plan.md](./P1_langgraph_capability_completion_plan.md)
- [P2_graph_topology_refactor_plan.md](./P2_graph_topology_refactor_plan.md)
- [P3_learning-agent-service-refactor-plan.md](./P3_learning-agent-service-refactor-plan.md)

## 统一执行原则

所有分天文档都必须遵守这些约束：

- 不要新增平行调度链，避免“双轨制”再次出现
- 不要把校验、修正、兜底混进生成节点
- 不要让 `route_gate` 或 `compose_answer` 继续膨胀成 God Node
- 不要为了拆分而拆分，职责边界必须清晰
- 每一天都要有明确验收，不留“看起来差不多”的中间态
