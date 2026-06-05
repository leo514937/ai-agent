# P3 代码体积与基础设施现代化

源文档： [../P3_learning-agent-service-refactor-plan.md](../P3_learning-agent-service-refactor-plan.md)

预计工期：4 天

## 目标

把剩余的大文件和模板代码拆掉，提升可维护性，但放在最后做，避免一边重构一边制造新 bug。

## 必须避免的冗余

- 不要为了拆文件再造一套平行实现
- 不要把 settings / DI / retrieval / routing_signals 再次分裂成多套口径
- 不要在基础设施层引入新的双轨制

## 分天文档

1. [day1_settings_modernization.md](./day1_settings_modernization.md)
2. [day2_di_container.md](./day2_di_container.md)
3. [day3_local_life_retrieval_split.md](./day3_local_life_retrieval_split.md)
4. [day4_routing_signals_and_stub_cleanup.md](./day4_routing_signals_and_stub_cleanup.md)
