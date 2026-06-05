# P0-Day2：决策合并、合同与可追踪性

源文档： [../P0_intent-routing-4-stage-architecture.md](../P0_intent-routing-4-stage-architecture.md)

## 本日目标

- 完成 Decision Merger
- 完成 Contract Builder
- 完成 Execution Router
- 完成 Trace / Eval / Replay

## 改造边界

- 只处理“选哪条路、要带什么合同、怎么追踪”
- 不把业务修补堆回路由节点
- 不把答案修正文案混进路由合同

## 必须避免的架构冗余

- 不要让 route_gate 和 execution router 重复做分支判断
- 不要把 contract builder 做成第二个 route_gate
- 不要让 trace 变成只记录不验证

## 完成标准

- 路由结果是唯一事实源
- 每个执行路径都有合同可追踪
- 每轮都有可回放 trace
