# P3-Day2：DI 容器重做

源文档：[./P3_learning-agent-service-refactor-plan.md](./P3_learning-agent-service-refactor-plan.md)

## 本日目标

- 重做 `dependencies_impl.py`

## 必须避免的架构冗余

- 不要再堆大量 `_build_xxx()` 重复工厂
- 不要让容器和业务代码都保存同一份装配规则

## 完成标准

- 依赖树更清晰
- 单例生命周期更明确
- fallback 逻辑集中管理
