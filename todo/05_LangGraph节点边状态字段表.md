# 12. LangGraph 节点 / 边 / 状态字段表

## 目标
把 `todo/00` 的线性主流程，收敛成可直接映射到 `StateGraph` 的节点、条件边和状态字段契约，避免后续实现时靠口头约定拼图。

## 1. 状态字段表

| 字段组 | 字段名 | 唯一写入方 | 主要读取方 | 说明 |
| --- | --- | --- | --- | --- |
| 路由标识 | `trace_id` / `turn_id` / `session_id` / `user_id` | `receive_input` | 全链路 | 贯穿一次对话回合的最小追踪键。 |
| 输入层 | `raw_text` / `normalized_text` / `input_type` | `receive_input` / `normalize_text` | `hard_guard` / `top_intent_router` | 原始输入与规范化输入必须同时保留。 |
| 顶层意图 | `top_intent` | `top_intent_router` | `semantic_parse` / `response_builder` | 只允许 `local_life / capability / chat / invalid / unsafe / out_of_scope`。 |
| 语义帧 | `semantic_frame` | `semantic_parse` / `slot_extractor` | `context_recovery` / `task_router` | 保存 `task_type`、`facets`、`merchant_mentions`、`reference_mentions`。 |
| 澄清状态 | `pending_clarification` | `clarify_decide` / `resolve_shop` | `check_pending_clarification` / `context_recovery` | 命中后优先于常规解析。 |
| 会话记忆 | `current_shop` / `last_recommendation_list` / `active_constraints` / `comparison_targets` | `state_update_planner` | `context_recovery` / `task_router` | 推荐多店后不得写 `current_shop`。 |
| 解析结果 | `resolved_target` / `resolve_shop_result` | `resolve_shop` | `task_plan` / `clarify_decide` | 仅 `RESOLVED` 才能进入执行。 |
| 执行计划 | `execution_plan` | `task_plan` / `facet_planner` / `comparison_planner` | `plan_validator` / `tool_execute` | 包含 `tool_calls`、并发组、预算和依赖。 |
| 工具结果 | `tool_result_set` / `tool_results` | `tool_execute` | `evidence_build` / `answer_verify` | 统一包装成 `ToolResult`，禁止下游直接碰裸返回。 |
| 证据层 | `evidence_pack` | `evidence_build` | `answer_plan_build` / `answer_verify` | 唯一事实来源。 |
| 回答层 | `answer_plan` / `final_response` | `answer_plan_build` / `answer_generate` / `final_response_build` | `answer_verify` / `emit_response` | `strict_natural` 只允许在计划框架内润色。 |
| 状态更新 | `state_update_plan` | `state_update_planner` | `persist_session_state` | 负责统一写 Session，其他节点不得越权写。 |
| 观测字段 | `event_log` / `metrics_tags` / `trace_spans` | 各节点按需追加 | `emit_response` / `observability` | 用于 trace / metrics / eval。 |

## 2. 节点表

| 节点 | 责任 | 输入字段 | 输出字段 | 下一跳 |
| --- | --- | --- | --- | --- |
| `receive_input` | 组装回合上下文 | `raw_text`、`session_id`、`trace_id` | `normalized_text`、`input_type`、基础 ID | `load_session_state` |
| `load_session_state` | 载入会话状态 | `session_id` | `current_shop`、`last_recommendation_list`、`pending_clarification` 等 | `check_pending_clarification` |
| `check_pending_clarification` | 优先处理挂起澄清 | `pending_clarification`、`raw_text` | 恢复任务或清空挂起状态 | `hard_guard` / `clarify_response` / `semantic_parse` |
| `basic_input_validate` | 输入合法性检查 | `normalized_text` | `input_type`、`error_code` | `normalize_text` / `emit_response` |
| `normalize_text` | 规范化文本 | `raw_text` | `normalized_text` | `hard_guard` |
| `hard_guard` | 拦截纯无效输入 | `normalized_text` | `guard_result` | `emit_response` / `top_intent_router` |
| `top_intent_router` | 顶层意图识别 | `normalized_text`、`session_state_before` | `top_intent` | `semantic_parse` / `emit_response` |
| `semantic_parse` | 业务语义解析 | `normalized_text`、`top_intent` | `semantic_frame` | `slot_extractor` / `frame_validator` |
| `slot_extractor` | 槽位抽取 | `semantic_frame` | `facets`、`merchant_mentions`、`reference_mentions` | `context_recovery` |
| `frame_validator` | 语义帧校验 | `semantic_frame` | `semantic_frame` 或 `error_code` | `context_recovery` / `clarify_response` |
| `context_recovery` | 多轮上下文恢复 | `session_state_before`、`semantic_frame` | `resolved_target` 候选 | `target_resolve` |
| `target_resolve` | 目标解析 | `merchant_mentions`、`reference_mentions`、`session_state_before` | `resolve_shop_result` | `clarify_decide` / `task_plan` |
| `clarify_decide` | 决定是否澄清 | `resolve_shop_result`、`semantic_frame` | `pending_clarification` 或可执行目标 | `clarify_response` / `task_plan` |
| `task_plan` | 任务路由与子图选择 | `top_intent`、`task_type`、`resolved_target` | `execution_plan` | `facet_plan` / `comparison_planner` / `tool_execute` |
| `facet_plan` | 拆分 facets 与必选/可选工具 | `semantic_frame`、`resolved_target` | `execution_plan.tool_calls` | `plan_validator` |
| `comparison_planner` | 构建对比计划 | `comparison_targets`、`resolved_target` | `execution_plan`、`comparison_matrix` 占位 | `plan_validator` |
| `plan_validator` | 执行计划校验 | `execution_plan` | `validated_plan` 或 `error_code` | `tool_execute` / `fallback_answer` |
| `tool_execute` | 调用工具与并发编排 | `validated_plan` | `tool_result_set` | `evidence_build` |
| `evidence_build` | 汇聚事实证据 | `tool_result_set` | `evidence_pack` | `answer_plan_build` |
| `answer_plan_build` | 生成回答计划 | `evidence_pack`、`semantic_frame` | `answer_plan` | `answer_generate` |
| `answer_generate` | 仅做自然语言润色 | `answer_plan`、`evidence_pack` | `draft_response` | `answer_verify` |
| `answer_verify` | 可信校验与 rewrite 决策 | `draft_response`、`evidence_pack` | `verify_result` | `rewrite` / `fallback_answer` / `final_response_build` |
| `rewrite` | 基于 verifier 结果重写回答 | `verify_result`、`answer_plan` | `draft_response` | `answer_verify` |
| `final_response_build` | 组装最终响应 | `draft_response`、`verify_result` | `final_response` | `state_update_plan` |
| `clarify_response` | 生成澄清提示 | `resolve_shop_result`、`pending_clarification` | `final_response` | `state_update_plan` |
| `fallback_answer` | 生成降级保底回答 | `error_code`、`evidence_pack` | `final_response` | `state_update_plan` |
| `state_update_plan` | 决定 Session 写法 | `final_response`、`session_state_before` | `state_update_plan` | `persist_session_state` |
| `persist_session_state` | 持久化 Session | `state_update_plan` | `session_state_after` | `emit_response` |
| `emit_response` | 发出最终响应或 SSE 事件 | `final_response`、`trace_id` | SSE / DTO | 结束 |

## 3. 条件边表

| From | 条件 | To | Session 写入 | Emit |
| --- | --- | --- | --- | --- |
| `check_pending_clarification` | 命中有效序号 / 指代恢复 | `target_resolve` | 继续保留原任务上下文 | 否 |
| `check_pending_clarification` | 明显换话题 | `top_intent_router` | 清空 `pending_clarification` | 否 |
| `hard_guard` | 纯无效 / 纯招呼 | `emit_response` | 不写业务状态 | 是 |
| `top_intent_router` | `out_of_scope` / `unsafe` | `emit_response` | 不写业务状态 | 是 |
| `semantic_parse` | JSON 失败且重试耗尽 | `clarify_response` | 不写业务状态 | 是 |
| `target_resolve` | `RESOLVED` | `task_plan` | 可写 `current_shop` | 否 |
| `target_resolve` | `AMBIGUOUS` | `clarify_response` | 写 `pending_clarification` | 是 |
| `target_resolve` | `LOW_CONFIDENCE` | `clarify_response` | 写 `pending_clarification` | 是 |
| `target_resolve` | `NOT_FOUND` | `emit_response` | 不写 `current_shop` | 是 |
| `plan_validator` | 非法计划 / 未注册工具 / 成环 | `fallback_answer` | 不写业务状态 | 是 |
| `tool_execute` | required tool `failed` / `unknown` | `fallback_answer` | 不中断会话，但不写目标结果 | 是 |
| `tool_execute` | optional tool `failed` / `unknown` | `evidence_build` | 记录 `unknown` | 否 |
| `answer_verify` | pass | `final_response_build` | 否 | 否 |
| `answer_verify` | rewrite attempts < 2 | `answer_generate` | 否 | 否 |
| `answer_verify` | rewrite attempts >= 2 | `fallback_answer` | 视场景写 `state_update_plan` | 是 |

## 4. 约束

- 节点必须单一职责，禁止一个节点同时改路由、改 Session、改答案文本。
- `top_intent`、`task_type`、`shop_id`、`ranking`、`state_update` 的决策唯一归属必须与 [04_补全核心协议与执行依赖.md](./04_补全核心协议与执行依赖.md) 保持一致。
- `emit_response` 只能消费已校验的最终产物，不得回头改写事实。
- `emit_response` 是唯一的 SSE 统一出口节点，其他节点不得直接写流。

## 5. 图形态说明

- 这不是纯 DAG，而是带条件边和回边的 LangGraph `StateGraph`。
- `answer_verify -> rewrite -> answer_generate`、`pending_clarification` 恢复、失败降级等路径都要求允许回跳。
- 如果未来需要 DAG，只能作为“单轮无重试快照图”，不能替代真实运行图。

## 阶段完成后的收尾

- 核对每个节点的输入、输出、条件边是否闭合。
- 确认没有“表里写了节点，但前后没有接上”的孤岛。
