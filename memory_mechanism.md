# 记忆机制的实现

这份文档总结当前 Python 服务里的记忆层。它不是单一的“聊天历史”，而是分成了感知记忆、短期记忆、长期记忆和实体记忆四层，并且分别走不同的存储和晋升策略。

## 一、整体结构

```text
当前输入
  |
  v
[感知记忆]
  |
  +--> 只保留当前 turn 的原始信号
  |
  v
[短期记忆]
  |
  +--> session / JSON / Redis(默认) / 内存兜底
  |
  v
[长期记忆]
  |
  +--> PostgreSQL 作为 truth source
  +--> Qdrant 只做向量索引 / 检索辅助
  |
  v
[实体记忆]
  |
  +--> PostgreSQL 的结构化实体事实
  +--> 需要时再投影到检索层
```

## 二、四类记忆分别是什么

| 记忆类型 | 作用 | 主要存储 | 备注 |
| --- | --- | --- | --- |
| 感知记忆 | 保存当前 turn 的原始输入和即时信号 | `InMemorySensoryMemoryBuffer` / session 内存 | 不做长期持久化 |
| 短期记忆 | 保留会话窗口、最近话题、摘要、上下文 | session store / short term store，常以 JSON/字典形态流转 | 默认 Redis，必要时可回退内存 |
| 长期记忆 | 保存稳定事实、语义事实、事件、流程性知识 | PostgreSQL 为真值源，Qdrant 为索引 | 可被向量化检索 |
| 实体记忆 | 保存实体级事实，例如当前 topic、最近实体、稳定偏好 | PostgreSQL 为主，必要时做索引投影 | 默认不直接进 Qdrant |

## 三、感知记忆

感知记忆的实现非常轻：

- 只记录当前 turn 的原始 query、slots、intent、输出风格等
- 生命周期只在当前 turn 或极短时间内存在
- 主要是给后面的路由、摘要、抽取提供最新上下文

它的价值是“先抓住眼前发生了什么”，而不是长期保存。

## 四、短期记忆

短期记忆负责“这轮对话还没结束，别忘上下文”。

当前实现里，短期记忆主要落在：

- session store
- short term store
- 会话上下文里的 JSON / 字典结构

会保存的内容通常包括：

- current_topic
- history_summary
- recent_entities
- open_questions
- confirmed_facts
- next_steps
- summary_version

这层记忆的目标不是长期沉淀，而是让同一会话内的回答保持连续性。

## 五、长期记忆

长期记忆保存的是更稳定、更适合复用的事实。当前代码里长期记忆的原则很清楚：

- PostgreSQL 是 truth source
- Qdrant 只做 semantic index
- 不把 Qdrant 当成真值库

长期记忆一般包含：

- semantic memory
- episodic memory
- procedural memory
- 部分 preference 事实

### 长期记忆的晋升条件

不是所有内容都会晋升到长期记忆。`MemoryPromotionGate` 会先过滤一轮。

常见拒绝条件包括：

- 会话还只是澄清阶段
- 用户是 guest
- 置信度太低
- 稳定性太低
- 重要性太低
- 查询本身很含糊

常见阈值大致是：

- confidence >= 0.7
- stability >= 0.7
- importance >= 0.6

如果不满足条件，就会降级为 session-only，或者只进入短期记忆。

### 晋升流程

```text
turn/state
  |
  v
[MemoryPromotionPolicy.evaluate]
  |
  +--> 生成 preference patch
  +--> 生成 profile updates
  +--> 生成 semantic facts
  +--> 生成 outbox events
  |
  v
[MemoryService.persist_session]
  |
  +--> session_store.save
  +--> preference_store.upsert
  +--> profile_projection_store.upsert
  +--> semantic_memory_store.upsert
  +--> async_log / outbox
```

## 六、实体记忆

实体记忆是“围绕一个实体，把当前对话里和它相关的稳定信息收拢起来”。

当前实现里，实体记忆主要来自这些信号：

- `recent_entities`
- `confirmed_facts`
- `current_topic`
- `resolved_entity`
- 明确的偏好信号
- 上下文里的 focus topics

也就是说，它更像是“结构化投影”，不是纯靠一个独立 NER 模型抽取。

### 抽取方式

在代码里，实体相关候选会在 orchestrator 里构造：

- 从 `persistent.recent_entities` 和当前 topic 生成实体候选
- 如果 `reference_resolution.resolved_entity` 存在，会优先使用它
- 再结合 `confirmed_facts`、`open_questions`、`next_steps` 做补充

实体记忆的记录通常会带这些字段：

- `memory_type = ENTITY`
- `scope = USER`
- `source = MODEL_INFERRED`
- `content.current_topic`
- `entities = [topic]`
- `tags = ["entity", "topic"]`

### 实体记忆的存储

实体记忆默认落在 PostgreSQL 一侧的结构化存储里，不是默认进 Qdrant。只有在明确允许实体向量化、且满足向量化门槛时，才会考虑做检索索引。

## 七、短期到长期的衔接

记忆层不是把所有内容都越积越多，而是分层处理：

- 先进入 session 上下文
- 再由规则和门控决定是否晋升
- 能晋升的写到 PostgreSQL
- 能检索的再同步到 Qdrant
- 冲突内容会走 supersede / merge

### 冲突处理

对于偏好和实体类记录，系统会做：

- 归一化 key
- 查找冲突
- 必要时 supersede 老记录
- 保留新记录为 active

这能避免用户偏好被旧数据覆盖，也避免同一个实体出现多份互相打架的事实。

## 八、为什么要分这么多层

因为不同信息的保质期不一样：

- “当前这轮在问什么” 只适合感知/短期
- “用户喜欢什么回答风格” 适合长期
- “某个商家当前营业信息” 更适合 RAG 或工具，而不是长期记忆
- “稳定的人物 / 实体 / 偏好” 适合实体记忆和长期记忆

分层之后，系统既能保持上下文连续，又不会把噪声永久写进长期存储。

