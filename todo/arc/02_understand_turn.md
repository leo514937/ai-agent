# Understand Turn 子图分析

> 目标：解释 `understand_turn` 子图如何把一句话变成可路由的结构化状态。

> 实测提示：这个子图本身不会直接把答案发给用户，它的价值要从 `routing_decision`、`phase0_trace`、`phase3_trace` 这些字段里看出来。

## 子图节点

- `parse_intent_slots`
- `resolve_reference`
- `ambiguity_check`
- `finalize_understand_turn`

## 子图结构

```text
understand_turn
  -> parse_intent_slots
  -> resolve_reference
  -> ambiguity_check
  -> finalize_understand_turn
  -> END
```

## 这个子图的作用

它不直接回答用户，而是把输入 query 变成后续主图要用的结构化上下文：

- 用户意图
- 相关槽位
- 是否存在引用消解
- 是否有歧义
- 是否需要重写 query
- 是否可以进入本地生活域

## 每个节点做什么

### `parse_intent_slots` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L539))

- 解析意图和槽位。
- 结果会写回 `turn.intent`、`turn.decision`、`turn.slots`、`turn.extra` 等。
- 这一层通常会决定后面是直接回答、继续检索，还是要澄清。

### `resolve_reference` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L903))

- 解析“这家店”“那家”“它”这种引用。
- 会尽量把模糊引用绑定到具体实体。

### `ambiguity_check` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L959))

- 检查当前 query 是否歧义过大。
- 如果歧义太大，后续可能会导向澄清或者拒绝继续检索。

### `finalize_understand_turn` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py#L427))

- 汇总前面几步结果。
- 形成后续顶层路由要读的 state。

## 常见 case

### Case 1: 有明确实体

```text
海底捞怎么样
  -> parse_intent_slots
  -> resolve_reference
  -> ambiguity_check
  -> finalize_understand_turn
```

结果通常是：

- `turn.intent` 可用
- `turn.reference_resolution` 可用
- `turn.retrieval_plan` 或 `turn.routing_decision` 可继续驱动后续分支

### Case 2: 引用已经缓存

如果前面已经有 `understanding_bundle` 或缓存上下文，测试里能看到：

- `resolve_reference` 可能不会再次执行
- `rag_gate` 也可能直接跳过一些重复计算

这类 case 用来避免重复 LLM / 重复推理。

### Case 3: 歧义太强

如果引用和实体都不清楚：

- `ambiguity_check` 之后会留下更明显的澄清信号
- 主图后面更容易走到 `clarification_node`

## 和测试的对应关系

可以重点看这些测试：

- `learning-agent-service/tests/test_workflow_rag_gate.py`
- `learning-agent-service/tests/test_workflow_compiled_subgraphs.py`

里面已经验证了：

- `resolve_reference` 能被跳过
- `rag_gate` 能把低信息请求留在直接回复路径
- 解析结果会写进 `turn.extra`，供后续路由复用

## 实测观察

### `D1-1` 单店评价

输入：

```text
海底捞水晶城店怎么样？
```

实际观察到的理解结果：

- `raw_query` 会先进入理解层
- `intent` 被识别成本地生活查询
- `answer_style = single_shop_review`
- `route_gate.branch = rag`

### `D14-1` 多维度查询

输入：

```text
海底捞水晶城店环境怎么样，有券吗，离我多远？
```

实际观察到的理解结果：

- `intent` 最终会落到更复杂的组合意图
- `required_action = rag_plus_tool`
- `answer_style = facet_multi`
- 这类 query 会把“单店 + 动态 facet”都写进后续 state

### `D13-1` 多轮继承

输入：

```text
海底捞水晶城店怎么样？
有券吗？
```

实际观察到的理解结果：

- 第二轮会继承前一轮的店铺语境
- 后续券查询不再是完全匿名问题
- `priority_source` 会偏向 `session_context`
