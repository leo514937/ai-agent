# P2-Day1：移除计划执行链并纯化路由

源文档： [../P2_graph_topology_refactor_plan.md](../P2_graph_topology_refactor_plan.md)

## 本日目标

- 废弃 `plan_execute_subgraph`
- 纯化 `route_gate`

## 必须避免的架构冗余

- 不要保留双轨调度
- 不要在路由节点里继续堆业务修补

## 完成标准

- 图上不再以 plan-execute 为常规主干
- 路由节点只做路由，不做修正
