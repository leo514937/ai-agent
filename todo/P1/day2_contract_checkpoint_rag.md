# P1-Day2：路由合同 + Checkpointer + 证据评估

源文档： [../P1_langgraph_capability_completion_plan.md](../P1_langgraph_capability_completion_plan.md)

## 本日目标

- 路由合同传递到 RAG / Tool / Compose
- 真实启用 checkpointer
- 补上 Agentic RAG 证据评估

## 必须避免的架构冗余

- 不要让 RAG、Tool、Compose 各自私自改合同
- 不要把 checkpoint 退化成“有接口但不落盘”
- 不要把证据质量判断散到多个层重复实现

## 完成标准

- 合同可贯穿全链路
- 状态可保存与恢复
- 证据质量有统一评估层
