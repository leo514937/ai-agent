# 13. Streaming Event 协议表

## 目标
把当前 SSE 里的 `ack / error / final` 事件，扩展成可支撑 Agent 调试和前端增量展示的统一事件协议。

## 1. 事件总原则

- 事实性内容只能在工具结果和校验完成后输出。
- `answer_delta` 只能用于非事实性润色，或者用于已经锁定证据后的分段输出。
- `trace_started` 到 `final` 之间必须可串起同一个 `trace_id`。
- 当前 Java 入口已经能发 SSE，但协议还不完整，后续实现要保持兼容：`ack` 可以视作 `trace_started` 的兼容别名。

## 2. 事件协议表

| event_type | 触发时机 | 必填 payload | 可选 payload | 说明 |
| --- | --- | --- | --- | --- |
| `trace_started` | 回合初始化完成 | `trace_id`, `session_id`, `turn_id`, `workflow_version` | `page`, `user_id` | SSE 首个事件，标记本轮开始。 |
| `input_normalized` | 输入规范化完成 | `normalized_text` | `input_type` | 仅回显输入，不含业务结论。 |
| `pending_clarification_checked` | 读取澄清状态后 | `has_pending`, `pending_id` | `candidate_count` | 用于前端理解是否进入恢复流。 |
| `hard_guard_hit` | 命中硬拦截 | `guard_type`, `message` | `reason_code` | 纯无效输入或纯招呼直接返回。 |
| `intent_detected` | 顶层意图识别完成 | `top_intent` | `task_type`, `confidence` | 只表示路由，不输出事实。 |
| `semantic_frame_ready` | 语义帧解析完成 | `top_intent`, `task_type` | `merchant_mentions`, `facets`, `confidence` | 可用于调试槽位抽取结果。 |
| `target_resolved` | 商户解析完成 | `resolve_status` | `resolved_shop`, `candidates` | `resolved_shop` 只有 `RESOLVED` 才能出现。 |
| `clarify_requested` | 需要用户澄清 | `pending_id`, `question` | `candidate_text` | 进入等待用户回复状态。 |
| `task_planned` | 执行计划生成完成 | `execution_plan_id`, `task_type` | `tool_call_count`, `max_concurrency` | 只公开计划骨架，不公开内部敏感字段。 |
| `tool_call_started` | 工具开始执行 | `call_id`, `tool_name` | `target_shop_id`, `required`, `facet` | 可多次出现，支持并发。 |
| `tool_call_finished` | 工具执行结束 | `call_id`, `tool_name`, `status` | `result_status`, `error_code`, `degraded` | `status` 统一使用 `ok / empty / unknown / failed / circuit_open`。 |
| `evidence_built` | 证据包生成完成 | `evidence_pack_id`, `target_shop_ids` | `evidence_count`, `unknown_count` | 供调试和回归使用。 |
| `answer_plan_built` | 回答计划生成完成 | `answer_plan_id`, `answer_type` | `allowed_claim_count`, `forbidden_claim_count` | 方便检视 `strict_natural` 约束。 |
| `answer_delta` | 文本增量输出 | `delta_text` | `sequence`, `partial_section` | 只能在不违反事实锁定前提下输出。 |
| `final` | 最终回答完成 | `answer_text`, `trace_id`, `session_id`, `turn_id` | `cards`, `next_steps`, `task_chain`, `context` | 与当前实现兼容，最终状态。 |
| `error` | 任一阶段出错 | `code`, `message`, `stage` | `retryable`, `detail` | 统一错误出口，不再抛裸异常。 |

## 3. 事件顺序建议

```text
trace_started
  -> input_normalized
  -> pending_clarification_checked
  -> hard_guard_hit | intent_detected
  -> semantic_frame_ready
  -> target_resolved / clarify_requested
  -> task_planned
  -> tool_call_started / tool_call_finished
  -> evidence_built
  -> answer_plan_built
  -> answer_delta (optional, repeated)
  -> final
```

## 4. 前端消费约束

- 前端可在 `trace_started` 之后建立调试面板。
- `tool_call_started` / `tool_call_finished` 适合展示步骤进度。
- `answer_delta` 只用于体验增强，不得拿它当事实来源。
- `final` 到达前，前端不应把任何临时文本渲染为最终结论。

## 5. 后端实现约束

- SSE 事件必须按 `trace_id + session_id + turn_id` 串联。
- 如果工具层返回 `unknown / failed / circuit_open`，后端应优先发出 `tool_call_finished`，再由 `error` 或 `final` 收束。
- 现有 `ack` 事件可以保留，但建议在新协议中视为 `trace_started` 的兼容别名，避免前端一次性改动过大。
- 事实性回答必须在 `evidence_built` 和 `answer_plan_built` 之后才开始流式输出。

## 6. 统一 SSE 回复出口设计

### 6.1 设计目标

- 全链路只保留一个统一的 SSE 回复出口，避免多个节点各自写流导致事件顺序和协议不一致。
- 图内节点只返回结构化结果，不直接碰 HTTP 输出流。
- 最终由 `emit_response` 节点或其适配器把结构化结果转换成 SSE 事件并写出。

### 6.2 出口职责

统一 SSE 出口负责以下工作：

1. 接收 LangGraph 最终态及中间态摘要。
2. 统一封装 `trace_started / tool_call_started / tool_call_finished / answer_delta / final / error`。
3. 保证所有事件都携带同一组 `trace_id / session_id / turn_id`。
4. 在 `answer_verify` 失败、`fallback_answer`、`clarify_response` 等分支下保持一致的输出格式。
5. 将当前 `ack` 作为兼容事件保留，但内部语义统一映射到 `trace_started`。

### 6.3 建议落点

- `AiAssistantStreamService` 只保留一个最外层 `StreamingResponseBody` 适配器。
- `emit_response` 节点输出统一的 `StreamEventEnvelope` 或同等 DTO。
- `SSE writer` 仅存在于适配层，不进入业务节点。

## 阶段完成后的收尾

- 检查 SSE 事件顺序和兼容别名。
- 确认前端能按 `trace_started -> tool_call -> final` 这条线消费，不会提前把事实性内容当最终答案。
