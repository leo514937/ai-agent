# Day4：Tool Harness 与实时信息契约增强

> 目标：把优惠券、营业状态、距离、排队等实时信息从 RAG 中彻底分离，建立可靠 Tool Harness，并确保工具决策永远以最新一轮用户意图为优先输入。  
> 前置：Day3 已完成 RAG Dirty Guardrail，RAG 不再承担实时事实判断。  
> 产出：实时信息可追踪、可降级、不可编造。

---

## 1. Day4 要解决什么

实时或准实时信息：

```text
优惠券
营业状态
团购套餐
库存
排队
距离
配送时间
价格变动
```

不能由 RAG 或 LLM 猜。

典型错误：

```text
用户问：有券吗？
系统从 RAG 历史套餐里猜“有券”。

用户问：现在营业吗？
系统根据旧营业时间推断“应该营业”。
```

---

## 2. RealtimeContract

```python
class RealtimeContract:
    facet: str
    requires_tool: bool
    allowed_tools: list[str]
    freshness_required: str
    fallback_allowed: bool
    fallback_message: str
    cannot_infer_from_rag: bool
```

示例：

```text
coupon:
  requires_tool = true
  allowed_tools = ["coupon"]
  cannot_infer_from_rag = true

open_status:
  requires_tool = true
  allowed_tools = ["open_status"]
  cannot_infer_from_rag = true
```

---

## 3. 标准 ToolResult

```python
class ToolResult:
    tool_name: str
    shop_id: str | None
    status: str
    data: dict
    error_code: str | None
    error_message: str | None
    source: str
    fetched_at: str
    ttl_seconds: int | None
    is_realtime: bool
    confidence: float
```

`status`：

```text
success
empty
timeout
error
unsupported
degraded
```

---

## 4. Tool Planner

Tool Planner 输入：

```text
AnswerContract
TargetShopResolution
UserNeed
latest_turn_message
current_intent
```

输出：

```python
class ToolPlan:
    required_tools: list[str]
    optional_tools: list[str]
    tool_inputs: dict
    execution_mode: str
    timeout_budget_ms: int
    fallback_policy: str
```

---

## 5. latest_turn_message 优先

多轮：

```text
第 1 轮：海底捞水晶城店环境怎么样？
第 2 轮：这家有券吗？
```

第 2 轮必须：

```text
current_intent = coupon
required_tools = ["coupon"]
forbidden_facets = ["environment", "recommendation"]
```

不能继续沿用第 1 轮的 environment 语义。

---

## 6. recommendation 场景工具范围

多轮：

```text
第 1 轮：海底捞水晶城店怎么样？
第 2 轮：附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。
```

第 2 轮必须：

```text
route = recommendation
single_shop_mode = false
current_shop 不得作为整轮 tool_inputs 的主 shop_id
```

可以对推荐候选逐个调用：

```text
coupon
open_status
distance
```

不能只查上一轮的海底捞。

---

## 7. Context 规则

如果用户问：

```text
有券吗？
```

最终上下文只能包含：

```text
coupon tool result
coupon fallback state
```

不能包含：

```text
RAG 中历史套餐描述
用户评价里提到“团购”
```

除非明确标注：

```text
知识库曾提到相关优惠，但需以实时工具为准。
```

---

## 8. 降级策略

coupon tool 失败：

```text
我暂时没有查到这家店的实时优惠券信息，建议以店铺页面显示为准。
```

open_status tool 失败：

```text
我暂时无法确认这家店当前是否营业，建议以店铺页面实时状态为准。
```

禁止：

```text
根据 RAG 猜有券。
根据历史营业时间说现在营业。
```

---

## 9. 需要修改的模块

```text
learning-agent-service/src/learning_agent_service/local_life/tool_planner.py
learning-agent-service/src/learning_agent_service/local_life/tool_executor.py
learning-agent-service/src/learning_agent_service/local_life/tool_result_normalizer.py
learning-agent-service/src/learning_agent_service/local_life/answer_contract.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py
```

如果当前没有这些文件，可在现有 `tool_subgraph` / workflow services 中实现等价结构。

---

## 10. Trace 字段

```text
latest_turn_message
current_intent
tool_plan.required_tools
tool_plan.source_intent
tool_plan.blocked_by_realtime_contract
tool_call.tool_name
tool_call.shop_id
tool_result.status
tool_result.fetched_at
tool_result.is_realtime
tool_degraded
tool_error_code
answer_realtime_claim_supported
```

---

## 11. Harness 测试

新增：

```text
tests/local_life/tools/test_tool_harness_coupon.py
tests/local_life/tools/test_tool_harness_open_status.py
tests/local_life/tools/test_tool_degradation.py
tests/local_life/tools/test_realtime_contract.py
tests/local_life/tools/test_tool_latest_turn_priority.py
```

必测：

```text
coupon success / empty / timeout
open_status success / timeout
multi_tool
rag_plus_tool
latest_turn_priority
recommendation_tool_scope
```

---

## 12. 验收标准

Day4 完成后必须满足：

```text
1. coupon / open_status 必须走工具。
2. 工具结果结构统一。
3. 工具失败可降级，不影响整轮回答。
4. RAG 不能替代实时工具。
5. 最终回答中的实时声明必须有 ToolResult 支撑。
6. latest_turn_message 决定 tool plan。
7. recommendation 不能被上一轮 single_shop current_shop 污染。
8. trace 可复盘每个工具调用。
```

---

## 13. 给 Codex 的执行提示词

```text
你是资深 Tool Calling / Harness Engineering / Context Engineering 工程师。

Day1-Day3 已完成。请执行 Day4：Tool Harness 与实时信息契约增强。

必须完成：
1. 排查 coupon / open_status / tool_planner / tool_executor / tool_result_normalizer / tool_subgraph。
2. 统一 ToolResult 结构。
3. 定义 RealtimeContract，明确 coupon/open_status 不能从 RAG 推断。
4. ToolPlan 必须由 latest_turn_message、AnswerContract、TargetShopResolution、current_intent 决定。
5. 工具调用必须带 shop_id；recommendation 场景不得只继承上一轮 single_shop current_shop。
6. 增加 timeout、error、empty、degraded 的降级路径。
7. 最终回答中的实时声明必须由 ToolResult 支撑。
8. 新增测试并从 /internal/v1/chat/stream 触发。
9. 输出修改文件、测试结果、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
