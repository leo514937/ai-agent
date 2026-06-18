# 本地生活简单路径分析

> 目标：说明为什么有些本地生活 query 会走“轻量路径”，而不是进入完整的多来源合并链。

> 实测提示：在当前 chat E2E 里，很多“简单问题”更常表现为 `tool` 或 `rag` 后直接收口，而不是显式看到 `direct_executor`。所以这里把“简单路径”理解成“低复杂度、单来源、快速收口”的一组情况。

## 适用节点

- `complexity_router`
- `direct_executor`
- `rule_review`
- `final_answer`

## 主流程

```text
build_source_contract
  -> complexity_router
       -> direct_executor
  -> rule_review
  -> final_answer
```

## 这个路径什么时候出现

当路由认为当前问题已经足够简单，或者不需要跑完整的 workflow 执行链时，就会走这条路。

典型信号：

- 只需要一个简单结论
- 不需要多来源合并
- 不需要复杂计划
- 不需要多轮 source dispatch

## 每个节点做什么

### `complexity_router`

- 决定执行模式。
- 可能输出：
  - `clarify`
  - `simple`
  - `standard`
  - `complex`

如果输出 `simple`，就会进 `direct_executor`。

### `direct_executor`

- 直接构造答案或直接整理成可回答的内容。
- 它绕过了标准的 `select_required_sources` / `source_dispatch`。

### `rule_review`

- 对简单答案做一轮规则检查。
- 结果会被写回 `turn.extra`，然后进入 `final_answer`。

### `final_answer`

- 轻量路径也会经过最终收口。
- 在实测里，最终看到的文本通常是 `open_status_only`、`distance_only`、`coupon_only` 这一类短答案。

## 典型 case

### Case 1: 营业状态

例如：

```text
海底捞水晶城店现在营业吗？
```

实测结果：

```text
route_gate.branch = tool
answer_style = open_status_only
```

### Case 2: 距离查询

例如：

```text
海底捞水晶城店离我多远？
```

实测结果：

```text
route_gate.branch = rag
answer_style = distance_only
```

### Case 3: 券查询继承上下文

例如：

```text
海底捞水晶城店怎么样？
有券吗？
```

实测结果：

```text
route_gate.branch = tool
answer_style = coupon_only
priority_source = session_context
```

## 和标准链的区别

| 维度 | 简单路径 | 标准路径 |
|---|---|---|
| 是否一定显式看到 `direct_executor` | 否 | 不一定 |
| 是否可能只靠单一来源收口 | 是 | 否 |
| 是否走 `select_required_sources` | 通常否 | 是 |
| 是否走 `source_dispatch` | 可能很轻量 | 是 |
| 是否做多来源合并 | 通常否 | 是 |
| 适合场景 | 单店营业、距离、券、简单评价 | 检索 / 工具 / 推荐 / 对比 |
