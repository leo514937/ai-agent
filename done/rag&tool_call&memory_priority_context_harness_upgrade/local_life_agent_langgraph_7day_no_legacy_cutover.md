# 本地生活 Agent LangGraph 7 天去 legacy 改造计划

> 本文档已按 `todo/rag&tool_call&memory_priority_context_harness_upgrade/` 的新版 todo 同步。  
> 核心变化：Day1-Day2 保持不变，原先未完成的 Day2.5「RAG 脏数据治理」前置为新的 Day3，Day4-Day7 顺延并扩展为 Tool、RAG、Answer Quality、Graph/Memory/Harness/Cutover 的完整主链路。

## 总目标

- 7 天内把本地生活 chat 主链路完全切到 LangGraph compiled graph。
- Chat 默认且唯一主路径是 LangGraph，不再保留可执行的 legacy chat 主路径。
- 如果 LangGraph 出错，只能显式失败并暴露，不能静默切回旧链路。
- 最新一轮用户消息必须始终优先于历史上下文，用于当前轮意图判断、目标商家解析、回答契约和工具路由。
- recommendation 轮次必须主动隔离单店锚点，`current_shop`、`last_candidates`、旧 `route_decision` 只能作为弱参考。
- 所有 Chat / stream / golden cases 最终都以 LangGraph 结果为准。

## 最终主链路

```text
/chat/stream
  ↓
load_context
  ↓
understand_query(latest_turn_message first)
  ↓
memory_arbitration
  ↓
resolve_target
  ↓
build_answer_contract
  ↓
route_gate
  ├── tool_subgraph
  ├── rag_subgraph + rag_guardrail
  ├── rag_plus_tool
  └── recommendation_subgraph
  ↓
answer_depth_policy
  ↓
answer_structure_composer
  ↓
repetition_guard
  ↓
answer_quality_gate
  ↓
persist_session
  ↓
emit_final
```

---

## Day1：Context 边界与目标商家解析增强

目标：

- 把目标商家解析从隐式上下文升级为可解释、可测试、可回放的 Context Boundary 机制。
- 让最新一轮消息成为目标商家解析和上下文合并的最高优先级输入。
- recommendation 场景下显式降权 `session.current_shop` 和 `last_candidates`，避免把整轮推荐压缩成单店回答。

任务：

- 明确上下文分层：`L0 当前输入 > L1 client_context > L2 session context > L3 last_candidates/history_summary`。
- 定义统一的 `TargetShopResolution` 结构，显式输出 `source`、`confidence`、`should_clarify`、`reason`。
- 强化显式店名覆盖规则：本轮显式商家必须覆盖 `session.current_shop`、`history_summary`、`last_candidates` 的弱继承。
- 强化指代继承规则：“这家 / 它 / 第一家” 只能在可解释来源存在时继承。
- 新增低信息量输入 gate，禁止 `，`、`?`、`啊`、`1`、`...` 之类输入进入 RAG 或 Tool。
- 建立“最新一轮消息优先”的目标商家解析 harness 与 trace。

验收：

- 用户问 A 店只能答 A 店。
- 第二轮显式换店时不能继承第一轮店名。
- recommendation 轮次不能因为上一轮单店上下文而被收缩成单店回答。
- 低信息量输入不进入 RAG、不调用 Tool、不更新 `session.current_shop`。

---

## Day2：AnswerContract 与 Context Pruning 增强

目标：

- 让系统只回答用户当前轮真正问到的 facet，避免问券答环境、问营业答推荐、问环境编券。
- 让最新一轮用户消息决定本轮 contract，而不是历史 session 主题。

任务：

- 生成标准 `AnswerContract`，明确 `required_facets`、`forbidden_facets`、`allowed_tools`、`allowed_rag_facets`、`answer_style`。
- 为 `coupon / open_status / environment / recommendation / general_review` 等 facet 建立 contract 模板。
- 引入 Context Pruning：根据当前轮 contract 裁剪上下文，不再把所有历史内容塞给 LLM。
- recommendation contract 必须把单店结果降级为局部 evidence，不能让上一轮单店上下文收缩推荐主答案。
- 回答前增加 contract validation 和 answer linter，检查 forbidden facet 泄露、无关商家、伪实时声明、旧 contract 继承等问题。
- 建立多轮 contract harness，验证“最新消息优先重算 contract”。

验收：

- 问券不答环境。
- 问营业不推荐。
- 问环境不查券。
- 上一轮是推荐、本轮是有券吗时，本轮只使用 coupon contract。
- 上一轮是单店、本轮是推荐时，本轮必须重新生成 recommendation contract。

---

## Day3：RAG Dirty Data Guardrail 与 Clean Evidence Pack

目标：

- 把原来未完成的 Day2.5 提前为新的 Day3，先解决 RAG 脏数据治理这个 P0 问题。
- 让所有进入 LLM 的 evidence 在召回后、入模前完成准入控制。

任务：

- 新增 `LocalLifeRagGuardrail`，职责包括：
  - `validate_retrieval_plan`
  - `judge_evidence_relevance`
  - `drop_cross_shop_evidence`
  - `drop_forbidden_facet_evidence`
  - `drop_low_relevance_evidence`
  - `limit_sibling_context`
  - `build_clean_evidence_pack`
  - `return_low_quality_degradation`
- 定义 `EvidenceJudgement` 与 `RagGuardrailResult`，显式区分 `clean_items`、`weak_items`、`dropped_items`、`rag_quality_status`。
- 拦截跨店 evidence、错误 facet evidence、低相关 evidence、污染 sibling evidence。
- 建立 `Clean Evidence Pack`，并在全部弱证据或脏证据场景下触发降级回答。
- 增加 trace：记录 dropped reason、dirty reason、rag quality status、latest_turn_message 优先级。

验收：

- 问 A 店时，B 店 evidence 必须被 drop。
- 问环境时，coupon / open_status evidence 不得进入 final prompt 或 final answer。
- 全部弱证据时必须明确降级，不能强答。
- sibling 补全不得把 forbidden facet 或跨店信息带入上下文。

---

## Day4：Tool Harness 与实时信息契约增强

目标：

- 把优惠券、营业状态、距离、排队等实时或准实时信息从 RAG 中彻底分离。
- 建立可靠 Tool Harness，确保工具决策永远由最新一轮用户意图驱动。

任务：

- 定义 `RealtimeContract`，明确哪些 facet 必须走 Tool，且 `cannot_infer_from_rag = true`。
- 标准化 `ToolResult` 与 `ToolPlan`，显式记录 `status`、`fetched_at`、`is_realtime`、`confidence`、`fallback_policy`。
- Tool Planner 输入必须包含 `AnswerContract`、`TargetShopResolution`、`UserNeed`、`latest_turn_message`、`current_intent`。
- 支持 recommendation 场景下对候选店逐个调用 `coupon / open_status / distance`，禁止把上一轮单店 `current_shop` 当成整轮 tool 主 shop。
- 约束最终上下文：问券只能注入 coupon tool result；问营业只能注入 open_status tool result。
- 定义工具失败降级话术，禁止根据 RAG 猜有券、根据历史营业时间猜当前营业状态。

验收：

- “有券吗” 必须走 Tool，券数量只能来自 tool result。
- “现在营业吗” 必须走 Tool，实时声明必须由 tool result 支撑。
- Tool timeout / error 时只能降级说明，不能编造实时结果。
- recommendation 场景不会被上一轮单店 `current_shop` 绑定成单店工具查询。

---

## Day5：RAG 父子检索、混合检索与 RAG Eval

目标：

- 在 Day3 脏数据准入完成后，升级父子检索、BM25、metadata recall、RRF、rerank 与 RAG Eval。
- 让单店问题不串店，让推荐问题能按店聚合且可评测。

任务：

- 明确两种 RAG 模式：
  - `single_shop_rag`：必须 `filter shop_id = target_shop_id`。
  - `recommendation_rag`：不能强 filter `session.current_shop`，必须广谱召回并按 `shop_id` 聚合。
- 升级 Qdrant payload，补齐 `chunk_level`、`parent_id`、`shop_id`、`facet`、`scene_tags`、`business_area`、`freshness_level` 等关键字段。
- 实现混合检索：`dense + BM25 + metadata -> RRF -> rerank`。
- 引入父子检索与 sibling 补全，并与 Day3 Guardrail 联动，限制 sibling 数量与 facet 兼容性。
- 定义 `RagEvidencePack` / `Evidence`，显式输出 `grouped_by_shop`、`dropped_cross_shop_evidence`、`support_level`。
- 新增 `rag_eval_cases.jsonl` 与 `rag_dirty_cases.jsonl`，建立多轮 latest priority 评测集。

验收：

- `single_shop_rag` 的 evidence 只能来自目标店。
- `recommendation_rag` 必须返回多个不同 `shop_id`，同一家店不能重复占多个推荐位。
- 上一轮单店、本轮推荐时，推荐结果不能只围绕上一轮店名。
- RAG Eval 必须产出 `recall@5`、`mrr@10`、`ndcg@10`、`cross_shop_rate`、`facet_hit_rate`、`dirty_context_rate`。

---

## Day6：Answer Quality、Depth Policy 与 Repetition Guard

目标：

- 在 clean evidence 支撑下，让回答充分、结构化、不重复。
- 解决回复过短、结构不完整、重复表达、重复推荐店铺等问题。

任务：

- 新增 `AnswerDepthPolicy`，按 `answer_style` 控制 `depth_level`、`min_sections`、`min_chars`、`require_risk_or_caveat`、`require_next_step`。
- 定义 `clean_evidence_count` 约束：证据不足时只能降级，禁止为了变长而编造。
- 新增 `AnswerStructureComposer`，为单店综合评价、场景判断、多 facet 问题、多店推荐定义结构化输出模板。
- 新增 `RepetitionGuard`，处理重复句子、重复 bullet、重复推荐理由、低信息表达、重复店铺。
- 新增 `AnswerQualityGate`，检查 `answer_too_short`、`answer_too_repetitive`、`forbidden_facet_leak`、`unsupported_realtime_claim`、`recommendation_duplicate_shop`。
- 建立回答质量 harness，验证答案变长基于 clean evidence 而不是 hallucination。

验收：

- 单店综合评价至少包含总体结论、核心优点、可能不足、适合场景、到店建议。
- 多 facet 问题必须按 facet 分块回答。
- 多店推荐至少返回 3 家店或明确说明候选不足，每家至少 2 条非重复理由。
- `clean_evidence_count = 0` 时只能输出证据不足降级回答，不能强行详细展开。

---

## Day7：GraphState、Memory Arbitration、Harness、Cutover 与生产硬化

目标：

- 把 Day3-Day6 的能力全部纳入 LangGraph 状态生命周期。
- 补齐 Memory Arbitration、Golden Cases、Observability、性能预算，并完成最终去 legacy 切流。

任务：

- 定义 `InputContext`、`TurnRuntimeState`、`PersistentContext`。
- 新增 `PerceptionContext` 和 `MemoryArbitrationResult`，固化 Current Turn Perception 优先级。
- 明确 temporal scope：临时表达只写 session，长期表达进入 promotion candidate。
- 为每个 LangGraph 节点定义 `requires`、`writes`、`invariants`、`error_behavior`。
- 增加 `state_diff`、`node_writes`、`illegal_state_mutation`，禁止：
  - `rag_subgraph` 修改 `target_shop`
  - `tool_subgraph` 修改 `answer_contract`
  - `compose_answer` 偷偷补充 forbidden facet
  - `persist_session` 把 recommendation 轮写成新的 `current_shop`
- 建立 L1-L5 Harness：Unit、Node、Route、Chat E2E、Golden Cases Regression。
- 定义统一 trace、error taxonomy、核心质量指标与 slow trace。
- 删除或废弃 legacy 入口：
  - `ChatWorkflowService` 中的 legacy fallback 分支
  - `create_workflow_runner` 中生产切到 `SequentialWorkflowRunner` 的路径
  - `LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY` 运行时开关
  - 生产代码对 `LocalLifeSubgraph` 作为主链路的直接依赖

验收：

- `latest_turn_message` 是每轮状态推导的第一输入。
- Current Turn Perception 高于 session / profile / long-term memory。
- `recommendation_scope` 与 `target_shop` 分离，互不污染。
- `graph_runtime = langgraph`，生产运行时不存在 legacy fallback 分支。
- `golden_cases` 通过率不低于 95%。
- `dirty_context_rate = 0`，核心场景 `answer_too_short_rate = 0`，`answer_repetitive_rate = 0`。

---

## 全局验收与 Trace 标准

每个关键 E2E case 都必须断言：

```text
runner_kind = langgraph
runner_backend = langgraph
graph_runtime = langgraph
final_answer 非空
无 Traceback
无 None 泄露
无 debug 字段泄露
latest_turn_priority = true
```

每轮 trace 至少包含：

```json
{
  "trace_id": "...",
  "runner_kind": "langgraph",
  "graph_runtime": "langgraph",
  "nodes_visited": [],
  "latest_turn_message": "...",
  "current_intent": {},
  "priority_source": "latest_turn_message",
  "target_shop": {},
  "answer_contract": {},
  "tool_plan": {},
  "tool_results": [],
  "rag_guardrail": {},
  "answer_quality": {},
  "memory_arbitration": {},
  "latency": {},
  "errors": []
}
```

关键错误分类：

```text
LOW_INFO_QUERY
TARGET_SHOP_MISSING
TARGET_SHOP_AMBIGUOUS
TARGET_SHOP_WRONG
ROUTE_MISMATCH
CONTRACT_VIOLATION
FACET_LEAK
RAG_EMPTY
RAG_CROSS_SHOP
RAG_LOW_CONFIDENCE
RAG_DIRTY_CONTEXT
TOOL_TIMEOUT
TOOL_ERROR
TOOL_BAD_RESULT
UNSUPPORTED_REALTIME_CLAIM
ANSWER_TOO_SHORT
ANSWER_REPETITIVE
RECOMMENDATION_DUPLICATE_SHOP
MEMORY_ARBITRATION_ERROR
GRAPH_NODE_ERROR
GRAPH_ILLEGAL_STATE_MUTATION
COMPOSE_ERROR
```

---

## Day7 完成后的硬标准

必须满足：

- 运行时没有 legacy fallback 分支。
- 不再存在可从 chat 主路径调用旧链路的入口。
- `LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY` 已删除或废弃，不再作为运行时切换开关。
- test / staging / prod 都以 LangGraph 为唯一运行时主路径。
- 如果 LangGraph 异常，必须显式失败并暴露，不得悄悄回退。
- 所有 Chat / stream 验收都以 LangGraph 结果为准。
- `latest_turn_message` 优先级已经固化在主图里，不依赖 legacy 补丁。
- recommendation 轮次不会再把旧 `current_shop` 写回成新的会话主锚点。
