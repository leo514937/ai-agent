# Context Engineering Local Life P0 Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 闭环本地生活助手的 Context Engineering，让显式实体、指代、RAG 证据、工具调用和最终回答都以同一份 `ExecutionContract` 为准，消除 `shop:5` 污染、泛搜、工具串店和多 facet 模板混乱。

**Architecture:** 这一轮不重建 Qdrant collection，不重构 chunk schema，也不扩展成完整 `AnswerVerifier`。核心策略是把“当前轮要做什么、允许看哪些店、必须调用哪些工具、最终能对用户说什么”收敛成一份轻量、可追踪的 `ExecutionContract`，并让 EntityResolver、RAG、ToolExecutor、ResponseBuilder 共用它。所有对用户可见的输出再经过统一 `AnswerSanitizer`，保证不会从任何出口泄漏 `shop:5`、错误店名或原始英文状态词。

**Tech Stack:** Python 3.x, pytest, pydantic models, existing `learning_agent_service/local_life`, `learning_agent_service/rag`, `learning_agent_service/application`, `learning_agent_service/adapters` modules.

---

## Root Cause

- 第一轮“海底捞火锅(水晶城购物中心店）怎么样？”虽然已经命中 `shop_id=5`，但这份“当前店”只作为弱上下文写入了 session，后续回合没有被正式提升成“本轮执行约束”。
- “这家适合约会吗？” 仍然泛搜 SPA/KTV/美发，说明 RAG 调用时没有被 `candidate_shop_ids=[5]` 收口，或者收口后仍有全局 fallback。
- “INLOVE KTV(水晶城店) 这家现在有券吗？” 会继续回答 `shop:5`，说明显式实体解析没有压过历史 recent_entities / session anchor。
- “有券吗 / 这家现在有券吗” 暴露 `shop:5`，说明最终 answer 出站前没有统一 sanitizer，局部替换只能覆盖一小段路径。
- 多 facet 查询已经不再 `RAG_EMPTY_REFUSED`，但模板、工具结果、证据范围仍混杂，说明 route / plan / response 三层没有共享同一个 contract。

## Non-Goals

- 不重建 Qdrant collection。
- 不修改 chunk schema。
- 不引入完整 AnswerVerifier。
- 不把这次问题扩展成全量 RAG 重构。

## File Map

- [execution_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/execution_contract.py)：新增每轮执行契约。
- [entity_resolver.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py)：新增显式实体 / 指代 / session anchor 的解析器。
- [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)：组装 contract、调用 RAG/Tool/Response、回写 session。
- [answer_sanitizer.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/answer_sanitizer.py)：统一出站字符串净化。
- [context_arbitration.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/context_arbitration.py)：P1 续接的上下文仲裁器。
- [evidence_scope_guard.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/evidence_scope_guard.py)：P1 证据范围守卫。
- [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py)：按 required_facets 选模板并做最终出站。
- [local_life_retrieval.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py)：RAG 硬过滤 candidate_shop_ids。
- [java_business.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/adapters/java_business.py)：coupon / open_status 工具必须带 shop_id。
- [contracts.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/contracts.py)：session 侧增加结构化 anchor / pending 续接字段。
- [models.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/memory/models.py)：如果 session store 读取的是 memory 模型，同步补齐字段。
- [routing.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing.py)：工具计划、证据验证、最终路由收口。
- [routing_signals.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing_signals.py)：如需把 pending user need 的恢复信号前置，也在这里接入。
- [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py)：P0 主测试文件。
- [test_p0_routing_review.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_routing_review.py)：P0 路由/证据/工具回归文件。

## Contract Shape

`ExecutionContract` 需要至少包含这些字段，并作为单轮推理的唯一约束对象：

```python
ExecutionContract(
    raw_query=...,
    resolved_query=...,
    intent=...,
    resolved_shop_id=...,
    resolved_shop_name=...,
    candidate_shop_ids=...,
    required_facets=...,
    execute_rag=...,
    execute_tools=...,
    city=...,
    area=...,
    category=...,
    shop_type_id=...,
    price_max=...,
    scene_keywords=...,
    negative_categories=...,
    clarification_action=...,
    forbid_global_fallback=...,
    reason=...,
)
```

解析优先级必须固定为：

1. 当前 query 显式实体
2. page_context
3. pending_user_need
4. recent_entities
5. session memory
6. long-term profile

如果当前 query 显式实体已经识别出 `INLOVE KTV(水晶城店)`，就不能继续沿用 `shop_id=5` 的海底捞历史锚点。

---

### Task 1: Introduce `ExecutionContract` and `EntityResolver`

**Files:**
- Create: [execution_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/execution_contract.py)
- Create: [entity_resolver.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py)
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)
- Modify: [schemas.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/schemas.py)

- [x] **Step 1: Write the failing tests**

在 [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py) 里先写 4 个最小测试：

1. 显式实体优先于历史 `recent_entities`
2. “这家 / 它 / 刚才那家 / 有券吗” 在有上下文时回指当前店
3. 纯指代无上下文时返回 `reference_clarify`
4. 当前 query 显式 `INLOVE KTV(水晶城店)` 时绝不沿用 `shop_id=5`

期待断言：

- `resolved_shop_name == "INLOVE KTV(水晶城店)"`
- `resolved_shop_id != 5`
- `clarification_action == "reference_clarify"`（无上下文时）
- `candidate_shop_ids` 只从当前 query / page_context / session anchor 产生

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: fail，因为 `ExecutionContract` 和 `EntityResolver` 还不存在，或者解析仍沿用旧的 session 逻辑。

- [x] **Step 3: Implement the minimal contract and resolver**

实现要求：

- `ExecutionContract` 只负责描述“这一轮应该怎么做”，不要把业务逻辑塞进去。
- `EntityResolver.resolve(...)` 需要返回：
  - 显式实体来源 `source="query"` / `source="page_context"` / `source="session"` / `source="pronoun"`
  - `resolved_shop_id`、`resolved_shop_name`
  - `candidate_shop_ids`
  - `forbid_global_fallback`
  - `clarification_action`
- 明确禁止把 `recent_entities` 当成比显式实体更高的优先级。
- 如果 query 里已经明确出现一个新商家，则必须覆盖旧商家锚点。

- [x] **Step 4: Wire the contract into `subgraph.py`**

在 [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py) 里应在理解 / slot extraction / user_need 之后立刻组装 `ExecutionContract`，然后把它传给后续 RAG / Tool / Response 节点。
`LocalLifeTurnState` 需要额外带上一个 `execution_contract` 字段，方便后面节点直接读取，不要再各自从 session / raw query 里重复猜。

- [x] **Step 5: Re-run the contract test**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: 4 个解析测试全部通过。

---

### Task 2: Persist first-round selected shop into session

**Files:**
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)
- Modify: [contracts.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/contracts.py)
- Modify: [models.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/memory/models.py)

- [x] **Step 1: Write the session persistence regression test**

在 [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py) 补一个两轮对话用例：

1. 第一轮命中海底捞 `shop_id=5`
2. 第二轮输入“这家适合约会吗？”

期望：

- `session.current_shop` 保留为海底捞可读名
- 结构化锚点里写入：
  - `shop_id`
  - `shop_name`
  - `source`
  - `confidence`
  - `turn_id`
- `recent_entities` 和 `last_candidates` 被一起写回 session

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: fail，因为 session 里还没有结构化 shop anchor。

- [x] **Step 3: Implement the session write-through**

落点建议：

- `recent_entities`：写当前回合明确提到的商家名 / 别名 / 归一化名。
- `last_candidates`：写候选商家列表，保留 `shop_id`、`shop_name`、`source`、`confidence`、`turn_id`。
- `current_shop`：继续保留可读字符串，供现有模板兼容。
- 结构化锚点：新增 `current_shop_anchor` 或等价字段，存完整对象。

不要直接把现有所有 `current_shop` 字符串依赖一次性改成 dict，先兼容旧代码，再逐步收口。

- [x] **Step 4: Re-run the persistence test**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: 第一轮锚点能稳定写入，第二轮能稳定读回。

---

### Task 3: Make RAG consume `candidate_shop_ids` as a hard scope

**Files:**
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)
- Modify: [local_life_retrieval.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py)
- Modify: [evidence_pack.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py)

- [x] **Step 1: Write the retrieval scope test**

在 [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py) 写 2 个检验：

1. “这家适合约会吗？” 在上一轮海底捞后，只能返回 `shop_id=5`
2. `candidate_shop_ids=[5]` 时，RAG evidence 里不能出现 SPA / KTV / 美发

期望：

- `contract.candidate_shop_ids == [5]`
- `retrieve_local_life_evidence(..., candidate_shop_ids=[5])`
- 返回 evidence 的 `shop_id` 只能是 5
- 如果过滤后没有证据，且 `forbid_global_fallback=True`，不能 fallback 到全局检索

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: fail，因为目前 caller / retriever / evidence pack 还没有统一硬过滤。

- [x] **Step 3: Implement hard scope filtering**

要求：

- [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py) 调 `retrieve_local_life_evidence(...)` 时必须传 `candidate_shop_ids=contract.candidate_shop_ids`
- [local_life_retrieval.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py) 在 recall / group / pack 三层都做一次最终过滤
- [evidence_pack.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py) 在最终对外证据包装时再做一次范围守卫
- 如果 `forbid_global_fallback=True`，过滤后为空就直接返回空 evidence pack，不允许绕回全局候选

- [x] **Step 4: Re-run the retrieval test**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: 约会回问不再泛搜 SPA / KTV / 美发。

---

### Task 4: Force tools to consume `resolved_shop_id`

**Files:**
- Modify: [routing.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing.py)
- Modify: [routing_signals.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing_signals.py)
- Modify: [java_business.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/adapters/java_business.py)
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)

- [x] **Step 1: Write the tool routing regression test**

在 [test_p0_routing_review.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_routing_review.py) 写 2 个测试：

1. 先问海底捞，再问“INLOVE KTV(水晶城店) 这家现在有券吗？” 时，`tool_args.shop_id` 不能是 5
2. 先问海底捞，再问“有券吗” 时，coupon 工具必须拿到 `shop_id=5`

期望：

- 显式实体 query 的 `source == "query"`
- `resolved_shop_name == "INLOVE KTV(水晶城店)"`
- `resolved_shop_id != 5`
- `coupon/open_status/queue_status` 工具没有 shop_id 时必须 `reference_clarify`，不能盲调

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: fail，因为当前工具计划和执行还会从旧 session / fallback 里借店。

- [x] **Step 3: Implement tool argument enforcement**

要求：

- `ToolPlanner` / `ToolExecutor` 生成的 `shop_id` 只能来自 `ExecutionContract.resolved_shop_id`
- `JavaBusinessClient.get_coupon_list(shop_id)`、`check_open_status(shop)` 必须从 contract 传入明确 shop
- 如果 `resolved_shop_id` 缺失，直接进入 `reference_clarify`
- 不允许 coupon / open_status 在缺少 shop 时自动猜一个候选商家

- [x] **Step 4: Re-run the routing test**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: 明确实体会覆盖历史海底捞，指代查券会稳定命中海底捞，缺 shop 时会转澄清。

---

### Task 5: Add a unified `AnswerSanitizer`

**Files:**
- Create: [answer_sanitizer.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/answer_sanitizer.py)
- Modify: [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py)
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)

- [x] **Step 1: Write the sanitizer regression test**

在 [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py) 增加字符串净化测试：

- 输入 `shop:5` / `shop_id=5` 需要输出海底捞火锅(水晶城购物中心店）
- 找不到店名时要回退成 `这家店`
- `open` -> `营业中`
- `closed` -> `未营业`
- `0.49000000000000005` -> `0.5`

期望是最终用户可见的 answer / summary / hint / suggestion 都经过同一层净化。

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: fail，因为目前只有局部替换，没有统一出站 sanitize。

- [x] **Step 3: Implement the sanitizer and apply it once at the final egress**

要求：

- sanitizer 只做输出归一化，不改变事实逻辑
- 优先在 [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py) 的最终 bundle 生成前统一调用
- 如果 [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py) 还有额外直接对用户发出的文本，也必须走同一个 sanitizer
- 不要只在 `_build_coupon_environment_answer` 里做局部替换

建议的统一接口：

```python
sanitize_local_life_output(text_or_bundle)
```

或者等价的 `sanitize_answer_text(...)` + `sanitize_response_bundle(...)`

- [x] **Step 4: Re-run the sanitizer test**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: `shop:5` 不再裸露在最终可见文本里。

---

### Task 6: Add `ContextArbitration` and `pending_user_need` continuation

**Files:**
- Create: [context_arbitration.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/context_arbitration.py)
- Modify: [contracts.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/contracts.py)
- Modify: [models.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/memory/models.py)
- Modify: [subgraph.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/subgraph.py)
- Modify: [routing_signals.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing_signals.py)

- [x] **Step 1: Write the pending need continuation test**

在 [test_p0_context_contract.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_context_contract.py) 新增一条两轮恢复测试：

1. 用户问：“附近有没有人均100以内、适合朋友聚餐的烤肉？”
2. 系统先问位置
3. 用户回答：“北京”

期望：

- 解析后恢复出完整的 pending 需求
- `city == "北京"`
- `category == "烤肉"`
- `price_max == 100`
- `scene_keywords` 包含“朋友聚餐”
- 不允许推荐杭州门店、酒吧、海底捞作为主结果

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: fail，因为 pending_user_need 还没有被当作一等公民恢复。

- [x] **Step 3: Implement ContextArbitration**

优先级必须固定成：

1. 当前 query 显式实体
2. page_context
3. pending_user_need
4. recent_entities
5. session memory
6. long-term profile

要求：

- 当系统追问位置时，要把原始意图和约束写入 `pending_user_need`
- 用户补充“北京”后，要把 `city` 合并回原需求，而不是覆盖掉 `category/price_max/scene_keywords`
- `ContextArbitration` 只做仲裁，不做检索和生成

- [x] **Step 4: Re-run the continuation test**

Run:

```bash
pytest tests/local_life/test_p0_context_contract.py -v
```

Expected: pending need 续接成功。

---

### Task 7: Make `response_builder` select templates by `required_facets`

**Files:**
- Modify: [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py)
- Modify: [schemas.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/schemas.py)
- Modify: [routing.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing.py)

- [x] **Step 1: Write the facet-template regression test**

在 [test_p0_routing_review.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_routing_review.py) 覆盖这些模板规则：

- `coupon` -> 券信息
- `open_status` -> 营业状态
- `scene_fit` -> 场景适配
- `recommendation` -> 推荐结果
- `shop_detail` -> 商家概览

期望：

- 多 facet 查询不会把所有旧模板拼在一起
- 只会输出当前 `required_facets` 对应的栏目
- 工具结果和推荐结果不会互相覆盖

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: fail，因为 `required_facets` 还没有真正驱动模板选择。

- [x] **Step 3: Implement facet-driven rendering**

要求：

- [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py) 读取 `required_facets`
- 只渲染被要求的栏目
- 对同一 shop 的多来源信息进行收口，不允许重复拼接“推荐 + 工具 + 模型摘要 + 原始证据”导致读感混乱
- 如果 `answer_plan` 和 tool result 同时存在，以 contract 里 `required_facets` 为准决定展示顺序

- [x] **Step 4: Re-run the routing review test**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: 多 facet 输出稳定，模板不再混乱。

---

### Task 8: Add `EvidenceScopeGuard`

**Files:**
- Create: [evidence_scope_guard.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/evidence_scope_guard.py)
- Modify: [routing.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing.py)
- Modify: [evidence_pack.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py)

- [x] **Step 1: Write the evidence scope regression test**

在 [test_p0_routing_review.py](file:///d:/javacode/hm-dianping/learning-agent-service/tests/local_life/test_p0_routing_review.py) 加一条断言：

- 当 `contract.candidate_shop_ids` 非空时，最终 evidence 中不允许出现其他 `shop_id`
- 过滤后空集时，不允许 fallback 到全局证据池

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: fail，因为最终 evidence 还没有统一的范围守卫。

- [x] **Step 3: Implement the guard**

要求：

- guard 要在 `response_builder` 之前执行
- 若 `candidate_shop_ids` 非空，则最终 evidence / citations / candidates 的 `shop_id` 只能属于该集合
- 若违规则丢弃，不做全局 fallback

- [x] **Step 4: Re-run the evidence scope test**

Run:

```bash
pytest tests/local_life/test_p0_routing_review.py -v
```

Expected: 范围外证据不会再进入最终答案。

---

## P0 Acceptance Test Matrix

### Test 1
先问“海底捞火锅(水晶城购物中心店）怎么样？”，再问“这家适合约会吗？”

期望：

- `session.current_shop_anchor.shop_id = 5`
- `contract.candidate_shop_ids = [5]`
- RAG evidence 只包含 `shop_id=5`
- 不允许出现 SPA / KTV / 美发

### Test 2
先问海底捞，再问“INLOVE KTV(水晶城店) 这家现在有券吗？”

期望：

- `explicit entity source = query`
- `resolved_shop_name = INLOVE KTV(水晶城店)`
- `resolved_shop_id != 5`
- `tool_args.shop_id != 5`
- 不允许回答 `shop:5`

### Test 3
先问海底捞，再问“有券吗”

期望：

- `resolved_shop_id = 5`
- `execute_tools` 包含 `coupon`
- final answer 不出现 `shop:5`
- 如果实时无券但知识库有券，要说明“实时未查到，可参考券存在，需以实时接口为准”

### Test 4
新会话直接问“这家适合约会吗？”

期望：

- `reference_clarify`
- `execute_rag = false`
- 不允许泛搜 SPA / KTV / 美发

### Test 5
“附近有没有适合约会、现在营业、最好有券的火锅？”

期望：

- `execute_rag = true`
- `execute_tools` 包含 `open_status` 和 `coupon`
- `category = 火锅`
- `scene_keywords` 包含 `约会`
- final answer 不出现 `shop:5`

### Test 6
“附近有没有人均100以内、适合朋友聚餐的烤肉？”
系统问位置；用户回答“北京”

期望：

- 恢复 `pending_user_need`
- `city = 北京`
- `category = 烤肉`
- `price_max = 100`
- `scene_keywords` 包含 `朋友聚餐`
- 不允许推荐杭州门店、酒吧、海底捞作为主结果

---

## P1 Follow-up Work

### Task 9: Harden context arbitration across page_context / session / profile

**Files:**
- Create: [context_arbitration.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/context_arbitration.py)
- Modify: [routing_signals.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing_signals.py)
- Modify: [contracts.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/contracts.py)

**What it should do:**

- 把当前 query 显式实体、page_context、pending_user_need、recent_entities、session memory、long-term profile 的来源分层。
- 让同义词、别名、分店、区域、模糊匹配都走同一条仲裁路径。
- 为 P2 的 exact / normalized / alias / branch / area / fuzzy match 预留输出字段。

### Task 10: Improve retrieval quality after P0 is stable

**Files:**
- Modify: [local_life_retrieval.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py)
- Modify: [query_rewriter.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/query_rewriter.py)
- Modify: [ranker.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/ranker.py)

**What it should do:**

- facet query rewrite
- category-aware retrieval
- scene-aware rerank
- parent-child aggregation

### Task 11: Unify business metrics provenance

**Files:**
- Modify: [response_builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py)
- Modify: [java_business.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/adapters/java_business.py)
- Modify: [local_life_retrieval.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/rag/local_life_retrieval.py)

**What it should do:**

- 人均、营业状态、券信息、图谱证据分别标注来源。
- 不把 RAG 人均、业务接口人均、演示数据人均混成一个口径。

---

## Test Commands

按这个顺序跑：

```bash
pytest tests/local_life/test_p0_context_contract.py -v
pytest tests/local_life/test_p0_routing_review.py -v
pytest tests/test_streaming_behavior.py tests/test_chat_workflow.py tests/test_sse.py tests/test_api_contracts.py tests/rag/test_hybrid_retrieval.py -v
```

判定标准：

- `test_p0_context_contract.py` 覆盖 entity resolution / session persistence / RAG scope / sanitizer / pending need。
- `test_p0_routing_review.py` 覆盖 tool shop_id / response template / evidence scope。
- 其余回归集确保聊天流、SSE、API 契约和混合检索没有被 P0 修改破坏。

---

## Self-Review Checklist

- [x] 每个 P0 需求都对应到了具体文件。
- [x] 没有提议重建 Qdrant collection。
- [x] 没有引入完整 AnswerVerifier。
- [x] `candidate_shop_ids`、`resolved_shop_id`、`current_shop`、`recent_entities`、`last_candidates` 的职责边界清晰。
- [x] `AnswerSanitizer` 是唯一出站净化层，不只修一个局部函数。
- [x] 新测试能覆盖“海底捞 -> 这家适合约会吗”、“海底捞 -> INLOVE KTV 这家现在有券吗”、“无上下文指代”、“pending_user_need 恢复”。
