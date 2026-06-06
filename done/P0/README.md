# P0 路由架构拆分

源文档： [../P0_intent-routing-4-stage-architecture.md](../P0_intent-routing-4-stage-architecture.md)

预计工期：2 天

## 目标

把本地生活 agent 的路由链路先钉死，避免后面一边做业务一边反复修路由。

## 必须避免的冗余

- 不要让静态路由和动态调度同时做同一层决策
- 不要把澄清、直答、拒识都压进同一个出口节点
- 不要让 `route_gate` 继续承担太多业务修补

## 分天文档

1. [day1_route_foundation.md](./day1_route_foundation.md)
2. [day2_contract_and_trace.md](./day2_contract_and_trace.md)
