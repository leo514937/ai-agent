# Day1：基线测试 + TargetShopPolicy + 多轮实体覆盖

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

Day1 合并原计划中的 Day0 与 Day1，原因是最终需要拆成 7 份每日执行文档。

当天目标：

```text
1. 建立 /api/ai/chat/stream 端到端测试框架。
2. 固化当前 5 个真实问题的 baseline。
3. 实现 target_shop 锁定。
4. 实现当前轮显式商铺覆盖历史商铺。
5. 修复“问 A 店却答 B 店”和“第二个商铺被第一个污染”。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P0 | Chat E2E 测试框架 | 后续所有天的验收基础 |
| P0 | TargetShopPolicy | 解决问 A 答 B |
| P0 | 当前轮实体覆盖 session.current_shop | 解决第二个商铺被第一个污染 |
| P0 | ResponseBuilder 使用 target_shop 作为回答主体 | 防止 ranked_candidates[0] 覆盖目标店 |
| P1 | trace/metrics 暴露 target_shop 与 single_shop_mode | 方便后续 Day2-Day7 回归 |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day1 聚焦部分高亮)

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
                         │ [Day1 锁定目标店作为主体]    │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ AnswerContract            │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ ResponseBuilder          │
                         │ [Day1 围绕目标店生成回答]    │
                         └──────────────────────────┘
```

### 3.2 当天要完成的架构链路与流转关系

在 Day1 阶段，我们主要是在**业务底层**将实体识别和锁定的这前半截关键链路做硬，确保后续高阶编排拥有可信的实体输入。

当天核心打通并锁定的链路流转关系如下：
```text
【当前轮用户输入】 
       │
       ▼
[normalize_query / extract_slots] （查询理解与槽位提取）
       │
       ▼
[UserNeedParser] （识别 required_facets 意图）
       │
       ▼
[resolve_target] ==> 触发【TargetShopPolicy】核心策略 ───┐
                                                       │
  ┌────────────────────────────────────────────────────┘
  ▼
【锁定最终 target_shop (shop_id / shop_name / source)】 ───┐
                                                       │
  ┌────────────────────────────────────────────────────┘
  ▼
【确立 single_shop_mode 或是 recommendation_mode 模式】
       │
       ▼
【传递给末端 ResponseBuilder 】 ==> 强制让回答主体锁死为 target_shop，杜绝 RAG Fallback 或随机候选店的非法篡改。
```

> [!NOTE]
> **当前编排状态**：此时所有大流程依然走 `LocalLifeSubgraph.run_stream` 手写顺序工作流，我们先不改变整体编排形式，专注于物理修复“问A答B”和“第二轮被第一轮污染”的链路高危缺陷。

---

### 3.3 槽位冲突解决硬规则

```text
当前轮显式商铺 > 用户选择序号 > 指代词 + session.current_shop > session.current_shop > RAG top1 fallback
```

严禁：
```text
session.current_shop 覆盖当前轮显式商铺
RAG top1 覆盖当前轮显式商铺
ranked_candidates[0] 覆盖 target_shop
```

---

## 4. 需要修改/新增的文件

新增：

```text
learning-agent-service/tests/local_life/chat_test_client.py
learning-agent-service/tests/local_life/test_day1_target_shop_chat.py
learning-agent-service/tests/local_life/golden_cases/local_life_chat_cases.yaml
learning-agent-service/src/learning_agent_service/local_life/target_shop_policy.py
```

修改：

```text
learning-agent-service/src/learning_agent_service/local_life/user_need_parser.py
learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
```

---

## 5. 详细任务

### 5.1 建立 ChatStreamTestClient

必须支持：

```python
class ChatStreamTestClient:
    def post_message(
        self,
        message: str,
        session_id: str,
        user_id: str = "test-user",
        extra_payload: dict | None = None,
    ) -> ChatStreamResult:
        ...
```

返回对象至少包含：

```python
class ChatStreamResult(BaseModel):
    final_answer: str
    delta_text: str
    events: list[dict]
    tool_calls: list[dict]
    tool_results: list[dict]
    retrieval_events: list[dict]
    metrics: dict
    error_events: list[dict]
```

### 5.2 新增 TargetShop

建议结构：

```python
class TargetShop(BaseModel):
    shop_id: int | None = None
    shop_name: str | None = None
    raw_mention: str | None = None
    source: Literal[
        "current_query",
        "pronoun_session",
        "candidate_selection",
        "session",
        "rag_fallback",
    ]
    confidence: float = 0.0
    is_explicit_in_current_turn: bool = False
    candidate_shop_ids: list[int] = []
```

### 5.3 修复 UserNeedParser 的 shop_detail 误触发

错误逻辑：

```python
has_detail_query = any(k in normalized_query for k in DETAIL_KEYWORDS) \
    or slots.shop_query is not None \
    or len(slots.shop_ids) > 0
```

正确逻辑：

```python
has_explicit_entity = slots.shop_query is not None or len(slots.shop_ids) > 0

if has_explicit_entity:
    entity_refs.append(...)

has_detail_query = any(k in normalized_query for k in DETAIL_KEYWORDS)
if has_detail_query:
    required_facets.append("shop_detail")
```

---

## 6. Chat/stream 验收用例

### Case D1-1：显式单店评价

请求：

```bash
curl -N -X POST "http://localhost:8080/api/ai/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"day1-single-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}'
```

预期：

```text
最终答案围绕海底捞水晶城店。
不得把其他店作为主体。
如果证据不足，必须说该店信息不足，不得换店。
trace 中 target_shop.source = current_query。
trace 中 single_shop_mode = true。
```

断言：

```python
assert "海底捞" in answer or "水晶城" in answer
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
assert_trace_value(result, "target_shop.source", "current_query")
assert_trace_value(result, "single_shop_mode", True)
```

### Case D1-2：多轮显式新商铺覆盖旧商铺

第一轮：

```json
{"sessionId":"day1-switch-shop-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

第二轮：

```json
{"sessionId":"day1-switch-shop-001","userId":"test-user","message":"巴奴毛肚火锅怎么样？"}
```

预期：

```text
第二轮必须围绕巴奴毛肚火锅。
第二轮不得继续回答海底捞。
trace 中 target_shop.source = current_query。
```

断言：

```python
assert "巴奴" in answer2
assert "海底捞水晶城" not in answer2
assert_trace_value(result2, "target_shop.source", "current_query")
```

### Case D1-3：指代词继承旧商铺

第一轮：

```json
{"sessionId":"day1-pronoun-001","userId":"test-user","message":"海底捞水晶城店怎么样？"}
```

第二轮：

```json
{"sessionId":"day1-pronoun-001","userId":"test-user","message":"它有券吗？"}
```

预期：

```text
第二轮可以继承海底捞水晶城店。
但 required_facets 必须是 coupon。
不得继续回答环境/综合评价。
```

断言：

```python
assert "券" in answer2 or "优惠" in answer2
assert "环境" not in answer2
assert "口味" not in answer2
assert "服务" not in answer2
assert_trace_value(result2, "target_shop.source", "pronoun_session")
```

### Case D1-4：Baseline 五问题快照

必须额外记录：

```text
1. 海底捞水晶城店环境怎么样？
2. 海底捞水晶城店有几张券？
3. 附近有没有推荐的餐厅？
4. 有券吗？  无上下文
5. 第一轮海底捞，第二轮巴奴
```

输出失败快照：

```text
session_id
message
final_answer
all_sse_events
tool_calls
tool_results
retrieval_results
metrics/trace
```

---

## 7. Day1 完成标准

```text
1. ChatStreamTestClient 可运行。
2. D1-1 / D1-2 / D1-3 全部通过。
3. target_shop trace 可见。
4. single_shop_mode trace 可见。
5. Day2-Day7 可以复用同一套 Chat 测试客户端。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / FastAPI / 本地生活 Agent 工程实现代理。今天只做 Day1：

1. 新增 chat_test_client.py，支持 /api/ai/chat/stream SSE 解析。
2. 新增 test_day1_target_shop_chat.py。
3. 新增 target_shop_policy.py。
4. 修复 EntityResolver，使其输出 target_shop。
5. 修复当前轮显式商铺覆盖 session.current_shop。
6. 修复 ResponseBuilder 回答主体，优先使用 target_shop。
7. 修复 UserNeedParser 中 shop_query 误触发 shop_detail 的风险。
8. 所有测试必须从 /api/ai/chat/stream 发起。
9. 完成后输出改动文件、测试结果、失败风险。
```
