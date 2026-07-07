# 第一层：入口与上下文层 — 架构报告（更新版）

> 当前范围：`local_life_agent/input/`、`semantic/`、`target/`、`session/`、`engine/subgraphs/intake_guard_router.py`、`engine/subgraphs/understanding_subgraph.py`、`engine/subgraphs/state_update_plan.py`
>
> 目标：把“输入校验、轮次恢复、语义理解、引用解析、会话写回”收敛为一层稳定入口，不再承担二层决策或三层回答职责。

---

## 1. 第一层职责边界

第一层负责把用户原始输入变成**可路由、可理解、可持久化**的状态片段。

**负责**
- 输入合法性校验、标准化、硬守卫
- 会话加载 / 会话写回
- 活跃轮次识别（是否在回复上一轮澄清）
- 语义解析：`SemanticFrame`
- 上下文恢复：`ContextualizedTurn`、`FocusContext`
- 引用信号识别：`target/context_recovery.py`

**不负责**
- 工具执行
- 目标决策与证据规划
- 最终自然语言回答
- 事实验证 / 改写

---

## 2. 第一层数据流

```text
raw_text
  → intake_guard_router
  → understanding_subgraph
      → semantic/intent_parser.py
      → semantic/slot_extractor.py
      → target/context_recovery.py
      → target/reference_resolver.py / focus_resolver.py
  → state_update_plan
  → session/store.py
```

当前第一层的核心输出不是“答案”，而是这些结构化中间态：

- `top_intent`
- `guard_result`
- `active_turn`
- `semantic_frame`
- `contextualized_turn`
- `focus_context`
- `pending_clarification`
- `session_state`

---

## 3. 入口守卫：`intake_guard_router`

文件：[`engine/subgraphs/intake_guard_router.py`](../local_life_agent/engine/subgraphs/intake_guard_router.py)

它负责四件事：
1. 接收原始输入
2. 调用 `input/validator.py` 做基础校验
3. 调用 `input/normalizer.py` 做文本归一化
4. 调用 `input/hard_guard.py` 做安全/能力/闲聊级别的第一道拦截

当前实现的关键点：
- `hard_guard` 只做 allow/deny，不决定业务路由权威
- 无 token / 匿名上下文不在这里处理
- 失败时直接落到预置响应或 `invalid`

---

## 4. 活跃轮次：`active_turn_resolver`

文件：[`engine/subgraphs/active_turn_resolver.py`](../local_life_agent/engine/subgraphs/active_turn_resolver.py)

它判断本轮输入是不是在回答上一轮澄清：
- 数字/序数
- 指示词（这家、那个、第二个）
- 取消 / 改口 / 超范围

它的输出是“是否延续上一轮上下文”的信号，不负责实体最终落点。

---

## 5. 语义理解：`understanding_subgraph`

文件：[`engine/subgraphs/understanding_subgraph.py`](../local_life_agent/engine/subgraphs/understanding_subgraph.py)

当前理解链路是：

1. `semantic/intent_parser.py`
2. `semantic/slot_extractor.py`
3. `target/context_recovery.py`
4. `target/reference_resolver.py`
5. `target/focus_resolver.py`

这层的输出对象主要是：
- `SemanticFrame`
- `ContextualizedTurn`（追踪用）
- `FocusContext`（追踪用）
- `PendingClarification`

### 重要边界

- `context_recovery` 只保留引用信号，不再承担最终实体解析权威
- `focus_resolver` 负责把“这家 / 第一个 / 上一条推荐”收敛成可追踪上下文
- 第一层不做工具选择，不做证据规划

---

## 6. 会话状态：`session/store.py`

当前会话层已经抽成 `SessionStore` 协议，并提供内存 / Redis 实现。

核心职责：
- `load(session_id)` / `save(session_id, state)` / `delete(session_id)`
- 按分区 TTL 管理会话片段
- 保持第一层和后续层共享同一份会话状态

相关辅助：
- `session/policy.py`：分区与 TTL 策略
- `session/context_summary.py`：会话摘要

---

## 7. 状态写回：`state_update_plan`

文件：[`engine/subgraphs/state_update_plan.py`](../local_life_agent/engine/subgraphs/state_update_plan.py)

这是第一层最后的写回节点，负责把本轮新增状态合并回 `SessionState`，避免上游节点直接修改存储层。

写回重点：
- `current_shop`
- `comparison_targets`
- `pending_clarification`
- `focus_context`
- `semantic_frame`
- `last_route` / `last_error` / `trace` 相关字段

---

## 8. 第一层与第二层的边界

| 项目 | 第一层 | 第二层 |
|---|---|---|
| 语义解析 | 产出 `SemanticFrame` | 消费 `SemanticFrame` |
| 引用恢复 | 识别“这家/第二个” | 解析成最终目标集 |
| 会话 | 读写 `SessionState` | 读取上下文，不直接改写入口状态 |
| 决策 | 只做输入级判断 | 决定 workflow / plan / tool |

---

## 9. 结论

第一层现在是“**输入净化 + 上下文恢复 + 语义帧产出 + 会话写回**”层。

如果它产出的不是稳定中间态，就不要让二层和三层去补洞。
