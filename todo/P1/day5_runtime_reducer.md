# P1-Day5：Runtime Context + Reducer

源文档：[./P1_langgraph_capability_completion_plan.md](./P1_langgraph_capability_completion_plan.md)

## 本日目标

- 把配置和依赖从 state 中剥离
- 为并行分支和 Send 准备 reducer

## 必须避免的架构冗余

- 不要把运行时上下文、请求上下文、业务状态混在一个层里
- 不要为并行分支再造一份状态合并逻辑

## 完成标准

- context 清晰分层
- reducer 字段明确
- 并行分支可合并
