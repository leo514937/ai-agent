# 1. 定义全局 Schema / DTO / 枚举

## 目标
根据六层架构设计，在 `local_life_agent/domain/` 下提取各层之间流转的唯一数据协议，保证全局状态的一致性和无损透传。

## 实现细节要求

### 1. 全局流转上下文：GlobalTurnContext
贯穿所有层的核心结构。每层只补充字段，不覆盖上游。
- `trace_id`, `turn_id`, `session_id`, `user_id`, `raw_text`, `normalized_text`
- `user_context` (位置与 mock 偏好)
- `session_state_before`
- 中间产物引用：`semantic_frame`, `resolved_target`, `execution_plan`, `tool_result_set`, `evidence_pack`, `answer_plan`, `final_response`, `state_update`

### 2. 六层核心 DTO
- **TurnInput**: input_type, raw_text, user_context。
- **SemanticFrame**: top_intent, task_type, primary_task, facets, merchant_mentions, reference_mentions, hard_constraints, soft_preferences, ranking_signals, follow_up, confidence, need_context。
- **PendingClarification**: pending_id, original_task_type, candidate_targets, expected_reply_type 等。
- **ToolResult**: call_id, shop_id, tool_name, success, result_status, data, error_code, error_message, source, degraded。

> **注：关于核心复合 DTO**  
> `ExecutionPlan`、`EvidencePack`、`ResolveShopResult`、`AnswerPlan` 的最终复杂结构及嵌套子项，请**严格以 01.5 阶段文档为准**。01 阶段只做粗略占位，防止出现双版本 Schema。

### 3. 会话状态：SessionState
维护用户的长期上下文：
- `current_shop`: 单店成功后写入，推荐多店时**不写入**。
- `last_recommendation_list`: 上轮推荐候选。
- `active_constraints`: 当前筛选约束。
- `pending_clarification`: 未决澄清对象。
- `comparison_targets`, `comparison_result`, `suggested_shop`。

### 4. 核心全局枚举
- **TopIntent**: local_life, capability, chat, invalid, unsafe, out_of_scope。
- **TaskType**: recommendation, single_shop_query, coupon_query, comparison 等。
- **Facet**: coupon, open_status, distance, price 等。
- **ToolResultStatus (核心 AnswerPolicy 语境约束)**:
  - `ok`: 执行成功且获得了确切数据。（**允许话术**：能肯定回答，“查到有……”；**禁止话术**：“可能有”）
  - `empty`: 工具成功执行，并明确确认没有数据。（**允许话术**：能肯定回答，“当前暂无……”；**禁止话术**：“没查到，所以可能没有”）
  - `unknown`: 工具未能确认结果（网络异常等）。（**允许话术**：不能肯定，“暂时无法确认”；**禁止话术**：直接断言“没有”）
  - `failed`: 工具执行彻底失败且不可自动恢复。（**允许话术**：不能肯定，“获取失败，建议稍后再试”；**禁止话术**：当做 empty 断言“暂无”）
  - `circuit_open`: 熔断导致未调用。（**允许话术**：不能肯定，“服务暂时不可用”；**禁止话术**：“没有相关信息”）
- **细分 ErrorCode 体系**（用于排查具体失败原因）：
  `TOOL_TIMEOUT`, `NETWORK_ERROR`, `CIRCUIT_OPEN`, `INVALID_ARGUMENT`, `SHOP_NOT_FOUND`, `AMBIGUOUS_SHOP`, `LOW_CONFIDENCE`, `TOOL_NOT_REGISTERED`, `SCHEMA_VALIDATION_FAILED`, `LLM_JSON_PARSE_ERROR`, `LLM_ENUM_OUT_OF_RANGE`, `ANSWER_VERIFIER_FAILED`。

## 本阶段完成标准 (Definition of Done)
1. `domain/schemas.py`, `domain/enums.py`, `domain/state.py` 编码完成，无语法或类型校验错误。
2. `ToolResult` 等 DTO 包含明确的 `error_code` 支持。
3. **完成测试**：`tests/test_domain_schemas.py` 编写并 Pass（验证 Pydantic 模型/类型系统的合法性，确保成功进行 JSON 序列化与反序列化）。

## 阶段完成后的收尾

- 跑 schema / DTO / enum 的序列化和校验测试。
- 确认字段命名、枚举值、状态字段和后续阶段一致。
