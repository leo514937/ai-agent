# Phase F 全链路回归与残留扫描报告

## 扫描结果

### Python camelCase 读取点

对 `local_life_agent/**/*.py` 进行了精确字符串搜索：

* `requestId`
* `traceId`
* `errorCode`
* `shopId`
* `shopName`
* `avgPrice`
* `couponId`
* `payValue`
* `actualValue`
* `fromLocation`
* `toLocation`
* `userLocation`
* `sessionShopIds`
* `maxReviews`
* `peopleCount`

结果：

* 未发现 Python 业务代码中显式读取 Java Agent 响应 camelCase 字段的命中
* 之前的宽松搜索命中主要来自类型名 `ErrorCode`、注释或测试描述，不是 Java Agent tool payload 读取点

## 定向回归结果

### Python

* `pytest local_life_agent/tests/test_java_tool_executor.py local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_b_runtime_contracts.py local_life_agent/tests/test_phase_c_evidence_contracts.py local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py -q`
  * 通过，`24 passed`

### Java

* 本轮前序已通过：
  * `mvn -q "-Dtest=AgentProtocolContractTest,AgentCouponContractTest" test`

## 全量回归结果

### Python 全量

* `pytest local_life_agent/tests -q`
  * 失败：`85 failed, 804 passed, 14 skipped, 2 xfailed`

### 失败特征

从失败分布看，主要集中在以下非本轮字段契约主线问题：

* Candidate / clarify / target_resolve 主链路行为漂移
* semantic fallback 与 top intent router 预期不一致
* mock scenario / recommendation / context recovery 旧行为断言
* 观测类测试仍假设 backend 为 `mock/tests_fake`

这些失败不能被诚实归类为“字段契约修复新增回归”或“已在本轮最小修改范围内可安全顺手修复”的问题。

## Live / Java 集成

读取环境变量结果为空：

* `LOCAL_LIFE_RUN_JAVA_INTEGRATION`
* `LOCAL_LIFE_TOOL_BACKEND`
* `LOCAL_LIFE_JAVA_BASE_URL`

因此本轮未执行 `local_life_agent/tests/integration/test_java_backend_live.py`。

## 结论

Phase F 结论是：

* 字段契约修复本身的定向回归稳定
* Python 侧未发现新的 camelCase 读取残留
* 但仓库当前全量测试基线本身并不干净，存在大量超出本轮范围的历史/主链路失败

## 建议

下一步不要把这些失败混进字段契约提交里统一处理。

更稳妥的方式是：

* 当前字段契约修复按本轮阶段报告收口
* 另起专项处理 Candidate / clarify / semantic / mock 基线失败
* 在具备环境变量后单独执行 Java live integration
