# Day3：FacetExecutionPlan + 多工具执行 + CouponResult 标准化

> 来源：根据上传的 `local_life_agent_langgraph_7day_refactor_plan_v2_with_chat_stream_acceptance(1).md` 拆分整理。
>
> 总原则：
>
> - 每天都必须有 `/api/ai/chat/stream` 用户视角验收。
> - 每天都必须写清楚：参考架构、修改优先级、改动范围、验收输入、预期输出、完成标准。
> - Day1-Day4 先把业务不变量做硬；Day5-Day7 再把稳定节点迁移进 LangGraph。
> - 不允许只做单元测试；单元测试只能辅助，最终验收看 Chat 接口最终用户可见结果。


---

## 1. 当天目标

```text
1. 把 execute_tools[0] 改成按 FacetExecutionPlan 执行多个工具。
2. 新增 FacetResultBundle。
3. 新增 CouponResult / CouponItem。
4. 解决优惠券数量错误。
5. 保证问券时数量只来自实时 tool，不来自 RAG 历史套餐。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P0 | CouponResult 标准化 | 解决券数量错误 |
| P0 | ResponseBuilder 只读 realtime_available_count | 禁止自己数券 |
| P0 | 无 target_shop 问券必须澄清 | 防止随机查店 |
| P1 | FacetExecutionPlan | 为多工具和 LangGraph 子图做准备 |
| P1 | 多工具执行 | 支持“有券吗，现在营业吗” |
| P1 | GroundedVerifier 校验券数量 | 防止最终文本与 tool 不一致 |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day3 聚焦部分高亮)

```text
                         ┌──────────────────────┐
                         │  [FacetExecutionPlan] │ ==> [Day3 新增细粒度分发项]
                         └───────────┬──────────┘
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       │                             │                             │
       ▼                             ▼                             ▼
┌──────────────┐             ┌──────────────┐             ┌────────────────┐
│[tool branch] │             │ rag branch   │             │ recommend branch│
│[Day3 遍历执行]│             │              │             │                │
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘
       │                            │                             │
       ▼                            ▼                             ▼
┌──────────────┐             ┌──────────────┐             ┌────────────────┐
│[ToolResults] │             │ EvidencePack │             │ Recommendation │
│[Day3标准化券] │             │              │             │ Results        │
└──────┬───────┘             └──────┬───────┘             └───────┬────────┘
       │                            │                             │
       └──────────────┬─────────────┴──────────────┬──────────────┘
                      ▼                            ▼
          ┌──────────────────────────┐   ┌──────────────────────────┐
          │ EntityConsistency         │   │ [FacetResultBundle]       │
          │                          │   │ [Day3 汇总实时工具结果]     │
          └────────────┬─────────────┘   └────────────┬─────────────┘
                       │                              │
                       └──────────────┬───────────────┘
                                      ▼
                            ┌────────────────────┐
                            │ fuse_and_rank       │
                            └─────────┬──────────┘
                                      ▼
                            ┌────────────────────┐
                            │ [verify_grounding] │ ==> [Day3 强校验证据和券数量]
                            └─────────┬──────────┘
                                      ▼
                            ┌────────────────────┐
                            │ build_response      │
                            └────────────────────┘
```

### 3.2 当天要完成的架构链路与流转关系

在 Day3 阶段，我们要重点攻克**实时工具的多任务并发/顺序分发与结果标准化**。必须让最终的券数据全部追溯到可信的数据源。

当天核心打通并锁定的链路流转关系如下：
```text
【AnswerContract 生成完毕】
            │
            ▼
【FacetExecutionPlan】 （精细化分析各 facet 运行渠道）
            │
            ├─ [Item 1] facet: coupon       ==> 绑定 tool_name: "coupon_tool"
            ├─ [Item 2] facet: open_status  ==> 绑定 tool_name: "open_status_tool"
            ├─ [Item 3] ...
            │
            ▼
【多工具遍历执行链】（废弃原 execute_tools[0] 仅执行单个的逻辑）
            │
            ├─ 运行 "coupon_tool"      ==> 产出标准化 【CouponResult】（明确记录 realtime_available_count）
            ├─ 运行 "open_status_tool" ==> 产出标准化 【OpenStatusResult】
            │
            ▼
【FacetResultBundle】 （统一封装多工具业务包）
            │
            ├─ 传递给 [GroundedVerifier] ==> 强校验证据，若回答中券数量与 CouponResult 实时数量不符，自动截断/重写
            └─ 传递给 [ResponseBuilder]  ==> 模版仅允许读取 realtime_available_count，彻底切断从 RAG 历史数据中推断/累加券数的逻辑
```

> [!NOTE]
> **当前编排状态**：本阶段开发仍在 legacy 顺序主链路下进行。通过 FacetExecutionPlan 和 CouponResult 的规范化，彻底物理消除了“多 facet 工具由于路由过早截断只执行一个”及“优惠券查询数量数错、混用历史套餐”的高危缺陷。

---

## 4. 需要修改/新增的文件

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/facet_execution_plan.py
learning-agent-service/src/learning_agent_service/local_life/coupon_result.py
learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py
```

修改：

```text
learning-agent-service/src/learning_agent_service/local_life/execution_contract.py
learning-agent-service/src/learning_agent_service/local_life/route_review.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/local_life/grounded_verifier.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
```

---

## 5. 详细任务

### 5.1 新增 FacetExecutionPlan

```python
class FacetExecutionItem(BaseModel):
    facet: str
    source: Literal["tool", "rag", "tool_plus_rag", "context"]
    tool_name: str | None = None
    retrieval_mode: str | None = None
    required: bool = True

class FacetExecutionPlan(BaseModel):
    items: list[FacetExecutionItem]
```

### 5.2 新增 CouponResult

```python
class CouponItem(BaseModel):
    coupon_id: str
    title: str
    status: Literal["available", "unavailable", "expired", "unknown"]
    source: Literal["realtime_tool", "rag_history", "mock", "fallback"]
    shop_id: int | None = None
    valid_until: str | None = None
    price: float | None = None
    original_price: float | None = None
    description: str | None = None

class CouponResult(BaseModel):
    shop_id: int
    realtime_available_count: int
    realtime_total_count: int
    items: list[CouponItem]
    query_success: bool
    source: Literal["realtime_tool", "fallback", "rag_history"]
    error_message: str | None = None
```

### 5.3 数量规则

```text
最终答案中的券数量只能来自 CouponResult.realtime_available_count。
RAG 历史套餐不能计入实时券数量。
ResponseBuilder 不允许 len(rag_items) 推断券数量。
```

---

## 6. Chat/stream 验收用例

### Case D3-1：coupon + open_status 双工具执行

请求：

```json
{"sessionId":"day3-multi-tool-001","userId":"test-user","message":"海底捞水晶城店有券吗，现在营业吗？"}
```

预期：

```text
至少执行 coupon_tool 和 open_status_tool。
最终答案同时回答券和营业状态。
```

断言：

```python
assert_tool_called(result, "coupon")
assert_tool_called(result, "open_status")
assert_any_in(answer, ["券", "优惠", "暂无"])
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
```

### Case D3-2：券数量一致

请求：

```json
{"sessionId":"day3-coupon-count-001","userId":"test-user","message":"海底捞水晶城店有几张券？"}
```

预期：

```text
如果最终答案提到具体数量，该数量必须等于 CouponResult.realtime_available_count。
```

断言：

```python
coupon_count = extract_coupon_result_count(result)
mentioned_count = extract_mentioned_coupon_count(answer)

if mentioned_count is not None:
    assert mentioned_count == coupon_count
```

### Case D3-3：实时无券但 RAG 有历史套餐

请求：

```json
{"sessionId":"day3-coupon-history-001","userId":"test-user","message":"海底捞水晶城店有没有可用优惠券？"}
```

预期：

```text
如果 realtime_available_count = 0：
回答“实时接口未查到当前可用券”。
如果 RAG 有历史套餐，只能说“历史描述需以实时接口为准”。
不得把历史套餐算成实时券数量。
```

断言：

```python
if extract_coupon_result_count(result) == 0:
    assert_any_in(answer, ["实时", "未查到", "暂无"])
    assert "有 1 张" not in answer
    assert "有 2 张" not in answer
```

### Case D3-4：无 target_shop 时问券必须澄清

请求：

```json
{"sessionId":"day3-no-target-coupon-001","userId":"test-user","message":"有券吗？"}
```

预期：

```text
如果 session 无 current_shop，必须澄清是哪家店。
不得随机查询某个店。
不得执行 coupon_tool。
```

断言：

```python
assert_any_in(answer, ["哪家", "哪一家", "具体门店", "想查"])
assert_tool_not_called(result, "coupon")
```

### 回归测试

必须继续运行：

```text
Day1：target_shop / 多轮实体覆盖
Day2：AnswerContract / ResponseBuilder
```

---

## 7. Day3 完成标准

```text
1. D3-1 / D3-2 / D3-3 / D3-4 全部通过。
2. Day1-Day2 测试无回归。
3. FacetResultBundle trace 可见。
4. CouponResult trace 可见。
5. execute_tools[0] 不再是唯一执行路径。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / Tool Calling / 本地生活业务接口工程实现代理。今天只做 Day3：

1. 新增 facet_execution_plan.py。
2. 新增 coupon_result.py。
3. ExecutionContract 升级为 FacetExecutionPlan。
4. subgraph 执行层从 execute_tools[0] 改成遍历 execution_items。
5. coupon_tool 输出标准 CouponResult。
6. ResponseBuilder 券数量只能读取 CouponResult.realtime_available_count。
7. GroundedVerifier 校验回答中的券数量。
8. 新增 test_day3_tools_coupon_chat.py。
9. 必须跑 Day1-Day2 回归测试。
```
