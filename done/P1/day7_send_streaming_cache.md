# P1-Day7：Send / Streaming / Cache

源文档：[./P1_langgraph_capability_completion_plan.md](./P1_langgraph_capability_completion_plan.md)

## 本日目标

- 补 Send API + map-reduce
- 对齐原生 streaming + SSE adapter
- 评估 CachePolicy / long-term store

## 必须避免的架构冗余

- 不要同时维护两套并行流式协议
- 不要把缓存、记忆、会话存储混成一个概念
- 不要为每个并发场景单独写特例

## 完成标准

- 多商家比较可并行展开
- SSE 与图事件对齐
- 缓存和记忆边界清晰
