# Agent 字段契约对齐验收报告

## 结论

* FAIL
* 当前实现不建议直接合并；协议层 snake_case 与 `from_location` 主路径已基本对齐，但仍存在会影响 Python 实际消费的契约回归和业务语义失真。

## 验收摘要

* 已通过项
  * Java `com.hmdp.dto.agent` 下请求 DTO、结果 DTO、wrapper DTO、trace DTO 已普遍加上 `@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)`。
  * `AgentDistanceEtaRequest` 已改为 `fromLocation` 主语义字段，并通过 `@JsonProperty("from_location")` 接收 snake_case 入参。
  * `AgentToolController` 已从 `request.getFromLocation()` 取值，不再从旧 `location` 字段取值。
  * Python `JavaToolExecutor` 已改为显式判断 `"data" in data`，空列表不会再因 `or` 逻辑退化成整个 envelope。
  * `local_life_agent/tests/test_java_tool_executor.py` 已补空列表回归用例。
  * Python 侧未发现 Java Agent tool 响应路径上的 camelCase 读取点。

* 未通过项
  * Java `search_shops` / `get_coupon_list` 返回了嵌套一层的 `{data: [...], total: n}`，但 Python 推荐/比选链路仍把 `coupon.data` 当列表、把 `search_shops.data` 当列表或 `items` 读取，运行时形状不一致。
  * `AgentShopDTO.tags` 通过 `deriveTopTags(...)` 推断生成，不是“无数据则空数组”的保守契约。
  * `AgentCouponDTO` 仍用推导/占位方式补 `discount_type`、`discount_value`、`min_consume` 等字段，与“不能伪造 registry 承诺字段”的要求不一致。
  * commit 拆分存在偏差：空列表修复被放在第 3 个 commit，而不是协议层阶段。

* 高风险残留项
  * `local_life_agent/tools/registry.py` 仍把 coupon 输出 schema 承诺为 `discount_type`、`discount_value`、`min_consume`、`valid_from`、`valid_until`、`stock`，与 Java 当前真实可提供字段不完全一致。
  * Java live / agent E2E 当前无法稳定通过；本次强制集成测试出现 HTTP 502 与超时，尚不能证明线上联调可用。
  * 当前 DTO / trace 中未定义 `request_id`、`trace_id` 字段，因此这两个字段不存在 snake_case 输出覆盖；如果协议层要求这两个字段，当前实现未覆盖。

## 详细检查结果

### 1. Java DTO snake_case 契约

Java DTO 包 `src/main/java/com/hmdp/dto/agent` 下，以下文件已统一看到 `@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)`：

* 请求 DTO：`AgentResolveShopRequest`、`AgentSearchShopsRequest`、`AgentDistanceEtaRequest`、`AgentOpenStatusRequest`、`AgentShopCardsRequest`、`AgentReviewSummaryRequest`、`AgentDealListRequest`、`AgentLocation`
* 响应 / 结果 DTO：`AgentShopDTO`、`AgentCouponDTO`、`AgentShopCardDTO`、`AgentReviewSummaryDTO`、`AgentSceneFitDTO`、`AgentDealDTO`、`AgentShopCardsResult`、`AgentReviewSummaryResult`、`AgentDealListResult`
* wrapper / trace DTO：`AgentToolResponse`、`AgentToolTraceDTO`

已覆盖的 snake_case 请求字段包括：

* `session_shop_ids`：`AgentResolveShopRequest`
* `from_location`：`AgentDistanceEtaRequest`
* `user_location`：`AgentShopCardsRequest`
* `shop_ids`：`AgentShopCardsRequest` / `AgentReviewSummaryRequest`
* `max_reviews`：`AgentReviewSummaryRequest`
* `people_count`：`AgentDealListRequest`

未发现 `to_location` 对应 DTO 字段；当前代码中也未定义 `request_id` / `trace_id` 字段，因此不存在这两个字段的 snake_case 输出验证。

测试方面：

* `src/test/java/com/hmdp/dto/agent/AgentProtocolContractTest.java` 已覆盖 `from_location` 绑定，以及 `AgentToolResponse` / `AgentToolTraceDTO` 的 `result_status`、`error_code`、`error_message`、`backend_source`、`tool_name`、`missing_shop_ids` 输出。
* `src/test/java/com/hmdp/dto/agent/AgentCouponContractTest.java` 已覆盖 `coupon_id`、`discount_type`、`discount_value`、`min_consume`、`valid_from`、`valid_until`、`stock` 的 snake_case 序列化。

结论：snake_case 注解覆盖整体通过，但 `request_id` / `trace_id` 不存在，无法算“已验收覆盖”。

### 2. Distance ETA 字段语义

检查结果：

* `src/main/java/com/hmdp/dto/agent/AgentDistanceEtaRequest.java` 已删除旧 `location` 主字段，仅保留 `fromLocation`，并通过 `@JsonProperty("from_location")` 绑定 snake_case。
* `src/main/java/com/hmdp/controller/AgentToolController.java` 的 `/distance-eta` 接口从 `request.getFromLocation()` 取值后传给 service。
* `src/test/java/com/hmdp/dto/agent/AgentProtocolContractTest.java` 已有 `from_location` 反序列化测试。

残留问题：

* `src/main/java/com/hmdp/service/AgentToolService.java` 的 service 方法签名仍为 `getDistanceEta(Long shopId, AgentLocation location)`；虽然控制器已传入 `fromLocation`，运行逻辑不再依赖旧 DTO 字段，但参数名仍是泛化语义，不利于后续维护判断。
* 未保留 `@JsonAlias("location")` 兼容逻辑。这本身不违反本轮“以 `fromLocation` 为主语义”的目标，但意味着旧调用方会直接失效。

结论：主链路已满足“`from_location` -> `fromLocation` -> service 使用”的验收要求，旧字段不再是主语义字段。

### 3. Python executor 空列表

检查结果：

* `local_life_agent/tools/executor.py` 已由易错写法改为：
  * `payload = data["data"] if "data" in data else data`
* `local_life_agent/tests/test_java_tool_executor.py` 中 `test_get_coupon_list_empty` 已断言 `result.data == []`。

结论：空列表包装 bug 已修复，且有单测覆盖。

需要注意：

* Java `get_coupon_list` 空结果当前返回 `AgentToolResponse.empty()`，即 `data = null`，并不是 `{ "data": [] }`。因此现有端到端链路并未用 live 返回实际验证“Java 后端返回空列表时 Python 是否保持 `[]`”，当前只有 executor 单测覆盖这一点。

### 4. Python camelCase 残留读取点

对 `local_life_agent/**/*.py` 做了 camelCase 关键字扫描：`requestId`、`traceId`、`errorCode`、`shopId`、`shopName`、`avgPrice`、`couponId`、`payValue`、`actualValue`。

结果：

* 未发现 Java Agent tool 响应路径上的 camelCase 读取点。
* 命中的 `ErrorCode` 均为 Python 枚举类名或测试引用，不属于读取 Java JSON 响应字段。

重点路径检查结果：

* `local_life_agent/tools/registry.py`：snake_case schema
* `local_life_agent/tools/executor.py`：snake_case envelope 读取
* `local_life_agent/tools/java_client.py`：snake_case envelope 透传
* `local_life_agent/planning/decision/candidate_decision.py`：内部使用 `shop_name`、`avg_price`、`coupon_titles` 等 snake_case

结论：未发现 Java Agent tool 响应路径上的 camelCase 读取点。

但发现一个更严重的“形状不一致”问题：

* `src/main/java/com/hmdp/service/AgentToolService.java` 在 `searchShops()` 与 `getCouponList()` 中返回 `AgentToolResponse.ok({data: dtos, total: n})`
* `local_life_agent/tools/executor.py` 只会把最外层 `data` 解开一次，因此 Python 侧得到的是内层对象 `{data: [...], total: n}`，不是列表本身
* 而 `local_life_agent/planning/decision/candidate_decision.py` 中：
  * `get_coupon_list` 路径要求 `isinstance(ev.coupon.get("data"), list)`
  * `search_shops` / `get_shop_cards` 路径只支持 `data` 为列表，或对象中使用 `items`

因此当前实现虽然没有 camelCase 残留，但存在 snake_case 之上的结构契约回归。

### 5. Coupon 字段真实性

`AgentShopDTO`：

* `alias` 当前固定输出空数组，这符合“无真实来源时返回空数组”的要求。
* `tags` 当前在 `src/main/java/com/hmdp/service/AgentToolService.java` 中通过 `deriveTopTags(...)` 推断生成，例如基于评分、均价、营业状态、是否有券等拼接标签。

结论：

* `alias` 处理可接受。
* `tags` 不满足本轮“暂无真实来源就返回空数组，不伪造标签”的约束，应视为必须修复项。

`AgentCouponDTO` / `registry.py`：

* Python `local_life_agent/tools/registry.py` 仍要求以下字段：`discount_type`、`discount_value`、`min_consume`、`valid_from`、`valid_until`、`stock`
* Java `src/main/java/com/hmdp/service/AgentToolService.java` 中：
  * `discountType` 被硬编码为 `"fixed"`
  * `discountValue` 由 `actualValue - payValue` 推导
  * `minConsume` 由 `actualValue / 100.0` 推导
  * `validFrom` / `validUntil` / `stock` 仅在秒杀券路径存在

结论：

* 当前 coupon 契约没有做到“只返回真实可证明字段”。
* 如果业务上无法保证所有券都真实具备 `discount_type`、`discount_value`、`min_consume`、`valid_from`、`valid_until`、`stock`，更合理的最小修复应是收紧 Python `get_coupon_list` schema，只保留真实稳定字段，例如：
  * `coupon_id`
  * `shop_id`
  * `title`
  * `description`
  * `pay_value`
  * `actual_value`
  * `status`

### 6. 测试运行结果

已执行命令与结果如下：

* `python -m compileall local_life_agent`
  * 结果：通过

* `pytest local_life_agent/tests/test_java_tool_executor.py -q`
  * 结果：通过
  * 摘要：`9 passed`

* `mvn -q "-Dtest=AgentProtocolContractTest,AgentCouponContractTest" test`
  * 结果：通过

* `pytest local_life_agent/tests -q`
  * 结果：失败
  * 摘要：`85 failed, 789 passed, 14 skipped, 2 xfailed`
  * 说明：失败集中在图路由、LLM 主路径、mock/backend observability、候选集解析等更大范围回归；并非都能直接归因到本轮字段契约改动，但当前分支整体并不处于“可放心合并”的测试状态。

* `pytest local_life_agent/tests/integration/test_java_backend_live.py -q`
  * 默认结果：`8 skipped`
  * 说明：未开启 live 环境变量时被跳过

* `LOCAL_LIFE_RUN_JAVA_INTEGRATION=1 LOCAL_LIFE_TOOL_BACKEND=java_api LOCAL_LIFE_JAVA_BASE_URL=http://localhost:8081 pytest local_life_agent/tests/integration/test_java_backend_live.py -q`
  * 结果：失败
  * 摘要：`7 failed, 1 passed`
  * 失败表现：
    * `resolve_shop` / `search_shops` 返回 HTTP 502
    * `get_shop_detail` / `get_coupon_list` / `check_open_status` / `get_distance_eta` / `search_shops_returns_seed_data` 出现超时
  * 结论：当前 Java live / E2E 未通过，无法据此证明联调可合并

## Blockers

* P0：`search_shops` / `get_coupon_list` 的 Java 返回形状与 Python 实际消费不一致。Java 返回 `{data: [...], total: n}`，但 Python 下游把 `coupon.data` 当列表、把 `search_shops.data` 当列表或 `items` 读取，存在直接运行时回归风险。
* P0：`AgentCouponDTO` 仍通过硬编码 / 推导填充 `discount_type`、`discount_value`、`min_consume` 等字段，不满足“不能伪造 registry 承诺字段”的验收要求。
* P1：`AgentShopDTO.tags` 通过推断生成，违反“无真实来源就返回空数组”的约束。
* P1：当前分支整套 Python tests 仍有 85 个失败，用例覆盖到主图、上下文恢复、推荐链路、mock 场景与工具观测；在这些失败未澄清前，不建议直接合并。
* P2：commit 拆分与计划不完全一致，空列表修复落在第 3 个 commit，而不是协议层阶段。
* P2：`request_id` / `trace_id` 当前未在 DTO 中定义，如这是外部协议要求，当前实现仍未覆盖。

## 建议修复

* 最小修复 1：统一 `search_shops` / `get_coupon_list` 的真实运行时 shape。二选一即可：
  * Java 直接把列表作为 `AgentToolResponse.data` 返回，`total` 若需要则另行约定；或
  * Python 相关消费点最小适配 `{data: [...], total: n}`，但必须把 `candidate_decision.py` 等读取点一起补齐。

* 最小修复 2：`AgentShopDTO.tags` 暂时改为空数组，并在 mapper 附近加简短中文注释说明“当前无稳定标签数据源，避免伪造标签”。

* 最小修复 3：收紧 `local_life_agent/tools/registry.py` 中 `get_coupon_list` 的输出 schema，只保留 Java 当前能真实稳定提供的字段；不要继续靠 Java 侧默认值/推导值去凑齐 schema。

* 最小修复 4：如果确实需要保留 coupon 扩展字段，必须先补充真实来源与字段语义说明，再补针对“非秒杀券”路径的真实性测试；否则不建议保留这些字段。

## 最终建议

* 不建议合并
