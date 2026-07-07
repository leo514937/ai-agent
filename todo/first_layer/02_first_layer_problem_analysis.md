# 第一层问题分析

本文件只按当前仓库真实代码做风险分析，不把未实现内容当作已存在。

## P0

### 1. 缺少 query rewrite / conversation contextualization 层

- 风险：像“便宜一点的呢”“那有券吗”“第二个怎么样”这类追问，当前主要依赖 `active_turn_resolver`、`semantic_parse` 的隐式上下文和 session summary，缺少一个可审计的中间产物。
- 证据：
  - `parse_semantic_frame` 只把压缩后的 `SessionContextSummary` 注入 prompt，并没有独立的 `ContextualizedTurn` 对象 `[intent_parser.py:1021-1037](D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py#L1021)`
  - `SessionContextSummary` 只是摘要，不是 rewrite 层 `[session_context_summary.py:32-162](D:/javacode/hm-dianping/local_life_agent/domain/session_context_summary.py#L32)`
  - 仓库内没有 `ContextualizedTurn` 命中

### 2. 缺少 FocusContext

- 风险：`current_shop`、`last_recommendation_list`、`comparison_targets`、`last_candidate_set`、`active_goal` 并存时，“这家 / 这几个 / 第一个”引用优先级不清。
- 证据：
  - `SessionState` 分散持有这些字段 `[state.py:116-150](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L116)`
  - `build_session_context_summary` 只能摘取少量名称和数量，没有焦点优先级模型 `[session_context_summary.py:94-162](D:/javacode/hm-dianping/local_life_agent/domain/session_context_summary.py#L94)`

### 3. 第一层提前写 `final_response` 和共用 `error_code`

- 风险：入口层、guard、intent router、澄清恢复都能提前写 `final_response`，而 `error_code` / `error_message` 又是 GraphState 共享字段，容易被后续阶段覆盖，导致错误来源难解释。
- 证据：
  - `basic_validate` 直接写 `final_response` 和错误码 `[intake_guard_router.py:183-189](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L183)`
  - `hard_guard` 直接写 `final_response` `[intake_guard_router.py:207-216](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L207)`
   - `top_intent_router` 也写 `final_response`（固定回复，共 5 种）`[intake_guard_router.py:241-249](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L241)`
   - `merge_clarification` 在 6 个分支（restore/topic_switch/cancelled/expired/invalid/out_of_range）写 / 清空 `final_response` `[merge_clarification.py:83-189](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/merge_clarification.py#L83)`

### 4. `active_turn_resolver` 职责过重

- 风险：它已经不是“只看 pending clarification”，还做 topic switch heuristic、规则、模糊匹配、可选 bounded LLM、语义 override，容易和 `context_recovery`、`slot_extractor`、`merge_clarification` 互相侵蚀职责。
- 证据：
  - `resolve_active_turn` 明确写着四层 pipeline `[active_turn_resolver.py:458-525](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L458)`
  - `_should_treat_as_topic_switch` 还会把“附近/火锅/优惠券/营业/哪家/怎么样/评价/距离”这类词当成 topic switch 线索 `[active_turn_resolver.py:539-595](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L539)`

### 5. `slot_extractor` 边界不清

- 风险：`slot_extractor` 已经不仅是 anchor 提取，而是直接决定 task_type、primary_task、workflow_hint、comparison、preference、focused_facets、comparison_targets 等，规则会侵入语义主路径。
- 证据：
  - `extract_slots` 内部直接分配 `task_type`、`primary_task`、`workflow_hint` `[slot_extractor.py:592-766](D:/javacode/hm-dianping/local_life_agent/semantic/slot_extractor.py#L592)`

## P1

### 6. `merge_clarification` restore 缺少显式 `restore_with_delta`

- 风险：用户回复“第二个吧，看看有没有券”时，当前逻辑虽然能通过 `constraint_update` / 选项 / 比较补槽合并部分 delta，但没有一个独立契约表达“恢复旧帧 + 追加新约束”。
- 证据：
  - `handle_clarification_reply` 已有 `_merge_semantic_frame(original_frame, reply_frame)` 和 `constraint_update` 路径 `[clarification.py:609-655](D:/javacode/hm-dianping/local_life_agent/target/clarification.py#L609)`
  - 但外层 `merge_clarification` 只消费 `status=restore/topic_switch/...`，没有显式 delta 对象 `[merge_clarification.py:60-180](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/merge_clarification.py#L60)`

### 7. `hard_guard` 的业务关键词放行可能变成弱路由

- 风险：命中 `_BUSINESS_PATTERNS` 就直接放行，可能让“包含火锅/优惠/距离”等词的非本地生活问题进入后续链路。
- 证据：
  - `_BUSINESS_PATTERNS` 覆盖很宽 `[hard_guard.py:25-60](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L25)`
  - 命中就 `passed=True, label=safe` `[hard_guard.py:93-99](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L93)`

### 8. `top_intent` 单标签无法表达 mixed intent

- 风险："你好，帮我推荐火锅""你能做什么，顺便查海底捞有券吗"这类 query，既有问候 / 能力成分，也有本地生活成分；当前 `TopIntent` 只能返回一个标签。
- 证据：
  - `TopIntent` 只有六个枚举值 `[enums.py:6-12](D:/javacode/hm-dianping/local_life_agent/domain/enums.py#L6)`
  - `_h_top_intent_router` 的路由也是单值判断（只检查 `top_intent` 枚举值）`[intake_guard_router.py:220-268](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L220)`（⚠️ 不存在独立的 `top_intent_router_handler.py`）

### 9. `SessionState` 过胖且缺少分区

- 风险：会话状态被同时当作当前店、推荐列表、比较集合、约束、目标、回顾结果、重规划计数器使用，后续很难维护。
- 证据：`[state.py:116-150](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L116)`

### 10. `_should_treat_as_topic_switch` 存在两份独立且不一致的实现

- 风险：`active_turn_resolver.py`（行 539-595）和 `clarification.py`（行 478-531）各有一份 `_should_treat_as_topic_switch`，两份逻辑结构相似但具体关键词列表和判断细节可能不同，双份代码导致 topic switch 判定行为不一致。
- 证据：
  - `[active_turn_resolver.py:539-595](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L539)` — 使用关键词 `"附近/火锅/推荐/优惠券/有券/营业/哪家/怎么样/好吃/评价/距离/多远/怎么去/怎么走/开门"`
  - `[clarification.py:478-531](D:/javacode/hm-dianping/local_life_agent/target/clarification.py#L478)` — 另一份独立副本

### 11. 缺少统一 TTL / freshness

- 风险：营业状态、距离、优惠券、推荐列表如果跨轮复用，没有统一 freshness 语义，就容易拿旧结果继续回答。
- 证据：
  - `PendingClarification` 有 `expires_at`，但这是单点 TTL `[schemas.py:704-719](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L704)`
  - `SessionValueMeta` 只有 `ttl` / `location_context` / `resume_strategy`，没有统一 session freshness 结构 `[state.py:89-102](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L89)`

## P2

### 12. `load_session` 可能过早且写 15+ 个 GraphState 字段（副作用过大）

- 风险：空输入 / 超长输入 / 非法输入也会触发 session IO；且 `_h_load_session`（`intake_guard_router.py:153-177`）除了从 store 读取外，还直接写 15+ 个 GraphState 字段（`session_state`、`current_shop`、`last_recommendation_list`、`active_constraints`、`pending_clarification`、`clarification_request` 等），实为"读 + 展开"而非单纯加载。
- 证据：
  - `intake_guard_router` 先 `load_session` 再 `basic_validate` `[intake_guard_router.py:45-48](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L45)`
  - `_h_load_session` 写 15+ 个字段 `[intake_guard_router.py:153-177](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L153)`

### 13. `slot_extractor` 被 4 处调用，跨层依赖严重

- 风险：`slot_extractor.extract_slots` 并非 `understanding_subgraph` 独占，而是被 `clarification.py`、`active_turn_resolver.py`、`intent_parser.py` 也直接调用。不同调用者的行为不一致（`understanding_subgraph` 内的调用只做 anchor 补强，不清空 `task_type`；其他调用者会覆盖 `task_type`），导致 `task_type` 的最终值取决于执行路径。
- 证据：
  - `[understanding_subgraph.py:206-228](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L206)` — 只做 anchor 补强，不在 _h_slot_extractor 内覆盖 task_type
  - `[clarification.py:541-544](D:/javacode/hm-dianping/local_life_agent/target/clarification.py#L541)` — _merge_semantic_frame 中调用，会覆盖 task_type
  - `[active_turn_resolver.py:219-228](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L219)` — _semantic_reply_frame 中调用，第 1 层节点直接调用第 2 层语义模块
  - `[intent_parser.py:618-622](D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py#L618)` — _parse_workflow_from_llm_slot 中调用
  - `[slot_extractor.py:564-766](D:/javacode/hm-dianping/local_life_agent/semantic/slot_extractor.py#L564)` — extract_slots 核心，会覆盖 task_type、primary_task、workflow_hint

### 14. `state_update_plan._h_persist_session` 有额外写逻辑绕过 SessionWriteDirective

- 风险：`_h_persist_session` 在 `store.save()`（行 179）之前有两段不受 `SessionWriteDirective` 控制的额外写逻辑（行 160-177），直接修改 `session_state.comparison_targets`。这在审计上是不透明的——谁改了什么并不完全由 `plan_state_update` 的返回值决定。
- 证据：
  - `[state_update_plan.py:160-168](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L160)` — comparison_target_resolution 写回
  - `[state_update_plan.py:169-177](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L169)` — comparison_result.rows 写回

### 15. `hard_guard` 双重 normalize

- 风险：`_h_hard_guard`（`intake_guard_router.py:207-217`）读 `normalized_text`，但 `hard_guard.py:82` 内部又自行调用 `normalize_text(input_text)`。等于 normalized_text 经过了两次 normalize，而 `_h_normalize_text` 阶段的结果被忽略。
- 证据：
  - `[intake_guard_router.py:199-204](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L199)` — _h_normalize_text 首次规范化
  - `[intake_guard_router.py:207-217](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L207)` — _h_hard_guard 传入 normalized_text
  - `[hard_guard.py:73-84](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L73)` — check_hard_guard 内部又调 normalize_text

### 16. `load_session` 写 `pending_clarification` 和 `clarification_request` 为同一值

- 风险：`_h_load_session` 直接把 session_state.pending_clarification 赋值给两个不同字段（`intake_guard_router.py:167`），后续如果只有一处被清空，二者会不同步。
- 证据：`[intake_guard_router.py:159-168](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L159)` — 同时写 pending_clarification 和 clarification_request

### 17. `InMemorySessionStore` 不适合生产

- 风险：进程内字典没有 TTL、没有多实例共享、没有持久化、没有并发控制。
- 证据：
  - `load/save/clear/snapshot` 都是本地字典 `[session/store.py:11-41](D:/javacode/hm-dianping/local_life_agent/session/store.py#L11)`
  - `get_session_store()` 返回进程级单例 `[session/store.py:44-60](D:/javacode/hm-dianping/local_life_agent/session/store.py#L44)`

### 18. 第一层 trace schema 不完整

- 风险：排查"为什么被路由错 / 为什么 pending 被清掉 / 为什么没进 local_life"时，需要串多个事件日志和字段，没有统一第一层专属 trace。
- 证据：
  - 当前主要是 `event_log` / `trace_spans` / `TurnTrace` 之类通用机制，未见 `FirstLayerTrace` 命名命中
  - `active_turn_resolver`、`top_intent_router`、`merge_clarification` 都只写各自事件日志

## 补充分析：六个关键点的问题深化

### A. Mixed Intent 的结构化表达（风险升级）

**从 P1 → 建议 P0**，理由如下：

- 当前 TopIntent 单标签导致的第一层路由丢失信息无法在下游恢复
- 当 LLM 被强制选一个标签时，"你好，推荐火锅"会落入 local_life，但 greeting 被丢弃；"你都能干什么，顺便查海底捞"会落入 capability 或 local_life，另一个被丢弃
- **丢失的信息无法恢复**：下游 semantic_parse 的 LLM prompt 只包含 	op_intent 这个枚举值，无法知道原始 query 有多个意图成分
- 混合意图跟 P2 的"greeting 回后还能识别"不同：greeting 的后续可以被 hard_guard 拦截，但 mixed intent 在第一步就被裁减掉了

**升级原因：这是信息丢失，不是延迟决策。**

### B. ContextualizedTurn 与 SemanticFrame 的权威边界（方案问题）

**风险不在实现，而在边界设计：**

- SemanticFrame 已经 75 个字段，覆盖了从"意图分类"到"facet 规划"到"排序策略"的完整链路。新增 ContextualizedTurn 如果不明确边界，可能变成"又一个 SemanticFrame"——同时又保持对旧 SemanticFrame 的兼容，产生两个胖对象。
- 具体困境：
  1. ContextualizedTurn 应该持有"上下文化后的 query 文本"还是"上下文化后的槽位"？
  2. 如果持文本，那 semantic_parse 仍然需要完整意图理解
  3. 如果持槽位，那它和 SemanticFrame.prefill 或 SemanticFrame.reference 有什么本质区别？
- **边界原则**：ContextualizedTurn 只持有"自然语言级"信息（query + rewrite_type + context_used），不做任何"意图级"判断。槽位归属、偏好提取、facet 规划仍然是 SemanticFrame 的职责。
- SemanticFrame 本身也需要缩窄：去掉 anking_policy、anking_signals、acets、acet_set、comparison_focused_facets 等应该在工程规划阶段解决的字段

### C. FocusContext 的 item 级字段规范（设计补全）

**现有方案 ocus_items: list[dict] 的 gap：**

- 没有每个 item 的 type/entity/source/priority/expiry/mention_support 约束
- 无法区分"上次推荐列表里的第 X 家"和"当前正在看的店"
- context_recovery 需要从 FocusContext 推断"这家/那家/第一家"时，缺乏排序和引用优先级字段
- state_update_plan 更新 FocusContext 时，无法知道哪些 item 过期、哪些 item 需要保留

**具体问题场景：**

1. 用户："推荐火锅" → FocusContext: [recommendation_list(items=[...])]
2. 用户："第一家怎么样" → context_recovery 需要知道"第一家"指推荐列表的第 0 项
   - 当前靠 last_recommendation_list[0]['entity']['id'] 推断，但没有统一匹配路径
3. 用户："算了，看看这个店有没有券" → FocusContext 应该有 shop_entity 和 ecommendation_ranked 的优先级比较
   - "这个店"应该优先匹配 current_shop（shop_entity 类型）而非推荐列表

### D. load_session 后移的可行性分析

**不能简单后移的原因（细化）：**

| 原因 | 细节 | 影响程度 |
|---|---|---|
| active_turn_resolver 需要 session | 行 603-657 读 session_state_before.pending_clarification | 高 — 没有 session 就无法判断 pending |
| basic_validate 不依赖 session | 行 180-196 只读 state.get("raw_text") | 低 — validate 本身可独立执行 |
| hard_guard 不依赖 session | 行 207-217 只读 
ormalized_text | 低 |
| top_intent_router 微依赖 session | 行 220-268 只用 
ormalized_text，但 LLM prompt 可能含上下文 | 中 — 当前 prompt 不依赖 session，但未来可能需要 |

**折中方案的风险分析：**

1. **"先 validate，再只读 session 不展开"方案**：
   - 需要把 _h_load_session 拆成两步：_h_validate_session_id（轻量校验） + _h_expand_session（展开字段）
   - 如果 session_id 本身来自 raw_text（如用户显式传 session_id），那 validate 时也需要 raw_text → 已经是 validate 之后
   - ⚠️ 当前 _h_receive_input 已经在 TurnInput 里带 session_id（eceiver.py:16-40），不需要从 raw_text 提取

2. **"先 validate，再完整 load_session"方案**：
   - 改动最小：只是把 _h_load_session 从步骤 2 移到步骤 3
   - 但 _h_basic_validate 当前只读 aw_text，移到 validate 后不影响任何节点输入
   - _h_active_turn_resolver 在步骤 6，session 早在步骤 2（或移动后步骤 3）已加载，所以不受影响
   - **核心损失**：validate 失败时多做了 _h_receive_input 和 session I/O，但省去了 _h_normalize_text + _h_hard_guard + _h_active_turn_resolver 的后续调度
   - ✅ **实际收益存在**：对于大量非法输入（恶意扫描、空连接、机器人），所有不经过 receive_input 的请求完全不走 session；经过 receive_input 但 validate 失败的请求只做一次 session load 就返回

**结论：后移可行且有收益，但需要明确"session load 后的所有字段展开"是否也应延迟。**

### E. InMemorySessionStore 迁移接口设计

**生产迁移要解决的痛点（按严重程度排序）：**

| 问题 | 当前状态 | 严重程度 |
|---|---|---|
| 无多实例共享 | 进程内字典，多实例 session 不统一 | P0 — 多实例必须 |
| 无 TTL | 会话永不自动过期 | P0 — 内存泄漏风险 |
| 无持久化 | 进程重启丢失所有 session | P1 |
| 无并发控制 | dict 操作非原子，多协程竞争写可能丢数据 | P1 |
| 无序列化契约 | 当前靠 Pydantic 隐式序列化，没有显式 schema | P2 |

**接口设计的关键决策：**

1. **抽象层级**：当前 load(session_id) -> SessionState 和 save(session_id, state) 接口简洁，但问题是粒度太粗——生产和消费可能只需要 SessionState 的某个分区（如 ocus_context），而非全部 24 个字段
2. **分区存储的必要性**：如果引入 FocusContext、FreshnessMeta、分区，应该支持按分区读写，而不是每次都序列化整个 SessionState
3. **TTL 策略**：不同分区应有不同 TTL（如 ocus_context 30min，ecommendation_context 10min，pending_clarification 5min）

### F. 第一层和第二层 target_resolve 的职责切分（重叠问题）

**当前重叠的准确范围：**

| 能力 | 第一层 context_recovery | 第二层 target_resolve | 重叠程度 |
|---|---|---|---|
| 解析比较目标 | _resolve_comparison_targets 快速解析 | esolve_comparison_targets 完整解析 | **高** — 函数名都一样 |
| 解析单店引用 | esolve_shop 快速条目解析 | esolve_shop_entity 完整实体解析 | **中** — 解析深度不同 |
| 构建 pending_clarification | uild_clarification 用于引用歧义 | esolve_shop_entity 返回 ambiguous 时也建 | **中** — 触发场景不同 |
| 消费 resolved_target | 产出者 | 通过 state.get(RESOLVED_TARGET) 消费 | **单向依赖** |

**具体耦合代码路径：**

1. context_recovery.py 产出 esolved_target（schemas.py 中 ResolvedTarget 类型）
2. planning_subgraph._h_target_resolve 行 597-632 读取 esolved_target
3. 如果 esolved_target.status == "RESOLVED"，第二层直接使用，不做第二遍解析
4. 如果 esolved_target.status != "RESOLVED"，第二层做自己的解析

**这意味着**：第二层的执行路径取决于第一层的解析结果，但第一层的解析器（规则/轻量）和第二层的解析器（完整/tool-based）不一致。如果第一层判定为 RESOLVED 但解析错误，第二层会直接使用错误结果。

**建议收敛方向：**

- 第一层 context_recovery 只做"引用识别 + 是否需要澄清"——不做完整 entity 解析
- esolved_target 只携带"引用索引"（如 ocus_item_id + mention_type），不携带最终 entity 数据
- 第二层 	arget_resolve 接收引用索引后，**始终做完整 entity 解析**，不受第一层 status == "RESOLVED" 短路


## 文档与代码偏差
以下是“常见架构预期”与真实代码的偏差，后续方案必须按真实代码收敛：

- 预期中的“query rewrite”层并不存在，当前只是 `SessionContextSummary` 注入和隐式上下文补偿
- 预期中的 `FocusContext` 并不存在，焦点被拆散到 `current_shop`、`last_recommendation_list`、`comparison_targets`、`last_candidate_set`
- 预期中的“第一层只做路由，不写最终响应”不成立，`final_response` 已被多个第一层节点提前写入
- 预期中的“澄清恢复只做恢复”不成立，`handle_clarification_reply` 已经兼顾新增约束、比较补槽、店铺引用、topic switch
- 预期中的“slot_extractor 只提 anchor”不成立，它已经在做 task_type 和 preference 决策
- 预期中的“slot_extractor 只被 understanding_subgraph 调用”不成立，它被 clarification.py、active_turn_resolver.py、intent_parser.py 额外调用，形成 4 处跨层依赖
- 预期中的“state_update_plan 完全受 SessionWriteDirective 控制”不成立，_h_persist_session 有 2 段额外写 comparison_targets 的逻辑绕过 directive
- 预期中的“hard_guard 读 normalized_text”不成立，check_hard_guard 内部重新调用 normalize_text，等于双重规范化
- 预期中的“load_session 只加载”不成立，它同时写 15+ 个 GraphState 字段，是展开而非单纯加载
- 预期中的“topic_switch 判定只有一处”不成立，active_turn_resolver.py 和 clarification.py 各有一份独立副本
- 预期中的“final_response 写入在 merge_clarification 只有一处”不成立，restore/topic_switch/cancelled/expired/invalid/out_of_range 六个分支都会写 final_response


