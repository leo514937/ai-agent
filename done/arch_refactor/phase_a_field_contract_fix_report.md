# Phase A 字段契约止血报告

## 目标

Phase A 只做止血和基线收敛，不做结构重构：

* `search_shops` / `get_coupon_list` 统一返回列表 payload
* coupon 契约收紧到真实可提供字段
* `AgentShopDTO.tags` 返回空数组，不伪造标签
* `unsupported` 状态在 registry / normalizer 中保真
* 补充最小 contract tests

## 实际改动

### Python

* `local_life_agent/tools/registry.py`
  * `search_shops.output_schema` 改为数组
  * `get_coupon_list.output_schema` 改为数组
  * coupon schema 收紧为：
    * `coupon_id`
    * `shop_id`
    * `title`
    * `description`
    * `pay_value`
    * `actual_value`
    * `status`
  * `unsupported` 纳入状态枚举
* `local_life_agent/tools/normalizer.py`
  * `unsupported` 纳入合法 `result_status`
* `local_life_agent/tools/db_client.py`
  * `_row_to_coupon()` 不再伪造 `discount_* / min_consume / valid_* / stock`
  * 仅输出真实字段
* `local_life_agent/tests/test_java_tool_executor.py`
  * 增加 `data: []` 不回退为 envelope 的回归测试
* `local_life_agent/tests/test_phase_a_contracts.py`
  * 增加 Phase A 最小契约测试

### Java

* `src/main/java/com/hmdp/service/AgentToolService.java`
  * `searchShops()` 直接返回 DTO 列表
  * `getCouponList()` 直接返回 DTO 列表
  * `toAgentShopDTO()` 中 `tags` 改为空数组
  * `toAgentCouponDTO()` 删除伪造 coupon 字段逻辑
  * 清理未再使用的 `SeckillVoucher` 相关 import / 注入
* `src/main/java/com/hmdp/dto/agent/AgentCouponDTO.java`
  * 删除伪造字段
* `src/test/java/com/hmdp/dto/agent/AgentCouponContractTest.java`
  * 断言真实字段存在
  * 断言伪造字段不存在

## 验证结果

### Python

* `python -m compileall local_life_agent`
  * 通过
* `pytest local_life_agent/tests/test_java_tool_executor.py local_life_agent/tests/test_phase_a_contracts.py -q`
  * 通过，`15 passed`
* `pytest local_life_agent/tests/test_tool_result_status.py -q`
  * 通过，`6 passed`

### Java

* `mvn -q "-Dtest=AgentProtocolContractTest,AgentCouponContractTest" test`
  * 通过

## 结论

Phase A 已完成，当前基线满足进入 Phase B 的条件：

* 列表型 payload 契约已统一
* coupon 伪造字段已收紧
* `unsupported` 状态已保真
* 最小回归测试已补齐并通过

## 已知未处理项

以下内容不属于 Phase A，留待后续阶段按顺序处理：

* Python 侧更大范围的字段生命周期收敛
* `DistanceEta` 语义字段全链路核对
* wrapper / trace snake_case 后的全局读取点审计
* Evidence / Session / Decision 层兼容字段逐步下线
