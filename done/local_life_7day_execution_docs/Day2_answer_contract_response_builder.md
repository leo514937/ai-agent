# Day2：AnswerContract + ResponseBuilder 强约束

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
1. 新增 AnswerContract。
2. 让 ResponseBuilder 所有输出受 AnswerContract 控制。
3. 解决问券答环境、问营业答推荐、上下文 facet 泄漏。
4. 保证 Day1 的 target_shop 修复不回归。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P0 | AnswerContract | 限制最终能回答什么 |
| P0 | ResponseBuilder contract validation | 防止模型/模板乱补内容 |
| P0 | coupon_only / open_status_only 模板 | 修复问券答环境、问营业答推荐 |
| P1 | AnswerPlanner 接收 contract | 防止规划阶段就越界 |
| P1 | 多轮只继承实体，不继承 facet | 防止上一轮环境污染下一轮券查询 |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day2 聚焦部分高亮)

```text
                      ┌──────────────────────┐
                      │    route_gate         │
                      └──────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────────┐
     │ no_rag         │ │ single_shop_rag│ │ recommendation_rag │
     │ tool/direct    │ │ 单店证据检索     │ │ 多店推荐检索         │
     └────────────────┘ └───────┬────────┘ └─────────┬──────────┘
                                │                    │
                                ▼                    ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │ shop_id hard filter  │  │ retrieve topK chunks  │
                  │ target_shop only     │  │ group by shop_id      │
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             ▼                        ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │ EvidencePack          │  │ ShopGroupEvidence     │
                  │ 单店证据包             │  │ 多店证据组             │
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             └──────────┬─────────────┘
                                        ▼
                         ┌──────────────────────────┐
                         │ EntityConsistency         │
                         │ 证据/工具/候选店对齐       │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ Fusion / Rank             │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ [AnswerContract 契约防线] │ ==> [Day2 强制解析意图并确立 allowed/forbidden]
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ [ResponseBuilder 强校验]  │ ==> [Day2 彻底拆分模版 + 注入契约做拦截校验]
                         └──────────────────────────┘
```

### 3.2 当天要完成的架构链路与流转关系

在 Day2 阶段，我们要建立坚固的**输出契约防线**。从用户意图分析到最终生成文本，全链路都要受 `AnswerContract` 的严格约束。

当天核心打通并锁定的链路流转关系如下：
```text
【当前轮 target_shop 锁定】 ───┐
                              ├──> [build_contracts] （构建契约节点）
【user_need.required_facets】 ───┘           │
                                           ▼
                                 【AnswerContract 实体生成】
                                   - allowed_facets: 仅限所需
                                   - forbidden_facets: 禁止越界泄露
                                   - answer_style: 精准分类 (coupon_only 等)
                                           │
                                           ▼
【多路证据/工具包召回完毕】 ────────────────> 【ResponseBuilder 强吞吐控制】
                                           │
             ┌─────────────────────────────┴─────────────────────────────┐
             ▼                                                           ▼
  [拆分模块化子渲染模板]                                          [输出前 Contract Validation]
  - build_coupon_only_answer                                      - 动态校验最终文本中的事实
  - build_open_status_only_answer                                  - 强制剥离 forbidden 内容
  - build_distance_only_answer                                    - 违规自动收缩/降级最小回答
```

> [!NOTE]
> **当前编排状态**：本阶段依然在 legacy 顺序工作流中进行开发。但通过 AnswerContract + ResponseBuilder 拦截机制，彻底物理修复了“问券答环境、问营业答推荐”以及“上一轮上下文 facet 泄露污染当前轮”的高危缺陷。

---

### 3.3 AnswerContract 示例与策略

```text
用户：有券吗？
allowed_facets = ["coupon"]
forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit"]
answer_style = "coupon_only"

用户：现在营业吗？
allowed_facets = ["open_status"]
forbidden_facets = ["environment", "taste", "service", "recommendation"]
answer_style = "open_status_only"
```

---

## 4. 需要修改/新增的文件

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/answer_contract.py
learning-agent-service/tests/local_life/test_day2_answer_contract_chat.py
```

修改：

```text
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
learning-agent-service/src/learning_agent_service/local_life/answer_planner.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/local_life/route_review.py
```

---

## 5. 详细任务

### 5.1 新增 AnswerContract

```python
class AnswerContract(BaseModel):
    allowed_facets: list[str]
    forbidden_facets: list[str]
    required_sections: list[str]
    forbidden_sections: list[str] = []
    allowed_cards: list[str] = []
    forbidden_cards: list[str] = []
    answer_style: Literal[
        "coupon_only",
        "open_status_only",
        "distance_only",
        "single_shop_review",
        "multi_shop_recommendation",
        "comparison",
        "clarification",
    ]
    missing_info_policy: Literal[
        "say_unknown",
        "ask_clarify",
        "partial_answer",
    ]
```

### 5.2 ResponseBuilder 必须接收 contract

错误方式：

```python
build_response_bundle(user_need, evidence, tool_result)
```

目标方式：

```python
build_response_bundle(
    user_need=user_need,
    answer_contract=answer_contract,
    facet_result_bundle=facet_result_bundle,
    evidence_pack=evidence_pack,
    target_shop=target_shop,
)
```

### 5.3 输出前做 contract validation

```python
validate_answer_against_contract(answer_text, answer_contract)
```

若违反：

```text
1. 删除 forbidden facet 内容。
2. 如果无法安全删除，降级到 contract 允许的最小回答。
3. 不得继续输出越界内容。
```

---

## 6. Chat/stream 验收用例

### Case D2-1：coupon-only 不得答环境

请求：

```json
{"sessionId":"day2-coupon-only-001","userId":"test-user","message":"海底捞水晶城店有券吗？"}
```

预期：

```text
只回答券/优惠相关信息。
不得出现环境、氛围、口味、服务、推荐、适合聚餐等内容。
```

断言：

```python
assert_any_in(answer, ["券", "优惠", "暂无", "实时"])
assert_all_not_in(answer, ["环境", "氛围", "口味", "服务", "推荐", "适合"])
assert_trace_contains(result, "answer_contract.allowed_facets", "coupon")
assert_trace_contains(result, "answer_contract.forbidden_facets", "environment")
```

### Case D2-2：open-status-only 不得答推荐

请求：

```json
{"sessionId":"day2-open-001","userId":"test-user","message":"海底捞水晶城店现在营业吗？"}
```

预期：

```text
只回答营业状态或无法确认。
不得主动补口味、环境、推荐理由。
```

断言：

```python
assert_any_in(answer, ["营业", "开门", "休息", "时间", "暂时无法确认"])
assert_all_not_in(answer, ["环境", "口味", "服务", "推荐", "适合"])
```

### Case D2-3：general-review 可以综合回答

请求：

```json
{"sessionId":"day2-review-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

预期：

```text
可以综合回答口味、环境、服务、价格等。
但必须围绕目标店。
```

断言：

```python
assert_any_in(answer, ["整体", "评价", "环境", "口味", "服务", "价格"])
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
```

### Case D2-4：多轮上下文只继承实体，不继承 facet

第一轮：

```json
{"sessionId":"day2-context-facet-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

第二轮：

```json
{"sessionId":"day2-context-facet-001","userId":"test-user","message":"有券吗？"}
```

预期：

```text
第二轮继承目标店。
第二轮只回答券。
不得继续回答环境。
```

断言：

```python
assert_any_in(answer2, ["券", "优惠", "暂无", "实时"])
assert_all_not_in(answer2, ["环境", "氛围", "口味", "服务", "适合"])
```

### 回归测试

必须继续运行 Day1：

```text
D1-1 显式单店评价
D1-2 多轮显式新商铺覆盖旧商铺
D1-3 指代词继承旧商铺
```

---

## 7. Day2 完成标准

```text
1. D2-1 / D2-2 / D2-3 / D2-4 全部通过。
2. Day1 测试无回归。
3. answer_contract trace 可见。
4. ResponseBuilder 不再绕过 AnswerContract。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / Agent Response 工程实现代理。今天只做 Day2：

1. 新增 answer_contract.py。
2. 根据 user_need + target_shop + route 生成 AnswerContract。
3. ResponseBuilder 所有入口必须接收 answer_contract。
4. 拆分 coupon_only / open_status_only / distance_only / single_shop_review / multi_shop_recommendation / clarification 模板。
5. 增加 contract validation。
6. AnswerPlanner prompt 或规划输入必须包含 AnswerContract。
7. 新增 test_day2_answer_contract_chat.py。
8. 必须跑 Day1 回归测试。
```
