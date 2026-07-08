请你严格基于当前仓库真实代码，调研“第一层：入口与上下文层”的实际实现情况，并输出可执行的解决方案文档到 `todo/first_layer/` 目录。

重要要求：

1. 只做代码调研和方案文档，不要直接修改业务代码。
2. 不要根据已有文档或经验脑补，必须以当前仓库实际代码为准。
3. 如果文档描述和真实代码不一致，以真实代码为准，并在报告中指出偏差。
4. 不要扩大到第二层规划、工具执行、回答生成，除非第一层与它们存在明确调用边界问题。
5. 最终请把分析和解决方案放到 `todo/first_layer/` 下，可以新建一个或多个 markdown 文件。
6. 如果 `todo/first_layer/` 不存在，请创建该目录。
7. 输出时必须包含你实际扫描过的文件、函数、调用链和关键证据。
8. 不要声称问题已经修复，只能说“已形成解决方案文档”。

本次调研范围：

重点扫描以下模块及其直接依赖：

* `local_life_agent/engine/subgraphs/intake_guard_router.py`
* `local_life_agent/engine/subgraphs/merge_clarification.py`
* `local_life_agent/engine/subgraphs/understanding_subgraph.py`
* `local_life_agent/engine/subgraphs/state_update_plan.py`
* `local_life_agent/engine/subgraphs/active_turn_resolver.py`
* `local_life_agent/engine/_routes.py`
* `local_life_agent/input/receiver.py`
* `local_life_agent/input/validator.py`
* `local_life_agent/input/normalizer.py`
* `local_life_agent/input/hard_guard.py`
* `local_life_agent/semantic/intent_parser.py`
* `local_life_agent/semantic/frame_validator.py`
* `local_life_agent/target/context_recovery.py`
* `local_life_agent/target/clarification.py`
* `local_life_agent/session/store.py`
* `local_life_agent/domain/state.py`
* `local_life_agent/domain/graph_state.py`
* `local_life_agent/domain/schemas.py`
* `local_life_agent/core/StateCore` 相关实现，如果 state_update_plan 有调用
* 与 `SessionState`、`PendingClarification`、`SemanticFrame`、`TopIntent`、`GraphState` 相关的定义和测试

请重点确认当前第一层真实数据流：

```text
raw_text
  → intake_guard_router
  → merge_clarification 或 understanding_subgraph
  → 第二层 orchestration / planning
  → response
  → state_update_plan
  → final_response
```

请基于真实代码回答：

1. `load_session` 当前是否发生在 `basic_validate` 之前？
2. `final_response` 是否在第一层多个节点中被提前写入？
3. `error_code` / `error_message` 是否是多个阶段共用的全局字段？
4. `pending_clarification` 和 `clarification_request` 是否重复表达同一个对象？
5. `hard_guard` 是否包含业务关键词放行逻辑？
6. `top_intent_router` 是否只支持单标签 intent，是否能表达 greeting + local_life / capability + local_life 这类混合意图？
7. `top_intent_router` 是否对“便宜一点的呢 / 那有券吗 / 第二个怎么样”等上下文追问有足够上下文？
8. 是否存在明确的 `query rewrite` / `conversation contextualization` / `contextualized turn` 层？
9. `active_turn_resolver` 是否只处理 pending clarification，还是已经承担话题切换、模糊匹配、语义判断等职责？
10. `merge_clarification restore` 是否能处理“选择 + 新增约束 / 新增 facet / 新任务”的情况？
11. `slot_extractor` 是否只做 anchor 提取，还是会侵入 task_type / preference / shop_id 等业务决策？
12. `context_recovery`、`active_turn_resolver`、`slot_extractor`、`target_resolve` 之间是否有职责重叠？
13. `SessionState` 当前字段是否已经过胖？是否混合了 current_shop、last_recommendation_list、comparison_targets、active_constraints、active_goal、replan_counters 等不同层级状态？
14. 是否存在明确的 `FocusContext` 或等价模型，用于表达当前多轮焦点到底是单店、推荐列表、对比集合还是候选集？
15. 状态写回是否真的只有 `state_update_plan` 一个入口？是否有其他节点直接写 session store？
16. `SessionState` 是否有 TTL / freshness / generated_at / expires_at 等机制？
17. 营业状态、距离、优惠券、推荐列表等跨轮复用时是否有过期判断？
18. 用户位置上下文是否在第一层有清晰边界，例如 location_source、mock_location、permission、freshness？
19. `InMemorySessionStore` 是否只是开发态实现？是否已有可替换接口或 Redis / DB 实现边界？
20. 第一层是否有统一 trace schema，能解释每次 route、guard、intent、clarification、context recovery 的决策原因？

请输出到 `todo/first_layer/`，建议文件结构：

```text
todo/first_layer/
  01_first_layer_fact_baseline.md
  02_first_layer_problem_analysis.md
  03_first_layer_solution_plan.md
  04_first_layer_contract_design.md
  05_first_layer_test_plan.md
```

如果你认为一个文件更合适，也可以合并，但必须保证内容完整。

文档 1：`01_first_layer_fact_baseline.md`

请写清楚真实代码现状：

* 第一层真实调用链
* 每个节点读写的关键 state 字段
* `GraphState` / `SessionState` / `SemanticFrame` / `PendingClarification` 的真实字段
* 条件边如何读取路由字段
* 哪些节点会写 `final_response`
* 哪些节点会写 `error_code`
* 哪些节点会读写 session
* 哪些节点调用 LLM
* 哪些节点是规则 / 模糊匹配 / deterministic
* 当前缺失的模型或层，例如 query rewrite、FocusContext、TTL、mixed intent、trace schema

要求：每个结论都要标注对应文件和函数名，最好带行号。

文档 2：`02_first_layer_problem_analysis.md`

请按优先级分析问题，至少覆盖以下问题：

P0 级问题：

1. 缺少 query rewrite / conversation contextualization 层
   风险：多轮追问如“便宜一点的呢”“那有券吗”“第二个怎么样”可能在 top_intent 或 semantic_parse 阶段丢上下文。

2. 缺少 FocusContext
   风险：`current_shop`、`last_recommendation_list`、`comparison_targets`、`last_candidate_set` 并存时，“这家 / 这几个 / 第一个”引用优先级不清。

3. 第一层提前写 `final_response` 和共用 `error_code`
   风险：入口层、guard、intent、semantic validator 都可能覆盖同一字段，导致状态污染和错误来源不可解释。

4. `active_turn_resolver` 职责过重
   风险：它可能从 pending clarification 判断扩张成隐形 understanding 模块，与 semantic_parse / context_recovery 重叠。

5. `slot_extractor` 边界不清
   风险：规则抽取可能重新侵入 LLM 语义主路径，导致规则堆叠。

P1 级问题：

6. `merge_clarification restore` 缺少 restore_with_delta
   风险：用户回复“第二个吧，看看有没有券”时，只恢复旧帧，漏掉新增 facet。

7. `hard_guard` 业务关键词放行可能变成弱路由
   风险：包含“火锅/优惠/距离”等词的非本地生活问题被误放行。

8. `top_intent` 单标签无法表达 mixed intent
   风险：“你好，帮我推荐火锅”“你能做什么，顺便查海底捞有券吗”被 terminal 掉。

9. SessionState 过胖且缺少分区
   风险：多轮上下文越来越难维护。

10. 缺少 TTL / freshness
    风险：营业状态、距离、优惠券等实时信息被跨轮错误复用。

P2 级问题：

11. `load_session` 可能过早
    风险：空输入、超长输入、非法输入也触发 session IO。

12. `pending_clarification` / `clarification_request` 字段重复
    风险：状态不同步。

13. InMemorySessionStore 不适合生产
    风险：服务重启丢失、多实例不共享、无 TTL、无并发保护。

14. 第一层 trace schema 不完整
    风险：排查“为什么被路由错 / 为什么 pending 被清掉 / 为什么没进 local_life”困难。

文档 3：`03_first_layer_solution_plan.md`

请给出阶段化解决方案，不要一次性大改。

建议阶段如下：

### Phase A：事实冻结与边界测试

目标：

* 固化第一层真实调用链。
* 新增或规划 architecture boundary tests，防止职责继续扩散。
* 不改变业务行为。

输出：

* 第一层 state 字段读写矩阵。
* 第一层 route 决策矩阵。
* 第一层 session 写入矩阵。
* 第一层 LLM / rule / deterministic 调用矩阵。

### Phase B：引入 ContextualizedTurn / Query Contextualizer

目标：

* 新增明确的上下文化 turn 表示。
* 不直接替换 semantic_parse，先作为中间字段和 trace。
* 让 top_intent_router 和 semantic_parse 可选择使用上下文化 query。

建议模型：

```python
ContextualizedTurn:
    original_text: str
    normalized_text: str
    contextualized_query: str
    rewrite_type: Literal[
        "none",
        "followup_refinement",
        "deictic_resolution",
        "constraint_carryover",
        "comparison_followup",
        "clarification_delta"
    ]
    context_used: dict
    confidence: float
    warnings: list[str]
```

要求：

* 不允许编造事实。
* 必须保留 raw_text 和 normalized_text。
* 必须记录 context_used。
* 低置信度时不能强行 rewrite，应进入 clarification 或保守理解。

### Phase C：引入 FocusContext

目标：

* 统一 current_shop / recommendation_list / comparison_targets / candidate_set 的焦点表达。
* 给“这家 / 这几个 / 第一个”明确优先级。

建议模型：

```python
FocusContext:
    focus_type: Literal[
        "none",
        "single_shop",
        "recommendation_list",
        "comparison_set",
        "candidate_set"
    ]
    focus_items: list[dict]
    primary_focus: dict | None
    source_turn_id: str
    created_at: str
    expires_at: str | None
    freshness_policy: str | None
```

要求：

* `context_recovery` 只消费 FocusContext 或兼容映射，不再散读多个 session 字段。
* state_update_plan 负责从本轮结果生成新的 FocusContext。
* 保留旧字段兼容窗口，不要一次性删除。

### Phase D：收敛第一层错误和响应契约

目标：

* 第一层不再随意写最终自然语言回答。
* 入口层只输出 response directive。
* response_subgraph 统一生成最终文本。

建议模型：

```python
ErrorEnvelope:
    stage: str
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    recoverable: bool

EarlyResponseDirective:
    response_mode: Literal[
        "invalid",
        "greeting",
        "capability",
        "reject",
        "clarify",
        "answer"
    ]
    reason: str
    payload: dict
```

要求：

* 尽量减少全局 `error_code` / `final_response` 的提前写入。
* 若保留兼容字段，必须由新 envelope 派生。
* trace 中能看出错误来源。

### Phase E：收紧 active_turn_resolver / slot_extractor / hard_guard 边界

目标：

* `active_turn_resolver` 只处理 pending clarification 的回复识别，不做普通多轮 query 理解。
* `slot_extractor` 只输出 anchors / candidates / spans，不输出最终业务决策。
* `hard_guard` 只做安全、无效、问候、能力类判断，业务关键词只能作为 weak signal。

要求：

`slot_extractor` 允许：

* merchant mention span
* deictic reference anchor
* ordinal reference anchor
* number / location anchor
* brand candidate

`slot_extractor` 禁止：

* 判断 task_type
* 判断 recommendation / comparison
* 判断用户偏好
* 判断 facet 优先级
* 直接决定 shop_id
* 覆盖 LLM semantic_frame 的关键字段

### Phase F：SessionState 分区、TTL 与位置上下文

目标：

* 避免 SessionState 继续变成大杂烩。
* 给实时本地生活字段增加 freshness。
* 明确位置上下文可信边界。

建议结构：

```python
SessionState:
    conversation_context
    focus_context
    clarification_context
    recommendation_context
    comparison_context
    user_preference_summary
    execution_counters
```

建议增加：

```python
FreshnessMeta:
    generated_at: str
    expires_at: str | None
    source: str
    freshness_policy: str
```

位置上下文建议：

```python
LocationContext:
    lat: float | None
    lng: float | None
    label: str | None
    source: Literal["user_permission", "java_realtime_context", "mock", "default_city", "unknown"]
    generated_at: str | None
    expires_at: str | None
    confidence: float
```

### Phase G：第一层 trace schema 与验收

目标：

* 所有第一层关键决策可解释。
* 所有新增能力可测试。

建议 trace：

```python
FirstLayerTrace:
    intake_decision
    guard_decision
    active_turn_decision
    contextualization_decision
    top_intent_decision
    clarification_decision
    semantic_parse_decision
    context_recovery_decision
    state_update_decision
```

每个 decision 至少包含：

```python
stage
decision
reason
source
confidence
context_used
input_snapshot
```

文档 4：`04_first_layer_contract_design.md`

请写清楚建议新增或收敛的契约：

* `ContextualizedTurn`
* `FocusContext`
* `ErrorEnvelope`
* `EarlyResponseDirective`
* `FreshnessMeta`
* `LocationContext`
* `FirstLayerTrace`
* `AnchorExtractionResult`
* `ClarificationDelta`

同时说明：

1. 哪些属于 `GraphState`
2. 哪些属于 `SessionState`
3. 哪些属于 `Domain DTO`
4. 哪些属于 `Observability / Trace`
5. 哪些只是兼容派生字段，不应作为权威状态

文档 5：`05_first_layer_test_plan.md`

请给出测试计划，不要编造当前已存在的测试文件名。新增建议测试必须用 `TODO_ADD_TEST:` 标记。

必须覆盖以下 case：

1. 空输入不会加载 session 或不会触发后续理解链路。
2. “你好，附近有火锅吗”不能被 greeting terminal 掉。
3. “你能做什么，顺便查海底捞有券吗”不能被 capability terminal 掉。
4. 上一轮推荐火锅后，用户说“便宜一点的呢”，应生成 contextualized turn。
5. 上一轮推荐列表后，用户说“第二个怎么样”，应通过 FocusContext 定位第二个。
6. 上一轮澄清 A/B 店后，用户说“第二个吧，看看有没有券”，应识别为 restore_with_delta。
7. `slot_extractor` 不应输出最终 shop_id。
8. `slot_extractor` 不应覆盖 task_type。
9. `hard_guard` 的 business_patterns 不应成为本地生活路由权威。
10. `final_response` 应主要由 response_subgraph 生成，入口层只产出 directive。
11. `error_code` 应能追踪到具体 stage。
12. 营业状态、距离、券等实时结果跨轮复用时必须有 freshness 判断。
13. `state_update_plan` 是唯一 session 写入口。
14. 第一层 trace 能解释每个路由决策。

建议回归命令：

* 先扫描当前真实测试文件，列出现有可复用测试。
* 如果没有对应测试，请写 `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_contextualization.py`
* 如果没有对应测试，请写 `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_focus_context.py`
* 如果没有对应测试，请写 `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_contracts.py`
* 如果没有对应测试，请写 `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_trace.py`

最终输出要求：

1. 输出你实际扫描的文件列表。
2. 输出第一层真实调用链。
3. 输出问题清单，按 P0 / P1 / P2 排序。
4. 输出解决方案，按 Phase 1-5 排序。 
5. 输出建议新增的契约对象。
6. 输出测试计划和验收标准。
7. 将所有文档写入 `todo/first_layer/`。
8. 不要修改业务代码。
9. 不要删除旧字段。
10. 不要声称已经完成修复。
11. 如果发现我提供的第一层拆解与真实代码不一致，请单独列出“文档与代码偏差”。