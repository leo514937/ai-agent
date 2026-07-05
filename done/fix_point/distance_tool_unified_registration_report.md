# calculate_distance_km 统一接入报告

## 结论

已在当前 `toolcall` 分支完成直线距离工具 `calculate_distance_km` 的统一接入，并贯通到：

- Tool Registry
- Tool Gateway / Executor
- 规划层 `ExecutionPlan`
- EvidencePack / 证据归一化
- Answer Generator / Answer Verifier
- 单店多因子主链路

本次没有重写架构，也没有绕过 `ToolCallGateway`，只做了协议与路由的定点收口。

## 新工具语义

### 输入

- `origin`: `{lat, lng}`
- `destination`: `{lat, lng}`
- `mode`: 固定为 `"straight_line"`

### 输出

- 成功：
  - `distance_km`
  - `eta_minutes = null`
  - `method = "haversine"`
- 缺少 origin：
  - `result_status = "unknown"`
  - `blocked_reason = "missing_origin_coordinates"`
- 缺少 destination：
  - `result_status = "unknown"`
  - `blocked_reason = "missing_destination_coordinates"`
- 非法坐标：
  - `result_status = "failed"`
  - `error_code = "INVALID_COORDINATES"`

## 统一接入点

### 1. Tool Registry

已注册 `calculate_distance_km`，并为其配置独立 schema 与输出 schema，保证可以被网关和执行器识别。

### 2. Tool Executor / Fake Tools

`DbToolExecutor` 通过 `db_tools.calculate_distance_km` 执行，测试假实现也同步添加了同名包装。

### 3. 规划层

- `preferred_tool_for_facet("distance")` 已指向 `calculate_distance_km`
- `ExecutionPlan` 构建时，distance facet 会优先生成 `calculate_distance_km`
- 若 location 或目标坐标缺失，会记录 blocked tool call，而不是伪造距离

### 4. Evidence / Answer 链路

- Evidence 侧会把 `calculate_distance_km` 归一成 `distance` facet
- `blocked_reason` 会进入 facet reason / unknown item
- Answer 层改为输出“直线距离约 X 公里”
- Verifier 会拒绝 ETA、步行、驾车、路线等非直线距离语义

### 5. 主链路

单店多因子场景已从旧的 `get_distance_eta` 迁移到 `calculate_distance_km`，并且执行计划、工具调用、答案生成都能通过验证。

## 兼容性处理

仓库里仍保留 `get_distance_eta` 作为旧工具接口，便于历史测试和旧链路兼容，但新的 distance facet 规划与回答语义已经切换到 `calculate_distance_km`。

## 验证结果

已通过的定向验证：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_answer_verifier.py local_life_agent/tests/test_distance_facet_contract.py local_life_agent/tests/test_evidence_planner.py local_life_agent/tests/test_tool_gateway.py local_life_agent/tests/test_single_shop_multifacet.py -q`

结果：

- `67 passed, 5 warnings`

## 备注

- 未改动主图结构，也未新增平行执行链路。
- 距离工具只做直线距离，不提供 ETA / 驾车 / 步行推算。
- 缺少坐标时会返回可解释的 unknown，而不是编造结果。
