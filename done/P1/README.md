# P1 LangGraph 能力补全

源文档： [../P1_langgraph_capability_completion_plan.md](../P1_langgraph_capability_completion_plan.md)

预计工期：7 天

## 目标

把当前基础 LangGraph 编排补成可控、可回放、可恢复、可测试的工作流。

## 必须避免的冗余

- 不要再让 state 继续膨胀成随意 dict
- 不要重复造“软路由”和“硬路由”两套体系
- 不要把 checkpoint、replay、streaming 再做成平行实现

## 分天文档

1. [day1_typed_state_and_command.md](./day1_typed_state_and_command.md)
2. [day2_contract_checkpoint_rag.md](./day2_contract_checkpoint_rag.md)
3. [day3_replay_interrupt_retry.md](./day3_replay_interrupt_retry.md)
4. [day4_compiled_subgraph.md](./day4_compiled_subgraph.md)
5. [day5_runtime_reducer.md](./day5_runtime_reducer.md)
6. [day6_loop_guard_visualization.md](./day6_loop_guard_visualization.md)
7. [day7_send_streaming_cache.md](./day7_send_streaming_cache.md)
