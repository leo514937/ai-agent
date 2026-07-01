# 06 ToolCall-only 范围

## 目标

本文件定义 ToolCall-only 本地生活非交易能力的工具范围、工具状态、职责边界与验收口径。

它服务于 Phase 0 / Phase 1，重点是把当前真实可调用工具、需要收口的工具、未来规划工具和当前明确禁止的工具分开，避免把 future tool 当成当前事实，也避免工具层承担最终推荐决策。

## 当前阶段口径

当前产品范围只做：

- 店铺查询
- 店铺状态
- 距离 / ETA
- 优惠券 / 团购
- 评价摘要
- 附近推荐
- 条件筛选
- 场景化推荐
- 多店对比
- 多轮指代
- 候选澄清

当前阶段不做：

- RAG
- 平台政策问答
- 商家入驻规则问答
- 退款规则问答
- 交易
- 下单
- 支付
- 退款
- 取消订单
- 预约提交
- 订单 mutation tool
- 自由 ReAct loop
- 开放式 multi-agent handoff

## 工具状态分类

| 类别 | 定义 | 是否允许主链路调用 | 是否允许 Phase 1 修改 | 是否允许写入 ToolPlan | 是否允许出现在测试 mock | 是否可作为当前事实描述 |
| --- | --- | --- | --- | --- | --- | --- |
| `existing tool` | 当前代码里已经存在并可调用，可以作为当前事实描述 | 是 | 是 | 是 | 仅限测试目录 / 测试配置 | 是 |
| `current tool to refactor` | 当前代码里已经存在，但职责边界需要收口 | 是 | 是，且 Phase 1 重点收口 | 是 | 仅限测试目录 / 测试配置 | 是，但必须注明职责边界 |
| `future tool` | 当前代码里不存在或未确认存在，只能作为未来规划 | 否 | 否，Phase 1 不依赖 | 否 | 否 | 否 |
| `forbidden in current stage` | 当前阶段明确不做 | 否 | 否 | 否 | 否 | 否 |

### 四类工具的简明定义

- `existing tool`：当前代码里已经存在并可调用。
- `current tool to refactor`：当前代码里已经存在，但职责边界需要收口，Phase 1 可以修改其职责。
- `future tool`：当前代码里不存在或未确认存在，只能作为未来规划，不能写成当前事实。
- `forbidden in current stage`：当前阶段明确不做，不能进入工具注册表、ToolPlan、主链路或 mock。

## 真实工具核验结果

已核验的文件：

- [`local_life_agent/tools/db_tools.py`](../local_life_agent/tools/db_tools.py)
- [`local_life_agent/tools/registry.py`](../local_life_agent/tools/registry.py)
- [`local_life_agent/tools/gateway.py`](../local_life_agent/tools/gateway.py)
- [`local_life_agent/planning/plans/execution_plan_builder.py`](../local_life_agent/planning/plans/execution_plan_builder.py)

### existing tool

以下工具属于当前已存在并可调用的工具：

- `resolve_shop`
- `search_shops`
- `get_shop_detail`
- `get_coupon_list`
- `check_open_status`
- `get_distance_eta`
- `get_shop_cards`
- `get_shop_review_summary`
- `get_deal_list`

说明：

- `search_shops`、`get_shop_detail`、`get_coupon_list`、`check_open_status`、`get_distance_eta` 在 `db_tools.py` 中存在具体实现。
- `resolve_shop`、`get_shop_cards`、`get_shop_review_summary`、`get_deal_list` 也已在 `db_tools.py` 中实现，并已进入 `registry.py`。
- `registry.py` 是当前可调用工具白名单的中心定义。
- `gateway.py` 是当前统一调用入口。
- `execution_plan_builder.py` 已使用现有工具构建主链路计划，因此这些工具不能被写成“尚未存在”。

### current tool to refactor

当前最需要收口的工具是：

- `search_shops`

另外，任何在执行层或规划层中隐式承担排序、推荐、决策职责的工具调用路径，也属于需要收口的 current tool to refactor 范畴。

## search_shops 职责边界

`search_shops` 是 `existing tool`，也是 `current tool to refactor`。

当前问题是它可能同时承担召回、排序和截断，Phase 1 必须收口为“候选召回为主”。

### 允许保留

- `raw_order`
- `recall_rank`
- `distance_rank`
- `query_terms`
- `query_operator`
- 召回过程中的事实字段

### 不允许承担

- 决定最终推荐 winner
- 生成推荐话术
- 把工具返回顺序直接当作最终排序
- 输出 `final_winner`
- 输出 `best_shop`
- 输出任何“已经替用户选好”的结论

### 目标口径

- `search_shops` 只做候选召回。
- 最终推荐由 `DecisionCore` / `candidate_decision` 基于 `EvidencePack` 综合决定。
- 推荐问题不能只按 `search_shops` 返回顺序回答。

## 事实工具职责边界

以下工具只允许返回事实，不允许决定推荐或生成最终回答：

- `get_shop_detail`
- `get_coupon_list`
- `check_open_status`
- `get_distance_eta`

### 约束

- 只能返回事实、失败、空结果或部分成功状态。
- 不能决定推荐 winner。
- 不能生成最终回答。
- 不能补充 `EvidencePack` 之外的事实口径。
- 工具失败、空结果、超时必须进入 `ToolResultSet` 的 `failed_tools`、`empty_results`、`partial_success`。

## future tool 分层

以下工具可以规划，但如果当前代码没有，就必须标记为 `future tool`，不能写成当前事实。

### 位置与距离类

- `get_user_location`
- `calculate_distance`
- `estimate_travel_time`

### 搜索召回类

- `search_pois`
- `search_deals`
- `search_business_areas`

### 商家事实类

- `get_shop_status`
- `get_shop_business_hours`
- `get_shop_price_info`
- `get_shop_tags`
- `get_shop_facilities`
- `get_parking_info`
- `get_noise_level`

### 评价与场景类

- `get_review_summary`
- `get_negative_review_summary`
- `get_scene_review_tags`
- `get_scene_fit_score`
- `get_family_friendly_score`
- `get_date_friendly_score`

### 优惠与价值类

- `get_coupon_info`
- `get_deal_info`
- `calculate_value_score`

### 候选处理类

- `rank_shops`
- `rerank_candidates`
- `filter_candidates`

### 约束

- 这些都是 future tool，不是当前事实。
- Phase 1 不依赖它们。
- 如果未来新增，也必须先进入工具状态表，再补 ToolPlan、EvidencePack、测试。
- `rank_shops`、`rerank_candidates`、`filter_candidates` 即使未来存在，也不能替代 `DecisionCore` 的最终决策职责。

## forbidden 工具范围

### RAG / 政策类 forbidden

- `RAG retriever`
- `policy index`
- `refund policy retrieval`
- `coupon policy RAG`
- `merchant onboarding RAG`
- `platform policy QA`
- `merchant onboarding rule QA`
- `refund rule QA`

### 交易 / mutation 类 forbidden

- `transaction mutation tool`
- `payment tool`
- `refund tool`
- `booking submit tool`
- `cancel order mutation tool`
- `order create tool`
- `order update tool`
- `reservation submit tool`
- `payment confirm tool`

### 架构类 forbidden

- 自由 `ReAct` loop
- 开放式 `multi-agent handoff`
- 未受控 `tool auto-discovery`
- 无白名单工具执行

### 约束

- forbidden tool 不允许进入当前工具注册表。
- forbidden tool 不允许进入 ToolPlan。
- forbidden tool 不允许在主链路被调用。
- forbidden tool 不允许通过 mock 伪装成支持。
- forbidden tool 不允许作为 Phase 1 验收目标。

## ToolPlan / ToolCall / ToolResultSet / EvidencePack / DecisionPlan / AnswerPlan 数据流

工具结果的数据流必须保持如下顺序：

```text
ToolPlan
  -> ToolCall
  -> ToolResultSet
  -> EvidencePack
  -> DecisionPlan
  -> AnswerPlan
  -> final_response
```

### 约束

- `ToolResultSet` 不能直接进入 `final_response`。
- 工具结果必须先被 `EvidenceCore` 转成 `EvidencePack`。
- `EvidencePack` 不选择 winner。
- `DecisionPlan` 才能决定推荐、对比 winner 或单店判断。
- `ResponseCore` 只能表达 `DecisionPlan`，不能重新挑店。

## 工具白名单与注册表约束

### 当前实现事实

- 所有可调用工具必须在 `tool registry / gateway / executor` 白名单中。
- `ToolPlan` 只能引用白名单工具。
- `ExecutionCore` 必须拒绝执行 forbidden tool 或未知工具。
- 工具调用日志至少应记录 `tool_name`、`tool_status`、`latency`、`result_count`、`error_code`。

### 当前实现位置

- `registry.py` 负责工具注册表
- `gateway.py` 负责统一调用入口
- `executor.py` 负责实际执行

### Phase 1 目标口径

- 先梳理现有可调用工具边界。
- 后续 Core / workflow 阶段再稳定工具 registry。

## MOCK_LOCATION 与 get_user_location 边界

- `get_user_location` 当前如果不存在，应标记为 `future tool`。
- `MOCK_LOCATION` 不能伪装成 `get_user_location` 的真实返回。
- 主链路运行时不能把 `MOCK_LOCATION` 当作真实用户位置。

### 位置相关状态

位置相关状态必须通过以下字段表达：

- `location_status`
- `location_source`
- `requires_location`
- `location_missing_reason`

### 约束

- `location_status = missing` 时，附近类任务必须进入澄清、降级或无位置召回，并明确说明。
- `MOCK_LOCATION` 只能作为测试或显式 mock 上下文。

## 测试与验收要求

工具状态测试至少应覆盖：

- future tool 不能进入 current ToolPlan
- forbidden tool 不能被执行
- unknown tool 被拒绝
- `search_shops` 输出不能包含 `final_winner`
- `search_shops` 返回顺序不能直接决定最终推荐
- `get_coupon_list`、`check_open_status`、`get_distance_eta` 只能作为事实输入
- `ToolResultSet` 不能绕过 `EvidencePack` 进入 `final_response`
- `MOCK_LOCATION` 不能作为真实 provided location

## 当前事实、近期收口、最终目标

### 当前事实

- 当前已有真实可调用的工具注册表。
- 当前已有 `search_shops`、`get_shop_detail`、`get_coupon_list`、`check_open_status`、`get_distance_eta` 等事实工具。
- 当前已有 `get_shop_cards`、`get_shop_review_summary`、`get_deal_list`、`resolve_shop` 等工具。
- 当前主链路仍然需要通过工具结果、证据和决策分层来完成回答。

### 近期收口

- 收口 `search_shops` 的召回职责。
- 把事实工具限定为只返回事实。
- 把 future tool 和 forbidden tool 分开。
- 让工具白名单、ToolPlan、ExecutionCore、EvidenceCore 的边界一致。

### 最终目标

- 用统一的工具状态表表达当前事实和未来规划。
- 让工具层只做事实获取或候选召回，不做最终推荐决策。
- 让 `DecisionCore` 负责 winner 选择，`ResponseCore` 只负责表达。

## 兼容前述文档的口径

本文件与以下文档保持一致：

- [`todo/00_current_architecture_review.md`](./00_current_architecture_review.md)
- [`todo/01_target_architecture.md`](./01_target_architecture.md)
- [`todo/02_core_module_abstraction.md`](./02_core_module_abstraction.md)
- [`todo/03_workflow_design.md`](./03_workflow_design.md)
- [`todo/04_migration_phases.md`](./04_migration_phases.md)
- [`todo/05_state_and_schema_design.md`](./05_state_and_schema_design.md)

尤其需要保持以下口径不变：

- 当前阶段只做 ToolCall-only 本地生活非交易能力。
- 当前已有一级 `top_intent_router`。
- 当前 Review / Verifier 已参与主链路。
- 当前还不是稳定的能力包化 Agent。
- Phase 1 只做单主链路能力边界收口与模块化。
- 不把 future workflow 写成当前事实。
- 不做 RAG、交易、支付、退款、预约、订单 mutation。

## 可执行建议

1. 先把现有工具整理成 stable facts tools。
2. 再把 future tool 记入规划，不要混入当前实现文档。
3. forbidden 项要写进验收约束。
4. `search_shops` 的召回与排序职责要分开写清楚。
5. 工具状态、schema 和测试要一起收口。

