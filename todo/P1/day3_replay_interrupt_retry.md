# P1-Day3：Replay / Interrupt / Retry

源文档： [../P1_langgraph_capability_completion_plan.md](../P1_langgraph_capability_completion_plan.md)

## 本日目标

- 支持 time travel / replay / fork
- 支持 interrupt / resume
- 支持 RetryPolicy / timeout / degrade

## 必须避免的架构冗余

- 不要把重试逻辑散落在各个节点里
- 不要给同一错误设计多套恢复路径
- 不要让 interrupt 和普通澄清重复处理同一件事

## 完成标准

- 错路由可复现
- 确认类流程可暂停恢复
- 节点失败有统一降级机制
