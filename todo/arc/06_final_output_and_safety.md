# 最终输出与安全收尾分析

> 目标：解释为什么 `final_answer` 之后还要走一层安全审查，以及最终 SSE / state 是怎么出来的。

> 实测提示：在当前 chat E2E 里，稳定命中的大多数 case 都是 `ack -> final`，并没有频繁触发 `final_safety_fallback`。所以本页更适合把“安全收尾的结构”与“实际最终输出长什么样”分开看。

## 适用节点

- `final_answer`
- `final_answer_safety`
- `final_safety_fallback`
- `repair_answer`
- `final_with_limitations`
- `response_builder`
- `persist_session`
- `emit_final`

## 主流程

```text
final_answer
  -> final_answer_safety
       -> final_safety_fallback
       -> response_builder
  -> persist_session
  -> emit_final
  -> END
```

## 每个节点做什么

### `final_answer`

- 确保 `turn.final_answer` 不是空的。
- 如果前面没有产出最终答案，它会调用 compose 逻辑补齐。
- 对 plan_execute 路径，它也会把结果收口到最终答案上。

### `final_answer_safety`

- 对最终答案做最后一轮安全校验。
- 会根据：
  - `answer_contract`
  - `ranked_candidates`
  - `evidence_claims`
  - `tool_results`
  - `review_report`
  - `shop_lookup`
  来判断是否要修复、降级或阻断。

### `final_safety_fallback`

- 当安全审查判定 blocked 或最终答案为空时，提供兜底文本。

### `repair_answer`

- 修复后回到 `final_answer`，再走一次收尾。

### `final_with_limitations`

- 输出“有条件的答案”，并把限制写清楚。

### `response_builder`

- 把 `turn.final_answer`、对话状态、上下文记忆、比较态等整理进 persistent state。
- 也负责把 dialog state machine 的状态更新回去。

### `persist_session`

- 持久化这轮会话。

### `emit_final`

- 发出最终 SSE 事件。
- 这通常就是外部调用方真正消费到的最后一段数据。

## 实测 case

### `D1-1` 单店点评

```text
海底捞水晶城店怎么样？
```

实测结果：

- `answer_style = single_shop_review`
- `route_gate.branch = rag`
- `events = ack -> final`
- `final_answer` 里是“总体结论 / 核心优点 / 可能不足 / 适合场景 / 到店建议”这种结构

### `D5-1` 附近推荐

```text
附近有没有推荐的餐厅？
```

实测结果：

- `answer_style = multi_shop_recommendation`
- `route_gate.branch = recommendation`
- `events = ack -> final`
- 最终答案会把推荐理由和场景一起收口

### `D14-1` 复合 facet

```text
海底捞水晶城店环境怎么样，有券吗，离我多远？
```

实测结果：

- `answer_style = facet_multi`
- `route_gate.branch = rag_plus_tool`
- `events = ack -> final`
- 这类 case 会把多个 facet 合到一个最终回复里，但也可能因为证据不足而保守收口

### `D13-1` 多轮券查询

```text
海底捞水晶城店怎么样？
有券吗？
```

实测结果：

- 第二轮沿用了上一轮店铺上下文
- `answer_style = coupon_only`
- 最终还是以单店的券信息收口

## 典型 case

### Case 1: 正常安全通过

```text
final_answer -> final_answer_safety -> response_builder -> persist_session -> emit_final
```

### Case 2: 最终审查阻断

```text
final_answer -> final_answer_safety -> final_safety_fallback -> response_builder -> persist_session -> emit_final
```

### Case 3: 需要修复

```text
final_answer -> final_answer_safety -> repair_answer -> final_answer
```

### Case 4: 只能给有限答案

```text
complex_review -> final_with_limitations -> final_answer
```

## 为什么这里重要

很多人会只盯着“前面查到了什么”，但真正影响用户看到什么的是最后这条链：

1. 前面产出的答案可能还不完整
2. 安全层可能再改一次
3. response_builder 可能再改状态
4. persist_session 才把上下文保存下来
5. emit_final 才是最终流式输出
