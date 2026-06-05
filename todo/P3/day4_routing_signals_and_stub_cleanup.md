# P3-Day4：routing_signals 解耦 + stub 清理

源文档： [../P3_learning-agent-service-refactor-plan.md](../P3_learning-agent-service-refactor-plan.md)

## 本日目标

- 拆分 `routing_signals.py`
- 清理 stub 和旧导出

## 必须避免的架构冗余

- 不要让路由信号继续集中在一个文件里
- 不要让旧 stub 和新实现长期并存

## 完成标准

- 路由规则分域清晰
- 旧路径收口完成
- 工程噪音显著下降
