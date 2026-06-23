# 2. 实现 ToolRegistry + ToolCallGateway + mock tools

## 目标
实现 `tools/` 目录下的执行层核心，分离工具注册、调用网关和具体执行逻辑。同时明确真实接口与 Mock 的替换边界。

## 实现细节要求

### 1. ToolRegistry (工具注册中心)
定义工具契约：
- **6个注册工具**：`resolve_shop`, `search_shops`, `get_shop_detail`, `get_coupon_list`, `check_open_status`, `get_distance_eta`。
- **元数据**：`input_schema`, `output_schema`, `timeout_ms`, `max_retries`, `circuit_breaker_enabled`, `output_status_enum`。

### 2. ToolCallGateway (统一调用网关)
统一的工具防腐层与执行入口，**不感知底层是 Mock、HTTP 还是 DB**：
- 校验 args 是否符合 Schema，不符合不调用。
- 检查 `CircuitBreakerManager`，若 OPEN 则直接返回 `circuit_open`。
- `RetryManager` 指数退避重试（针对 TIMEOUT / NETWORK_ERROR）。
- 统归化：无论底层抛出什么，统一转化为带 `error_code` 的 `ToolResult`。

### 3. Mock 数据规范与执行器边界
- **静态数据文件**：统一放在 `mock_data/` 下（如 `shops.json`, `coupons.json`, `open_status.json`, `distance_eta.json`）。
- **字段稳定约束**：店铺 JSON 必须包含 `shop_id`, `shop_name`, `alias`, `category`, `address`, `lat`, `lng`, `avg_price`, `rating`, `tags`。防止 search_shops 和 get_shop_detail 用了不同数据源导致串店。
- **接口边界透明**：
  定义基础接口：
  ```python
  class ToolExecutor:
      async def execute(self, tool_def, args) -> RawToolResult:
          pass
  ```
  `MockToolExecutor` 继承此接口读取本地 JSON；后期切 Java 接口只需实现 `RealToolExecutor`，上层 Planner 与 Gateway 完全无需修改代码。

### 4. MockTools
- 定义具体的纯静态 JSON 函数（在 `tools/mock_data/` 中放置）。
- **契约承诺**：Mock 工具内部必须根据请求抛出特定的 Domain 级异常（如遇到某个特殊字眼抛出 `TOOL_TIMEOUT` 异常），由 Gateway 统一进行 fallback 或封装为 `ToolResult`。

### 5. 真实接口切换清单 (Mock to Real 规划)
为了保证后续向 Java 真实服务演进的平滑过渡，在此预先列出切轨路径（当前实现仍仅使用 Mock）：
- `shops.json` -> 接入 `search_shops` / `get_shop_detail` 对应的 Http API 或真实 DB 搜索。
- `coupons.json` -> 接入后端发券与查券真实服务。
- `open_status.json` -> 接入实时营业状态判定接口。
- `distance_eta.json` -> 接入地图厂商（高德/腾讯）的 API 及本地 LBS 计算引擎。
- `InMemorySessionStore` -> 升级替换为 Redis 或永久性 DB 存储。
- `Mock User` 信息注入 -> 升级为获取真实的 OAuth 或 Session User Profile。
- `Mock Location` -> 对接前端/移动端的经纬度精准直传。

## 本阶段完成标准 (Definition of Done)
1. `tools/` 和 `mock_data/` 目录实现完成，静态资源按稳定字段准备完毕。
2. 统一 Executor 接口，验证多态透明性。
3. **完成测试**：`tests/test_tool_gateway.py` 编写并 Pass：
   - 能看到对 Mock Tool 的成功调用返回 `status: ok` 或 `empty`。
   - 验证超时触发自动重试，失败返回含 `error_code` 的 `unknown` 状态，不抛 Exception。

## 阶段完成后的收尾

- 跑工具网关测试，重点看 `ok / empty / unknown / failed / circuit_open` 是否都能被统一包装。
- 确认没有 LLM 自创工具名、没有裸异常外泄。
