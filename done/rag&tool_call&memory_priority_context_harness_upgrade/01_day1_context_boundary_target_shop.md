# Day1：Context 边界与目标商家解析增强

> 目标：把“用户到底在问哪家店”从隐式上下文中剥离出来，升级为可解释、可测试、可回放的 Context Boundary 机制。  
> 重点：TargetShopPolicy、最新一轮消息优先、上下文优先级、指代继承、显式换店、低信息量输入拦截。  
> 产出：目标商家解析稳定，不串店，不被历史上下文污染。

---

## 1. 改造背景

本地生活 Agent 最核心的业务风险不是“回答不够长”，而是：

```text
用户问 A 店，系统答了 B 店；
用户显式换店，系统还沿用上一轮店；
用户说“这家”，系统不知道继承谁；
用户只输入一个逗号，也进入 RAG；
推荐场景中的候选店污染单店问答。
```

这些问题本质上都是 Context Boundary 不清楚。

Day1 的改造目标是：  
**把当前轮可用的上下文分层，把目标商家的来源、置信度、继承规则、覆盖规则全部显式化，并确保最新一轮消息优先。**

---

## 2. 用户端目标

用户体验必须满足：

```text
1. 用户显式输入店名时，系统必须以本轮店名为准。
2. 用户使用“这家/它/第一家”等指代时，系统必须能解释继承来源。
3. 用户没有给出目标店且上下文不足时，系统必须澄清。
4. 无效输入不能触发 RAG 或 Tool。
5. 推荐模式不能把 session.current_shop 强行当作目标店。
6. 当前轮显式意图必须压过历史 summary / 历史候选。
7. 当本轮意图是 recommendation 时，`session.current_shop` 和 `last_candidates` 只能作为弱辅助，不得自动收缩成单店目标。
```

---

## 3. Context Engineering 目标

### 3.1 明确上下文分层

建议将上下文分为四层：

```text
L0：当前用户输入
L1：前端显式上下文 client_context
L2：会话短期状态 session context
L3：历史候选 last_candidates / history_summary
```

优先级：

```text
本轮显式商家
  > 本轮显式意图
  > 前端 selected_shop
  > 指代继承
  > last_candidates 序号引用
  > session.current_shop
  > history_summary 弱参考
```

注意：

```text
history_summary 只能辅助理解，不能作为强目标店事实源。
最新一轮 message 必须能重算 target_shop，不能被旧 summary 覆盖。
recommendation 场景下，单店锚点只能作为历史弱信号，不能把整轮路由收缩成单店回答。
```

---

### 3.2 TargetShopResolution 结构

建议统一输出结构：

```python
class TargetShopResolution:
    target_shop_id: str | None
    target_shop_name: str | None
    source: str
    confidence: float
    is_explicit: bool
    is_pronoun_inherited: bool
    is_candidate_reference: bool
    should_clarify: bool
    candidates: list[ShopCandidate]
    reason: str
```

`source` 建议枚举：

```text
explicit_query
client_selected_shop
pronoun_session_current
candidate_reference
session_current
ambiguous
missing
```

---

## 4. Harness Engineering 目标

Day1 必须建立目标商家解析 harness。
同时必须建立“最新一轮消息优先”的多轮 harness，验证前一轮的店名、facet 和 route 不会覆盖当前轮。

### 4.1 目标商家解析测试集

新增：

```text
tests/local_life/context/test_target_shop_policy_harness.py
```

测试样例：

```json
[
  {
    "turns": ["海底捞水晶城店怎么样？"],
    "expected_target_shop": "海底捞水晶城店",
    "expected_source": "explicit_query"
  },
  {
    "turns": ["海底捞水晶城店怎么样？", "这家有券吗？"],
    "expected_target_shop": "海底捞水晶城店",
    "expected_source": "pronoun_session_current"
  },
  {
    "turns": ["海底捞水晶城店怎么样？", "巴奴毛肚火锅有券吗？"],
    "expected_target_shop": "巴奴毛肚火锅",
    "expected_source": "explicit_query"
  },
  {
    "turns": ["附近推荐几家适合约会的餐厅", "第一家有券吗？"],
    "expected_source": "candidate_reference"
  },
  {
    "turns": ["海底捞水晶城店怎么样？", "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"],
    "expected_route": "recommendation",
    "expected_target_shop": null,
    "expected_shop_anchor_behavior": "ignore_single_shop_anchor"
  },
  {
    "turns": ["，"],
    "expected_target_shop": null,
    "expected_route": "clarify_or_direct"
  }
]
```

---

### 4.2 必须断言的 trace 字段

每轮必须可观测：

```text
trace_id
latest_turn_message
raw_query
normalized_query
target_shop_id
target_shop_name
target_shop_source
target_shop_confidence
session_current_shop_before
session_current_shop_after
last_candidates_before
last_candidates_after
should_clarify
current_intent
latest_message_priority
```

---

## 5. 具体改造任务

### 5.1 强化低信息量输入 gate

新增或强化：

```text
is_low_information_query(query)
```

拦截：

```text
，
。
?
？
啊
嗯
1
...
```

低信息输入必须：

```text
不进入 RAG
不调用 Tool
不更新 session.current_shop
返回澄清或轻量提示
```

---

### 5.2 强化显式商家覆盖规则

当本轮 query 中识别出明确商家：

```text
必须覆盖 session.current_shop
必须覆盖 history_summary
必须覆盖 last_candidates 弱继承
```

禁止：

```text
因为上轮在聊 A 店，本轮显式 B 店仍查询 A 店
因为上一轮是推荐，本轮显式单店仍沿用推荐模式
```

---

### 5.3 强化指代继承规则

可继承指代词：

```text
这家
这店
它
他
她
刚才那家
上面那家
刚推荐的
第一家
第二家
第三家
```

继承必须有来源：

```text
session.current_shop
last_candidates
client_context.selected_shop
```

若没有来源，必须澄清。
如果本轮显式意图与历史上下文冲突，必须以本轮 message 为准。

---

### 5.4 推荐场景不锁单店

如果用户意图是：

```text
附近推荐
推荐几家
适合约会的餐厅
带长辈去哪吃
```

则：

```text
single_shop_mode = false
target_shop 只能作为弱参考
不能强过滤 shop_id
```

---

## 6. 验收标准

Day1 完成后必须满足：

```text
1. 显式店名优先级最高。
2. 指代继承可解释。
3. 无上下文指代会澄清。
4. 低信息输入不触发 RAG/Tool。
5. 推荐问题不被 current_shop 锁死。
6. 每轮 trace 都能解释 target_shop 从哪里来。
7. 最新一轮消息能覆盖历史弱信号和旧 route hint。
```

---

## 7. 给 Codex 的执行提示词

```text
你是资深 Python / LangGraph / Context Engineering 工程师。

请增强本地生活 Agent 的 Day1 Context Boundary 与目标商家解析能力。

必须完成：
1. 排查 TargetShopPolicy / entity_resolver / route_gate / session context 的目标商家解析逻辑。
2. 明确上下文优先级：
   本轮显式商家 > 本轮显式意图 > client_context.selected_shop > 指代继承 > last_candidates 序号引用 > session.current_shop > history_summary。
3. 增加 target_shop_resolution 结构化 trace 字段。
4. 修复低信息量输入触发 RAG/Tool 的问题。
5. 修复显式换店被历史 current_shop 污染的问题。
6. 修复“第一家/第二家”从 last_candidates 解析的问题。
7. 修复最新一轮消息不能覆盖旧 route hint / 旧 facet 的问题。
8. 增加 harness 测试：
   - 显式商家
   - 指代继承
   - 显式换店
   - 推荐后第一家
   - 低信息输入
9. 多轮消息优先级回归
10. 所有测试必须从 /internal/v1/chat/stream 触发，不能只测内部函数。
11. 输出完成项、修改文件、测试结果、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
