# AI 助手问答服务改进总规划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于《AI 助手问答服务需求文档》，将 `hm-dianping + learning-agent-service` 从“基础可用但链路不完整”的状态推进到“P0 可联调、P1 可观测、P2 可运营”的产品化 AI 问答服务。

**Architecture:** 维持“前端 -> Java 主入口 -> Python AI 编排核心 -> Java 业务工具 / RAG / 记忆基础设施”的总体架构。优先补齐主聊天链路、标准化错误与 SSE 事件、ToolCall 业务适配、RAG 引用与多轮上下文；将反馈、评测、知识库治理作为后续阶段独立推进，避免一次性过度改造。

**Tech Stack:** Vue 3、Spring Boot、Python/FastAPI、SSE、OpenAI/OpenRouter、Postgres、Redis、Qdrant、业务 REST API / ToolCall。

---

## 1. 规划使用说明

- 这是一份**总规划**，不是直接开工的逐文件实现清单。
- 原因很简单：需求文档覆盖的范围已经横跨 `接入链路 / 路由 / ToolCall / RAG / 记忆 / 反馈 / 评测 / 运营` 多个子系统。
- 如果现在把全部内容写成一个“单次执行计划”，会变得过大，而且会把 P0 和 P2 混在一起，风险很高。
- 因此本规划的目标是：
  - 先锁定系统边界、现状差距、阶段目标和实施顺序。
  - 再把后续执行拆成多个独立可验收的实施计划。

## 2. 当前实现与需求差距

### 2.1 已有基础

- 前端 AI 页面已经具备会话存储、消息展示和调用 `/ai/chat` 的能力。
- Java 已作为前端统一入口，能够把请求转给 Python，也保留了部分本地生活兼容逻辑。
- Python 已具备：
  - 流式聊天接口
  - 通用 workflow runner
  - Tool planner / executor / normalizer
  - RAG 检索链路
  - 会话上下文、记忆、反馈、session 查询等基础模块
- 现有测试已经覆盖：
  - 部分 workflow 行为
  - tool 路由
  - memory 能力
  - SSE 契约

### 2.2 与需求文档的主要差距

#### Gap A：Java 对外契约还不够符合“统一 AI 问答入口”

- 当前 Java `/ai/chat` 仍是同步 JSON 风格接口，不是需求文档强调的 SSE 主接口。
- Java 侧虽然已经收口为 remote-first，但仍保留本地兼容降级逻辑；而文档 11.1 更倾向于“彻底废弃 Java 关键词聊天兜底，直接把远端失败显式抛出”。
- 当前 controller 失败语义仍是 `Result.fail(...)` 的业务包装，不是标准 `500/503 + 错误码`。

#### Gap B：Python 路由已经切到通用 workflow，但“LLM 真正统一调度”还不彻底

- 当前默认主入口已经改到 workflow runner。
- 但实际路由仍混合了：
  - LLM 分类结果
  - 启发式兜底
  - local life slots 补齐
- 这符合“工程上可控”的现实目标，但与需求文档中“坚决不允许正则/关键词分发”的表述仍有差距。
- 更准确的改进方向应该是：
  - **短期保留受控 heuristic guard 作为安全网**
  - **中期把主路由判断逐步迁到 LLM + schema 约束输出**

#### Gap C：ToolCall 链路虽可用，但“标准内部业务工具接口层”还没完全产品化

- Python 工具层已支持本地生活工具映射。
- 但需求文档明确要求 Java 暴露标准 RESTful internal API，例如：
  - `/api/internal/shop/recommend`
  - `/api/internal/shop/detail`
  - `/api/internal/voucher/list`
  - `/api/internal/order/status`
- 当前更像“已有适配能力，但内部接口契约还未系统化”。

#### Gap D：RAG 可用，但“引用展示、低置信度策略、评测闭环”还未形成产品标准

- 当前 workflow 已经有 retrieval / evidence / citation builder。
- 但需求文档要求的以下内容仍需系统化：
  - 引用依据的前端展示规范
  - 检索不足时的低置信回答策略
  - 知识库版本/回滚/更新流程
  - 离线评测集与对比报告

#### Gap E：会话、记忆、反馈模块在后端已具雏形，但前后端产品闭环未打通

- Python 已有 session / memory / feedback 相关接口和测试。
- 但前端目前仍主要聚焦聊天消息展示，没有把以下能力接入产品流程：
  - helpful / unhelpful
  - 错误类型标记
  - 引用来源展开
  - trace/session/turn 调试入口

## 3. 总体改进原则

### 3.1 先做 P0 主链路，不把 P1/P2 混进首轮交付

- 第一优先级不是“把所有文档条目都实现”，而是先把下面这条主链路做到稳定可联调：
  - 前端提问
  - Java 统一入口
  - Python 流式聊天
  - LLM 路由
  - ToolCall 或 RAG
  - `ack -> 中间事件 -> final/error`
  - 前端稳定展示

### 3.2 允许“工程性受控兜底”，但不允许“伪装成功”

- 前端不能再伪造 assistant 成功回答。
- Java 不能再把普通闲聊失败伪装成固定模板。
- Python 可以保留：
  - 低信息量澄清
  - 工具超时降级
  - 检索不足谨慎回答
- 这些是“诚实降级”，不是“假装成功”。

### 3.3 优先标准化契约，再扩能力

- 先统一：
  - 请求字段
  - SSE 事件模型
  - Tool input/output schema
  - 错误码
  - trace/session/turn 透传
- 再继续加：
  - 更多业务工具
  - 更细 RAG 策略
  - 反馈与评测

## 4. 分阶段改进路线

### Phase 0：需求冻结与接口对齐

**目标**

- 把文档中的关键口径改成“可实现、可验收、与当前系统一致”的版本。

**要解决的问题**

- Java 对外到底保留 `/ai/chat` JSON，还是升级成真正 SSE 透传入口。
- Java 本地业务兼容降级是否继续保留。
- “坚决不允许 heuristic” 这条是否放宽成“生产主判定依赖 LLM，heuristic 仅作为 guardrail”。
- ToolCall internal API 契约是否由 Java 统一提供。

**交付物**

- 修订后的需求文档 v1.1
- 对外聊天接口契约
- 对内 business tools 接口清单
- SSE 事件清单
- 错误码清单

**验收**

- 产品、Java、Python 三方对接口口径达成一致。

### Phase 1：P0 主问答链路闭环

**目标**

- 打通“Java -> Python SSE -> LLM 路由 -> Tool/RAG -> final/error”的主链路。

**范围**

- 前端 AI 页面
- Java AI controller / remote client
- Python chat route / workflow / tool / rag / final event

**重点改进**

- Java 新增或改造真正的流式代理接口。
- Python `chat` 路由输出严格符合：
  - `ack`
  - `retrieval_started`
  - `tool_call`
  - `tool_result`
  - `final`
  - `error`
- 前端消费 SSE 并展示流式过程，而不是只等最终 JSON。
- 将当前结构化 metadata 统一到 SSE final payload。

**验收**

- 业务问答、RAG 问答、闲聊、澄清、失败五大场景都能联调通过。

### Phase 2：P0 业务 ToolCall 产品化

**目标**

- 让“业务数据问答”从“能查”提升到“标准工具化、可扩展、可控权限”。

**范围**

- Java internal business APIs
- Python java_business_client / tools / normalizer

**重点改进**

- 抽出标准 internal API：
  - shop recommend
  - shop detail
  - voucher list
  - blog list
  - booking / order status
- 统一工具输入输出 schema。
- 敏感工具增加鉴权、审计、超时与错误码。
- 工具失败时标准化为：
  - no_result
  - timeout
  - permission_denied
  - dependency_unavailable

**验收**

- 常见本地生活问答都通过 ToolCall 返回真实 JSON 证据。

### Phase 3：P0/P1 RAG 可信回答增强

**目标**

- 让专业知识问答不仅“能答”，而且“可引用、可保守、可验证”。

**范围**

- Python RAG orchestrator
- citation builder
- answer composer
- 前端引用展示

**重点改进**

- 明确 citation payload 结构。
- 前端支持展示“引用/依据摘要”。
- evidence 不足时，答案必须切换到低置信模板。
- 为高优先级问题建立小规模验收集。

**验收**

- 知识问答必须能给出来源摘要或引用。
- 无足够证据时不编造。

### Phase 4：P1 会话、记忆、反馈闭环

**目标**

- 把已有后端 memory/feedback 能力变成真实产品闭环。

**范围**

- Python session / memory / feedback routes
- 前端消息反馈入口
- Java trace 透传

**重点改进**

- 前端支持 helpful / unhelpful。
- 反馈支持错误类型分类：
  - 答非所问
  - 引用错误
  - 未召回
  - 工具数据错误
- 前端或运营端能按 `trace_id/session_id/turn_id` 定位问题。
- 补 session state 查询和调试视图。

**验收**

- 每条 final 回答都可关联反馈。
- 研发能基于 trace 复盘链路。

### Phase 5：P1/P2 评测、知识库运营、上线 readiness

**目标**

- 建立“可持续优化”的工程闭环。

**范围**

- 评测集
- 评测脚本
- 知识库更新流程
- 运行文档与监控

**重点改进**

- 建业务问答评测集。
- 建知识问答评测集。
- 固化知识文档切片、入库、版本、回滚流程。
- 增加核心指标：
  - route hit rate
  - tool success rate
  - citation rate
  - clarification rate
  - error rate
  - user feedback helpful rate

**验收**

- 每次重要迭代前后都有评测对比报告。

## 5. 推荐执行顺序

### 5.1 我建议按这条顺序推进

1. `Phase 0` 先做需求与契约冻结  
   原因：当前文档里有几条和现状、甚至和工程可行性不完全一致，必须先定口径。

2. `Phase 1` 做主聊天链路与 SSE 闭环  
   原因：这是所有后续工作的承载面。

3. `Phase 2` 做 ToolCall internal API 产品化  
   原因：业务问答是这个项目的核心价值，不先稳住 tools，后面的体验都不稳。

4. `Phase 3` 做 RAG 可信回答增强  
   原因：等主链路稳定后，再把引用和保守回答做扎实。

5. `Phase 4` 做反馈与记忆闭环  
   原因：这些能力更偏持续优化，需要建立在稳定对话主链之上。

6. `Phase 5` 做评测、知识库运营与上线准备  
   原因：这是上线 readiness，不该倒逼前置主链路设计。

## 6. 当前版本建议优先实现的 P0 范围

### 6.1 必做

- Java 对外流式聊天入口
- Python 流式 chat 主接口稳定化
- SSE 事件契约统一
- 普通闲聊 / 业务问答 / RAG / 澄清 / 错误五类路径打通
- 业务 ToolCall 核心接口最小集
- 前端流式展示与错误展示
- trace/session/turn 全链路透传

### 6.2 暂缓

- 高风险自动交易
- 多智能体协作
- 全量运营后台
- 大规模知识库治理
- 完整评测平台

## 7. 关键风险与决策点

### 风险 1：文档对“禁止 heuristic”要求过硬，可能与当前可用性目标冲突

**建议**

- 口径改为：
  - 主路由以 LLM schema 输出为准
  - heuristic 仅作为低信息量检测、保底防错与安全 guardrail

### 风险 2：Java 是继续做 JSON 包装，还是升级为 SSE 主入口

**建议**

- P0 就升级为 SSE 主入口，否则后续 ack / tool_call / retrieval_started 的体验无法完整落地。

### 风险 3：ToolCall internal API 没有统一标准，后面会持续返工

**建议**

- 在 Phase 1 结束前就产出 internal API 契约草案。

### 风险 4：P1/P2 范围过大，容易拖慢 P0 落地

**建议**

- 先只承诺 P0 联调闭环。
- P1/P2 通过独立计划推进。

## 8. 后续应拆成的独立实施计划

本总规划确认后，建议继续拆成以下 4 份实施计划：

1. `P0-01 Java 与 Python 聊天流式主链路改造计划`
2. `P0-02 业务 ToolCall internal API 与适配层计划`
3. `P0-03 RAG 引用与可信回答增强计划`
4. `P1-01 会话 / 反馈 / 观测闭环计划`

## 9. 本规划对应的代码边界

### 前端

- `frontend/src/pages/AiPage.vue`
- `frontend/src/lib/catalog.js`
- `frontend/src/lib/assistant.js`
- `frontend/src/components/assistant/*`

### Java

- `src/main/java/com/hmdp/controller/AiAssistantController.java`
- `src/main/java/com/hmdp/service/AiAssistantService.java`
- `src/main/java/com/hmdp/ai/remote/*`
- 后续新增 `internal` 业务 API controller / service

### Python

- `learning-agent-service/src/learning_agent_service/api/routes/chat.py`
- `learning-agent-service/src/learning_agent_service/application/use_cases/chat_workflow.py`
- `learning-agent-service/src/learning_agent_service/application/service.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/*`
- `learning-agent-service/src/learning_agent_service/tools/*`
- `learning-agent-service/src/learning_agent_service/rag/*`

## 10. 结论

这份需求文档的方向是对的，但如果直接“一口气照单全收”，会把项目从“问答服务产品化”拉向“大而全 Agent 平台”，风险很高。

更合理的推进方式是：

- 先冻结契约和 P0 边界。
- 先做主聊天链路与 ToolCall / RAG 的可联调闭环。
- 再逐步补记忆、反馈、评测、知识库运营。

这样做可以同时满足：

- 需求文档的大方向
- 当前仓库的真实结构
- 逐阶段可验收的工程节奏

