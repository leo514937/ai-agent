# 字段契约系统级审计报告

审计时间：2026-06-29

## 结论

本仓库的字段契约问题主要集中在 `local_life_agent` 和 Java `AgentTool` 边界上，表现为：

- Python 侧 `registry.py` 明确定义了 snake_case 输入/输出 schema。
- Java 侧 `AgentToolController` / `AgentToolService` / DTO 仍然使用 camelCase 字段名。
- 当前没有看到统一的 `@JsonNaming(PropertyNamingStrategies.SNAKE_CASE)` 或逐字段 `@JsonProperty` 兜底。
- 这会导致多条 Agent 工具链在真实请求下出现字段丢失、默认值接管、返回结构不一致，属于高风险契约漂移。

## 发现

### 1. 高风险：Agent 工具请求字段命名与 Java DTO 不一致，多个工具会收不到关键参数

证据：

- Python 侧 registry 约定的是 snake_case：`resolve_shop.session_shop_ids`、`get_distance_eta.from_location`、`get_shop_cards.user_location`、`get_shop_review_summary.max_reviews`、`get_deal_list.people_count` 等，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 238-419。
- `JavaToolClient` 把 `args` 原样作为 JSON body 发给 Java 后端，只去掉了 `shop_id` 路径参数，没有做 snake_case -> camelCase 转换，见 [local_life_agent/tools/java_client.py](../local_life_agent/tools/java_client.py) 109-117。
- Java 请求 DTO 仍是 camelCase 字段：  
  - [src/main/java/com/hmdp/dto/agent/AgentResolveShopRequest.java](../src/main/java/com/hmdp/dto/agent/AgentResolveShopRequest.java) 15-18  
  - [src/main/java/com/hmdp/dto/agent/AgentDistanceEtaRequest.java](../src/main/java/com/hmdp/dto/agent/AgentDistanceEtaRequest.java) 13-15  
  - [src/main/java/com/hmdp/dto/agent/AgentShopCardsRequest.java](../src/main/java/com/hmdp/dto/agent/AgentShopCardsRequest.java) 16-22  
  - [src/main/java/com/hmdp/dto/agent/AgentReviewSummaryRequest.java](../src/main/java/com/hmdp/dto/agent/AgentReviewSummaryRequest.java) 16-20  
  - [src/main/java/com/hmdp/dto/agent/AgentDealListRequest.java](../src/main/java/com/hmdp/dto/agent/AgentDealListRequest.java) 13-17

影响：

- `get_distance_eta` 直接受损最明显：Python 发的是 `from_location`，Java controller/DTO 读的是 `location`，会落成 `null`，然后在服务层返回 `INVALID_ARGUMENT`，见 [src/main/java/com/hmdp/service/AgentToolService.java](../src/main/java/com/hmdp/service/AgentToolService.java) 228-253。
- `get_shop_cards`、`get_shop_review_summary`、`get_deal_list`、`resolve_shop` 的 session hint 也会因为字段没绑定而失效或退化成默认值，见 [src/main/java/com/hmdp/service/AgentToolService.java](../src/main/java/com/hmdp/service/AgentToolService.java) 258-320、325-410、415-506、53-105。

建议：

- 在 Java 端统一加 snake_case 反序列化策略，或在请求 DTO 上逐字段补 `@JsonProperty`。
- 至少先把 `from_location`、`user_location`、`shop_ids`、`max_reviews`、`people_count` 这些对齐到真实入参名称。

### 2. 高风险：Agent 工具输出契约与 registry 定义不一致，返回字段名和字段集合都对不上

证据：

- `search_shops` 的 registry 输出 schema 要求 snake_case 的 `shop_id`、`shop_name`、`avg_price`、`tags` 等字段，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 273-290。
- `get_shop_detail` 复用同一套 `_SHOP_RESULT_SCHEMA`，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 297-309。
- Java 实际返回的是 `AgentShopDTO`，字段是 `shopId`、`shopName`、`categoryId`、`avgPrice`、`businessHours` 等 camelCase，且没有 `alias` / `tags`，见 [src/main/java/com/hmdp/dto/agent/AgentShopDTO.java](../src/main/java/com/hmdp/dto/agent/AgentShopDTO.java) 20-33，以及 [src/main/java/com/hmdp/service/AgentToolService.java](../src/main/java/com/hmdp/service/AgentToolService.java) 929-944。
- `get_coupon_list` 的 registry 输出要求 `coupon_id`、`discount_type`、`discount_value`、`min_consume`、`valid_from`、`valid_until`、`stock`，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 311-329；但 Java `AgentCouponDTO` 只有 `couponId`、`shopId`、`title`、`description`、`payValue`、`actualValue`、`status`，见 [src/main/java/com/hmdp/dto/agent/AgentCouponDTO.java](../src/main/java/com/hmdp/dto/agent/AgentCouponDTO.java) 19-30 和 [src/main/java/com/hmdp/service/AgentToolService.java](../src/main/java/com/hmdp/service/AgentToolService.java) 947-956。
- `get_shop_cards`、`get_shop_review_summary`、`get_deal_list` 的 registry 也都是 snake_case schema，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 361-419；Java 端对应 DTO 分别是 `AgentShopCardDTO`、`AgentReviewSummaryDTO`、`AgentDealDTO`，字段同样是 camelCase，见 [src/main/java/com/hmdp/dto/agent/AgentShopCardDTO.java](../src/main/java/com/hmdp/dto/agent/AgentShopCardDTO.java) 16-34、[src/main/java/com/hmdp/dto/agent/AgentReviewSummaryDTO.java](../src/main/java/com/hmdp/dto/agent/AgentReviewSummaryDTO.java) 16-32、[src/main/java/com/hmdp/dto/agent/AgentDealDTO.java](../src/main/java/com/hmdp/dto/agent/AgentDealDTO.java) 16-33。

影响：

- Python 侧后续消费如果按 registry schema 读取，会找不到关键字段，尤其是 shop 卡片、评价摘要、优惠券信息和团购信息。
- 这会把“真实证据”变成“结构上看似成功、语义上却缺字段”的半截结果。

建议：

- 要么把 Java DTO 全部改成 snake_case 序列化输出，要么在 Python registry 和消费侧统一改成 camelCase。
- 以当前代码结构看，最省改动的路径是 Java DTO 加 `@JsonProperty` 或统一的 Jackson 命名策略，然后把 registry schema 同步回归确认。

### 3. 中风险：`search_shops` 的类别兜底在 registry 里不可达，后端能力和工具契约不一致

证据：

- Java 搜索服务支持 `category` 兜底分支，见 [src/main/java/com/hmdp/service/AgentToolService.java](../src/main/java/com/hmdp/service/AgentToolService.java) 124-130。
- 但 `search_shops` 的 registry 入参只定义了 `query`、`location`、`limit`，没有 `category`，见 [local_life_agent/tools/registry.py](../local_life_agent/tools/registry.py) 273-283。
- Java 请求 DTO 虽然有 `category` 字段，见 [src/main/java/com/hmdp/dto/agent/AgentSearchShopsRequest.java](../src/main/java/com/hmdp/dto/agent/AgentSearchShopsRequest.java) 13-18，但 Python 调度层不会把一个 schema 外字段稳定传进去。

影响：

- 后端代码看起来支持“按类别兜底”，但在正式工具契约中这条路径基本走不到。
- 这会让规划层和执行层对工具能力的理解不一致，出现“计划里写了类别筛选，实际没生效”的隐性退化。

建议：

- 如果确实要保留 category 搜索，把它补进 registry schema，并同步到规划器。
- 如果不打算支持，就删掉后端这条兜底逻辑，避免契约漂移。

### 4. 中风险：`JavaToolExecutor` 会把空列表结果错误地提升为整个响应包，破坏空结果契约

证据：

- `JavaToolExecutor.execute()` 对 `data.get("data")` 使用了 `or data`，见 [local_life_agent/tools/executor.py](../local_life_agent/tools/executor.py) 174-180。
- 这意味着只要 Java 返回的 `data` 是空列表 `[]`，Python 侧拿到的 `RawToolResult.data` 就不是空列表，而会退化成整个响应 envelope。
- 这个场景在测试里已经被显式覆盖为“空优惠券列表”，见 [local_life_agent/tests/test_java_tool_executor.py](../local_life_agent/tests/test_java_tool_executor.py) 142-158。

影响：

- 空结果不再保持 registry 里承诺的 list shape，后续消费会很难区分“空列表”与“整包响应对象”。
- 对 `get_coupon_list` 这种天然可能返回空集的工具尤其危险。

建议：

- 改成显式判断 `if "data" in data`，不要用 `or` 吞掉空列表。
- 空列表也应该保留为空列表，而不是整个 envelope。

## 总体判断

这次审计里，真正需要优先处理的是 Agent 工具边界上的字段契约统一问题。它不是单个字段写错，而是“Python registry / Java DTO / Jackson 序列化 / Python 消费侧”四层命名策略没有收敛，已经足以让真实链路出现静默退化。

如果后续要修，我建议按这个顺序：

1. 先统一请求字段名，优先修 `get_distance_eta`、`get_shop_cards`、`get_shop_review_summary`、`get_deal_list`。
2. 再统一输出字段名，优先修 `search_shops`、`get_shop_detail`、`get_coupon_list`。
3. 最后修 Python executor 对空列表的处理，避免空结果被错误包装。
