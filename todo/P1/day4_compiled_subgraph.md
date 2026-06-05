# P1-Day4：真正 compiled subgraph

源文档： [../P1_langgraph_capability_completion_plan.md](../P1_langgraph_capability_completion_plan.md)

## 本日目标

- 让 RAG / Tool / Recommendation 成为真正 compiled subgraph

## 必须避免的架构冗余

- 不要再保留“顶层一堆函数节点 + 子图里再来一遍编排”
- 不要在主图和子图里重复实现同一套检索/执行路径

## 完成标准

- 子图可独立测试
- 子图边界清楚
- 主图只负责调度，不负责重复实现细节
