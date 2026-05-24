# 路由机制的实现

这份文档总结当前 Python 服务如何把一个请求分到不同链路。核心不是“一个大模型直接自由发挥”，而是先做输入质量判断、语义路由，再由条件边把请求送到 RAG、toolcall、记忆检索或直接回答。

## 一、路由入口在哪

路由主要发生在 `understand_turn` 之后。

```text
load_context
  |
  v
understand_turn
  |
  +--> direct_answer
  +--> clarify
  +--> rag_subgraph
  +--> tool_subgraph
  +--> plan_execute_subgraph
```

如果请求本身不需要复杂处理，可能在更早阶段就被短路到直接回答或澄清。

## 二、先看输入质量

系统会先评估输入质量，避免把噪声请求送进重链路。

常见输入质量类型包括：

- 空输入
- 纯标点
- 重复噪声
- 信息量很低
- 指代不清
- 推荐信息不完整
- 有效任务

这一步的作用是：

- 先挡掉明显无效请求
- 对低信息请求优先走澄清
- 避免检索和工具链路浪费资源

## 三、路由会分到哪些链路

当前主要路由分支是这些：

- `direct_answer`
- `clarify`
- `rag_retrieval`
- `tool_call`
- `rag_plus_tool`
- `memory_update`
- `no_op`
- `reject`

### 1. direct_answer

适合：

- 打招呼
- 简单确认
- 轻量上下文追问
- 不需要检索也不需要工具

### 2. clarify

适合：

- 信息缺失
- 需要补齐 slot
- 指代不明确
- 推荐条件不完整

### 3. rag_retrieval

适合：

- 要知识、要解释、要规则、要依据
- 不需要实时业务动作

### 4. tool_call

适合：

- 要实时状态
- 要业务动作
- 要强依赖外部系统的数据

### 5. rag_plus_tool

适合：

- 既要知识，又要业务动作
- 例如先看商家信息，再看券，再查距离或营业状态

## 四、如果一个请求同时涉及多个链路怎么办

这是最关键的问题。

### 当前做法

当前实现不是把所有链路都并行乱跑，而是通过一个“主路由 + 子图串联”方式处理：

- `memory` 先按需做检索
- `understand_turn` 决定主 action
- 如果是 `rag_plus_tool`，先走 RAG，再决定是否能进入 tool
- `tool_subgraph` 完成后再进入 `compose_answer`
- `memory` 的写回通常在答案之后统一做

也就是说，系统会尽量把“多个能力”压成一个有序路径，而不是让它们互相抢控制权。

### 一个典型例子

```text
用户：帮我推荐一家适合家庭聚餐的店，顺便看看有没有券
  |
  v
[memory retrieval]
  |
  v
[understand_turn]
  |
  v
required_action = rag_plus_tool
  |
  +--> RAG 先找商家和理由
  |
  +--> toolcall 再查券和实时状态
  |
  v
[compose_answer]
```

## 五、记忆检索和路由的关系

记忆检索不是独立主链，而更像一个“前置增强层”。

它会根据 `should_use_memory` 决定：

- 是否参与当前请求
- 是否把历史 topic、recent entities、confirmed facts、open questions 注入上下文

所以在“既要记忆又要 RAG / toolcall”的请求里，记忆通常先于主链路生效。

## 六、当前机制的优点

- 简单直接
- 路由结果可解释
- 对低质量输入有保护
- 支持 `rag_plus_tool` 这类组合路径
- 记忆和主任务解耦，不会互相污染太多

## 七、当前机制的局限

当前路由本质上还是“一个请求选一个主 action”。这会带来一个问题：

- 如果一个请求真的需要多个能力协同，但没有被明确识别成 `rag_plus_tool`
- 或者需要先 RAG 再工具，再补记忆，再二次澄清

就可能出现链路表达不够细的问题。

## 八、是否有更好的解决方案

有，而且会更稳。

### 更好的方案 1：显式任务计划

把路由结果从“单个 action”升级成“任务计划”：

```text
TaskPlan
  - step 1: memory_recall
  - step 2: rag_retrieve
  - step 3: tool_call
  - step 4: compose
```

这样多链路请求就不需要硬塞进一个 `required_action`。

### 更好的方案 2：主链 + 支路

把系统拆成：

- 主链：负责最终答案主干
- 支路：负责记忆、检索、工具调用的补充

例如：

- 记忆检索始终是前置支路
- RAG 和 toolcall 可以按顺序或并行调度
- 最后统一汇总

### 更好的方案 3：冲突时优先澄清

当多个链路都可能正确，但缺少关键 slot 时，优先澄清比强行执行更安全。

这对：

- 预约
- 下单
- 退款
- 高成本推荐

尤其重要。

## 九、推荐的路由原则

- 先挡噪声，再做深路由
- 能直接回答就不要上重链路
- 能澄清就不要猜
- 能先记忆增强，就先增强上下文
- 能用 `rag_plus_tool` 表达的组合任务，不要拆成互相打架的多次请求

