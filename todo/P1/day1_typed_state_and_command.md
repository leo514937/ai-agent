# P1-Day1：Typed GraphState + Command API

源文档： [../P1_langgraph_capability_completion_plan.md](../P1_langgraph_capability_completion_plan.md)

## 本日目标

- 把 `StateGraph(dict)` 改成强类型状态
- 把路由改成 Command API 硬跳转

## 必须避免的架构冗余

- 不要让节点继续随意写 dict
- 不要保留“字符串路由 + 后续再修正”双轨制
- 不要为一个字段在多个地方做同义写法

## 完成标准

- 状态字段清晰
- 路由跳转硬约束
- 后续节点不能随意推翻路由
