# 整体架构图

这份文档把 Python 服务的整体链路串起来，重点说明 `LangGraph` 在哪里发挥作用，以及各条链路之间是怎么连接和路由的。

## 一、LangGraph 的作用

`LangGraph` 在这里不是业务逻辑本身，而是“编排层”。

它负责：

- 把各个节点串成图
- 按条件边决定下一步走哪条链路
- 支持子图式组织
- 在主流程里统一调度 RAG、toolcall、memory、compose、persist

如果环境里没有 `langgraph`，系统还能退回到顺序 runner，说明它是“优先使用的编排方式”，不是唯一依赖。

## 二、整体链路图

```text
HTTP /internal/v1/chat/stream
  |
  v
[WorkflowLearningAgentService]
  |
  v
[Workflow Runner]
  |
  +--> LangGraphWorkflowRunner
  |
  +--> SequentialWorkflowRunner(兜底)
  |
  v
load_context
  |
  v
memory.retrieve_for_state
  |
  v
understand_turn
  |
  +--> direct_answer
  +--> clarify
  +--> rag_subgraph
  |        |
  |        v
  |     tool_subgraph
  |
  +--> tool_subgraph
  |
  +--> plan_execute_subgraph
  |
  v
compose_answer
  |
  v
memory.promote_from_state
  |
  v
persist_session
  |
  v
emit_final
  |
  v
SSE 输出
```

## 三、各链路之间的关系

### 1. memory 是前置增强层

它先把：

- session 上下文
- recent_entities
- confirmed_facts
- history_summary

注入到当前 turn。

这会影响后续路由和回答内容。

### 2. understand_turn 是路由中枢

它负责把输入变成结构化路由决策，包括：

- 是否直接回答
- 是否澄清
- 是否检索
- 是否调用工具
- 是否更新记忆

### 3. RAG 和 toolcall 是可串联的能力链

```text
understand_turn
  |
  +--> rag_subgraph
          |
          +--> tool_subgraph
```

这条串联只在需要时发生。它表达的是：

- 先拿知识依据
- 再拿实时动作 / 业务状态

### 4. compose_answer 是统一出口

无论前面走了哪条链，最后都要回到 `compose_answer`：

- 汇总证据
- 汇总工具结果
- 组织自然语言回答
- 给引用和说明留位置

### 5. persist_session 是统一落点

回答生成后，再统一做：

- session 保存
- 长期记忆晋升
- preference / profile 更新
- semantic fact 同步
- outbox 写入

这能保证“先答复，再沉淀”。

## 四、一个更完整的视角

```text
               +----------------------+
               |      routing         |
               |  输入质量 + 意图识别   |
               +----------+-----------+
                          |
          +---------------+----------------+
          |               |                |
          v               v                v
     direct_answer     rag/tool         clarify/reject
          |               |
          |               v
          |        +--------------+
          |        |  memory side  |
          |        |  retrieval    |
          |        +------+-------+
          |               |
          v               v
               +----------------------+
               |   answer composer    |
               +----------+-----------+
                          |
                          v
               +----------------------+
               |  session persist +   |
               |  memory promotion    |
               +----------+-----------+
                          |
                          v
                       final SSE
```

## 五、为什么这个结构好用

- 职责分离清楚
- 路由可解释
- RAG、toolcall、memory 可以独立演进
- 统一在 `compose_answer` 汇总，输出格式更稳定
- `persist_session` 把短期状态和长期沉淀分开，避免互相污染

## 六、当前最关键的设计点

当前系统真正的核心不是某一个模型，而是这三件事：

- 路由判断
- 子图编排
- 统一落盘与记忆晋升

也就是说，`LangGraph` 负责把“什么时候走哪条链”这件事制度化，而不是让每个节点各自乱跳。

