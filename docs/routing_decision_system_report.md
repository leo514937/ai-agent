# Routing Decision System 重构报告

## 目标

本次重构的目标是把请求路由从“分散判断、局部拍脑袋”的模式，收敛成一个可解释、可测试、可观测的 Routing Decision System，并且保留现有的 RAG、Tool、Memory、Session、SSE 能力，只修复它们的边界与优先级。

## 当前实现

- `RoutingDecision` 已经是 workflow 运行时分支的唯一事实源。
- 当前路由采用分层结构：`InputGuard -> Domain Signal Registry -> Semantic Router -> RoutingDecision -> Plan Synthesizer -> Hard Validator -> Execution`。
- `route_decision` / `route_reason` / `direct_response_kind` 仅保留为迁移 trace 或 API 输出字段，不再作为任何运行时分支依据。
- `routing.blocked`、`can_enter_retrieval()`、`can_enter_tool()` 和 `evidence_quality.response_mode` 分别控制硬阻断、检索/工具准入和最终回答模式。
- `retrieval_plan` / `tool_plan` 允许由 synthesizer 补最小可执行计划，classifier 没有产出 plan 不再直接拦死 RAG / Tool。
- 旧 session / cached understanding 只会在 `load_context` 入口经过 `legacy_routing_migration.py` 转成新的 `RoutingDecision`，转换后不会继续沿用旧字段控制流程。

## 问题根因

1. 路由判断分散在多个节点里，`intent_analysis`、`rag_gate`、`rewrite`、`retrieval`、`memory`、`compose_answer` 都在重复做相似判断，导致同一轮请求可能被多次改写路由语义。
2. 输入质量没有统一门禁，空输入、纯标点、重复噪音、低信息输入都可能继续进入理解、改写、检索和工具链。
3. `low_information` / `empty` / `memory_update` 这类转态在后续阶段被误提升成 `direct_answer`，造成澄清、拒答、记忆更新与真实直答混淆。
4. 旧 session / memory 的上下文注入和长期记忆写入缺少路由级开关，容易污染当前问题的 rewrite、retrieval 和 memory promotion。
5. 直答、澄清、检索、工具与 SSE 事件没有统一的决策源，导致“看起来在检索 / 生成”，但实际决策并不一致。

## 改动文件

### 新增

- [`learning-agent-service/src/learning_agent_service/application/routing.py`](../learning-agent-service/src/learning_agent_service/application/routing.py)
- [`learning-agent-service/src/learning_agent_service/application/routing_signals.py`](../learning-agent-service/src/learning_agent_service/application/routing_signals.py)
- [`learning-agent-service/src/learning_agent_service/application/workflow/legacy_routing_migration.py`](../learning-agent-service/src/learning_agent_service/application/workflow/legacy_routing_migration.py)
- [`learning-agent-service/tests/test_routing_decision_matrix.py`](../learning-agent-service/tests/test_routing_decision_matrix.py)
- [`learning-agent-service/tests/test_workflow_rag_gate.py`](../learning-agent-service/tests/test_workflow_rag_gate.py)
- [`learning-agent-service/tests/test_workflow_memory_integration.py`](../learning-agent-service/tests/test_workflow_memory_integration.py)
- [`learning-agent-service/tests/test_legacy_routing_purge.py`](../learning-agent-service/tests/test_legacy_routing_purge.py)

### 修改

- [`learning-agent-service/src/learning_agent_service/domain/contracts.py`](../learning-agent-service/src/learning_agent_service/domain/contracts.py)
- [`learning-agent-service/src/learning_agent_service/domain/__init__.py`](../learning-agent-service/src/learning_agent_service/domain/__init__.py)
- [`learning-agent-service/src/learning_agent_service/application/dependencies.py`](../learning-agent-service/src/learning_agent_service/application/dependencies.py)
- [`learning-agent-service/src/learning_agent_service/application/service.py`](../learning-agent-service/src/learning_agent_service/application/service.py)
- [`learning-agent-service/src/learning_agent_service/application/workflow/runner.py`](../learning-agent-service/src/learning_agent_service/application/workflow/runner.py)
- [`learning-agent-service/src/learning_agent_service/application/workflow/adapters.py`](../learning-agent-service/src/learning_agent_service/application/workflow/adapters.py)
- [`learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py`](../learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py)
- [`learning-agent-service/src/learning_agent_service/application/rag_gate.py`](../learning-agent-service/src/learning_agent_service/application/rag_gate.py)
- [`learning-agent-service/src/learning_agent_service/tools/service.py`](../learning-agent-service/src/learning_agent_service/tools/service.py)
- [`learning-agent-service/tests/test_workflow_memory_integration.py`](../learning-agent-service/tests/test_workflow_memory_integration.py)

## 核心路由规则

### 1. 统一决策对象

新增 `RoutingDecision` 作为单轮请求的统一路由事实源，核心字段包括：

- `input_quality`
- `intent`
- `required_action`
- `should_rewrite_query`
- `should_retrieve`
- `should_call_tool`
- `should_use_memory`
- `should_persist_memory`
- `should_vectorize_memory`
- `should_emit_retrieval_events`
- `missing_slots`
- `resolved_references`
- `route_reason`
- `safeguards_triggered`
- `rewrite_decision`
- `evidence_quality`

后续节点不再各自猜路由，而是读取这个对象。  
当前实现中，旧字段只允许出现在迁移 trace 或 API 输出里，不能作为新的分支条件，也不能继续穿透到 workflow edge、RAG、Tool、Memory 或 SSE 分支。

### 2. 输入质量门禁优先于一切

在进入 intent analysis、rewrite、retrieval、tool 之前，先执行 `build_input_quality()`：

- `empty_input`
- `pure_punctuation`
- `repeated_noise`
- `low_information`
- `ambiguous_reference`
- `incomplete_recommendation`
- `valid_task`

规则落地结果：

- `empty_input` / `pure_punctuation` / `repeated_noise` 不进入理解、改写、检索或工具。
- `low_information` 默认走澄清，只有能从上下文解析成 follow-up/reference 时才继续。
- `ambiguous_reference` 有上下文时先做 reference resolution，否则直接澄清。
- `incomplete_recommendation` 无上下文时优先澄清，不盲目 RAG 或 tool。

### 3. 直答、澄清、记忆更新分离

- greeting / thanks / profile 走 `direct_answer`
- `low_information` 不再自动提升成直答
- `memory_update` 只做记忆路由，不进入商家 RAG
- `session_only` 表达只影响本轮，不写长期记忆
- `clarify` / `reject` / `no_op` 会阻断后续的 RAG 与 tool 分支

### 4. Query Rewrite 受控

重写逻辑现在依赖 `RewriteDecision`：

- `invalid_input` 不 rewrite
- `low_information` 不自由 rewrite
- `ambiguous_reference` 先 resolve reference，再 rewrite
- rewrite 不允许凭空补充实体、商圈、品类、预算、偏好
- `risky_rewrite` 会降低后续检索意愿，必要时转澄清

### 5. Retrieval 二次校验

即使上游说可以检索，retrieval 节点也会再次检查：

- `routing.blocked = false`
- `RoutingDecision.should_retrieve`
- `RoutingDecision.required_action in {rag_retrieval, rag_plus_tool}`
- `input_quality.is_valid`
- `input_quality.score >= threshold`
- `normalized_query` / `rewritten_query` / `semantic_query` 非空
- intent 允许检索
- 不是 clarification-only / memory_update / tool_only / invalid turn
- `retrieval_plan` 有效

不满足则：

- 不生成 embedding
- 不查 Qdrant
- 不 rerank
- 不发 retrieval SSE

当 classifier 没给 `retrieval_plan` 时，`ensure_retrieval_plan()` 会尝试根据 `RoutingDecision`、上下文和配置化 domain signal 生成最小可执行 plan。只要 plan 可执行，就不应因为“缺 plan”而把有效 RAG 误拦掉。

### 6. Tool 与 RAG 解耦

- `tool_call` 先走工具，不先进入 RAG
- `rag_retrieval` 只走 RAG
- `rag_plus_tool` 先 RAG 再 tool，顺序由策略控制
- 推荐类只有在确实需要知识证据时才走 RAG
- 工具所需 slot 不足时走澄清，不盲目 RAG 或 tool

当 classifier 没给 `tool_plan` 时，`ensure_tool_plan()` 会尝试根据 `RoutingDecision`、上下文和 domain signal registry 生成最小可执行 tool plan。若依旧无法满足 slot 约束，则转澄清，而不是退回默认知识路由。

### 7. Memory 注入与长期写入受路由控制

- invalid / low-information / pure punctuation 不写长期记忆
- clarification-only / reject / no_op 不写长期记忆
- session-only constraint 不写长期记忆
- `memory_update` 只更新记忆，不触发商家 RAG
- memory retrieval / promotion 读取 `RoutingDecision`
- 不相关 memory 不注入 prompt

### 8. Evidence Pack 质量门禁

新增证据质量判断，避免低质量证据硬答：

- `evidence_count`
- `top_score`
- `score_gap`
- `topic_consistency`
- `entity_consistency`
- `city/area/category consistency`
- `required_roles coverage`
- `citation availability`
- `stale/deprecated evidence`

当前实现里，`evidence_quality.response_mode` 会直接影响 `compose_answer`：

- `EMPTY` -> 不允许 grounded answer，只返回 `no_answer_with_reason` / clarification
- `WEAK` -> 只能生成 weak answer，必须说明依据不足
- `grounded` -> 才允许 grounded answer

低质量证据会降级，不再强行给出强回答。

### 9. SSE 与真实路由一致

只有真正进入 retrieval / tool / understanding 才发对应 SSE 事件。  
无效输入、澄清-only、memory_update、tool-only 不再伪装成检索/向量化流程。

## 当前真实路由链路

1. `load_context` 先写入 `RoutingDecision`，必要时仅通过 `legacy_routing_migration.py` 做一次旧数据迁移。
2. `parse_intent_slots` 负责语义分类与 plan 补齐，但不再让旧字段决定分支。
3. `resolve_reference`、`ambiguity_check`、`rag_gate` 会回写 routing，`blocked` 会把后续路径硬停在 `compose_answer`。
4. `route_after_understand` 只按 `routing.required_action` 分流；`rag_retrieval`/`rag_plus_tool` 走 RAG，`tool_call` 走 Tool，`clarify`/`direct_answer`/`memory_update` 走回答或记忆路径。
5. `can_enter_retrieval()` / `ensure_retrieval_plan()` 决定是否真的进入 rewrite / embedding / Qdrant / rerank / evidence pack builder。
6. `can_enter_tool()` / `ensure_tool_plan()` 决定是否真的进入 tool planner / executor。
7. `compose_answer` 读取 `evidence_quality.response_mode` 决定 grounded / weak / no-answer 模式。
8. `persist_session` 读取 `routing.should_persist_memory` 和 `routing.should_vectorize_memory` 控制长期记忆写入。

## 验证结果

已执行验证：

- `python -m compileall learning-agent-service/src/learning_agent_service/application learning-agent-service/src/learning_agent_service/tools learning-agent-service/tests`
- `python -m pytest learning-agent-service/tests/test_routing_decision_matrix.py -q`
- `python -m pytest learning-agent-service/tests/test_workflow_rag_gate.py -q`
- `python -m pytest learning-agent-service/tests/test_workflow_memory_integration.py -q`
- `python -m pytest learning-agent-service/tests/test_sse.py -q`
- `python -m pytest learning-agent-service/tests/rag/test_workflow_routing.py -q`

结果：

- 语法检查通过
- `test_routing_decision_matrix.py`：31 passed，4 个 subtests 通过
- `test_workflow_rag_gate.py`：7 passed
- `test_workflow_memory_integration.py`：1 passed
- `test_sse.py`：8 passed
- `test_workflow_routing.py`：5 passed

当前仅剩一个非功能性警告：

- `PytestConfigWarning: Unknown config option: asyncio_mode`

## 剩余风险

1. 旧字段仍可能出现在 API 响应和历史 trace 中，但不会再参与 workflow 控制流。
2. `local_life` / heuristic 侧仍保留少量 legacy 语义枚举，属于独立兼容层，不属于当前 workflow 主链路。
3. 当前测试矩阵覆盖了最关键的路由分支，但还可以继续补更细的 SSE trace 断言和 memory promotion 回归测试。
4. `asyncio_mode` 的 pytest 配置警告还在，和本次路由重构无关，但后续建议单独清理。
