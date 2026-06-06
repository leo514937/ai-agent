# P3-Day3：local_life_retrieval 拆分

源文档：[./P3_learning-agent-service-refactor-plan.md](./P3_learning-agent-service-refactor-plan.md)

## 本日目标

- 把 `rag/local_life_retrieval.py` 拆成包

## 必须避免的架构冗余

- 不要在 orchestrator 和策略层重复做同一套召回判断
- 不要把 location / intent / hybrid 检索逻辑相互耦合

## 完成标准

- 检索策略分层清楚
- 公共后处理收口
- 大文件不再继续膨胀
