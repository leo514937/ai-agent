# 第一层事实基线

## 调研范围

本次只基于当前仓库真实代码扫描以下文件及其直接依赖：

- `local_life_agent/engine/subgraphs/intake_guard_router.py`
- `local_life_agent/engine/subgraphs/merge_clarification.py`
- `local_life_agent/engine/subgraphs/understanding_subgraph.py`
- `local_life_agent/engine/subgraphs/state_update_plan.py`
- `local_life_agent/engine/subgraphs/active_turn_resolver.py`
- `local_life_agent/input/receiver.py`
- `local_life_agent/input/validator.py`
- `local_life_agent/input/normalizer.py`
- `local_life_agent/input/hard_guard.py`
- `local_life_agent/semantic/intent_parser.py`
- `local_life_agent/semantic/frame_validator.py`
- `local_life_agent/semantic/slot_extractor.py`
- `local_life_agent/target/context_recovery.py`
- `local_life_agent/target/clarification.py`
- `local_life_agent/session/store.py`
- `local_life_agent/core/state_core.py`
- `local_life_agent/planning/plans/state_update_planner.py`
- `local_life_agent/domain/state.py`
- `local_life_agent/domain/graph_state.py`
- `local_life_agent/domain/schemas.py`
- `local_life_agent/domain/enums.py`
- `local_life_agent/domain/session_context_summary.py`
- 相关测试：`local_life_agent/tests/test_input_layer.py`、`test_hard_guard.py`、`test_top_intent_router.py`、`test_active_turn_resolver.py`、`test_context_recovery_clarification.py`、`test_slot_extractor_boundaries.py`、`test_p5_session_state_writeback.py`、`test_trace_observability.py`、`test_phase1_architecture_boundaries.py`、`test_p12_deadline_budget_freshness_ttl.py`

> ⚠️ 注意：仓库中不存在 `top_intent_router_handler.py`。`_h_top_intent_router` 实际定义在 `intake_guard_router.py:220-268`。

## 第一层真实调用链

### 外层路由视角

`_routes.py` 中的外层映射实际把入口分成三类：

- `intake_guard` -> `merge_clarification` / `understanding_subgraph` / `response_subgraph`
- `merge_clarification` -> `understanding_subgraph` / `planning_subgraph` / `response_subgraph`
- `understanding_subgraph` -> `orchestration_router_shadow` / `response_subgraph`

证据：

- `[local_life_agent/engine/_routes.py:407-425](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L407)`
- `[local_life_agent/engine/_routes.py:287-308](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L287)`

### 真实入口顺序

`h_intake_guard_router()` 的真实顺序不是"先理解再路由"，而是：

1. `_h_receive_input` — 从 raw_text 组装 TurnInput
2. `_h_load_session` — 从 store 加载 SessionState（此时 normalized_text 尚未写入）
3. `_h_basic_validate` — 校验 raw_text 类型/空串/长度（此时读的是 `state.get("raw_text", "")`，非 normalized_text）
4. `_h_normalize_text` — 写入 normalized_text（NFKC + 标点统一）
5. `_h_hard_guard` — 读 normalized_text 做安全检查
6. `_h_active_turn_resolver` — 检查 pending clarification 是否需要处理
7. `_h_top_intent_router` — LLM 分类 top_intent

> ⚠️ 注意：_h_basic_validate 在第 3 步执行时，_h_normalize_text（第 4 步）尚未运行。所以 basic_validate 只能读 raw_text，不能依赖 normalized_text。而 hard_guard _h_hard_guard 内部又自行调用了一次 normalize_text（hard_guard.py:82），等于做了双重 normalize。

证据：

- `[local_life_agent/engine/subgraphs/intake_guard_router.py:41-139](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L41)`
- `_h_receive_input` 行 142-150
- `_h_load_session` 行 153-177（注意此时不写 normalized_text）
- `_h_basic_validate` 行 180-196（只读 `state.get("raw_text")`）
- `_h_normalize_text` 行 199-204（首次写入 normalized_text）
- `_h_hard_guard` 行 207-217（读 normalized_text，但内部 hard_guard.py:82 又调 normalize_text）
- `_h_active_turn_resolver` 行 603-657
- `_h_top_intent_router` 行 220-268

### 第一层到第二层的边界

- `top_intent == local_life` 时，`intake_guard_router` 路由到 `understanding_subgraph`
- `pending` 相关分支可能路由到 `merge_clarification`
- `understanding_subgraph` 再把流转给 `orchestration_router_shadow`
- 之后才进入规划 / 执行 / 回答链路

证据：

- `[local_life_agent/engine/subgraphs/intake_guard_router.py:115-139](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L115)`
- `[local_life_agent/engine/subgraphs/understanding_subgraph.py:38-81](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L38)`
- `[local_life_agent/engine/_routes.py:411-425](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L411)`

### 真实状态回写顺序

`state_update_plan` 不是第一层内部的普通节点，而是末端统一写回：

1. `_h_state_update_plan`
2. `_h_persist_session`
3. `_h_emit_response`

证据：

- `[local_life_agent/engine/subgraphs/state_update_plan.py:34-40](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L34)`
- `[local_life_agent/engine/subgraphs/state_update_plan.py:48-190](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L48)`

## 节点读写矩阵

### `receive_input`

- 文件 / 函数：`local_life_agent/input/receiver.py:16-40`
- 读取：`raw_text`、可选 `user_context`
- 写入：`input_type`、`raw_text`、`user_context`
- 行为：只做运输层校验和上下文注入，不做意图判断
- 证据：`[receiver.py:16-40](D:/javacode/hm-dianping/local_life_agent/input/receiver.py#L16)`

### `basic_validate`

- 文件 / 函数：`local_life_agent/input/validator.py:21-62`
- 读取：`raw_text`
- 写入：`valid`、`input_type`、`raw_text`、`error_code`、`error_message`
- 行为：只校验空串 / 类型 / 长度，不读 session，不做业务判断
- 证据：`[validator.py:21-62](D:/javacode/hm-dianping/local_life_agent/input/validator.py#L21)`

### `normalize_text`

- 文件 / 函数：`local_life_agent/input/normalizer.py:41-50`
- 读取：`text`
- 写入：返回规范化文本
- 行为：NFKC、标点统一、空白折叠，保持业务关键词不变
- 证据：`[normalizer.py:41-50](D:/javacode/hm-dianping/local_life_agent/input/normalizer.py#L41)`

### `hard_guard`

- 文件 / 函数：`local_life_agent/input/hard_guard.py:73-132`
- 读取：规范化后的 `text`
- 写入：`passed`、`label`、`reason`、`reply`
- 行为：问候 / 能力 / 空串拦截；命中 `_BUSINESS_PATTERNS` 则直接放行
- 证据：`[hard_guard.py:73-132](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L73)`

### `load_session`

- 文件 / 函数：`local_life_agent/engine/subgraphs/intake_guard_router.py:153-177`
- 读取：`session_id`
- 写入：
  - `session_state`
  - `session_state_before`
  - `session_state_after`
  - `current_shop`
  - `last_recommendation_list`
  - `active_constraints`
  - `comparison_result`
  - `pending_clarification`
  - `clarification_request`
  - `active_turn_result`
  - `active_turn_route`
  - `restored_task`
  - `comparison_targets`
  - `recommendation_candidates`
  - `pending_check_result`
  - `merge_clarification_result`
  - `clarification_result`
- 结论：`load_session` 发生在 `basic_validate` 之前
- 证据：`[intake_guard_router.py:153-177](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L153)`

### `active_turn_resolver`

- 文件 / 函数：`local_life_agent/engine/subgraphs/active_turn_resolver.py:458-657`
- 读取：`raw_text` / `normalized_text`、`session_state_before.pending_clarification`
- 写入：`active_turn_result`、事件日志；外层 `h_active_turn_resolver_outer` 额外写 `active_turn_route`（行 674-685）
- 行为：不仅处理 pending reply，还包含 topic switch、规则、模糊匹配、可选 bounded LLM
- **跨层依赖**：`_semantic_reply_frame`（行 219-228）调用 `extract_slots(text, "local_life")`，即 `slot_extractor`，形成第 1 层节点对第 2 层语义规则模块的跨层调用
- **`_should_treat_as_topic_switch`**（行 533-595）使用 `"附近/火锅/推荐/优惠券/有券/营业/哪家/怎么样/好吃/评价/距离/多远/怎么去/怎么走/开门"` 作为话题切换启发式关键词
- 证据：
  - `[active_turn_resolver.py:458-525](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L458)`
  - `[active_turn_resolver.py:539-595](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L539)`
  - `[active_turn_resolver.py:603-657](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py#L603)`

### `top_intent_router`

- 文件 / 函数：`local_life_agent/engine/subgraphs/intake_guard_router.py:220-268`（⚠️ 不存在独立的 `top_intent_router_handler.py`）
- 读取：`normalized_text`
- 写入：`top_intent`、`error_code`、`error_message`、`top_intent_router_llm_available`、`top_intent_router_backend`、`top_intent_router_error_type`、`top_intent_router_error_message`、`top_intent_source`、`final_response`
- 行为：
  - 调用 `parse_top_intent`（intent_parser.py:760-875），LLM 分类，结果是单一 `TopIntent`
  - 对于 `invalid`/`chat`/`capability`/`unsafe`/`out_of_scope`，直接写入固定 `final_response`（行 241-249）
  - 对于 `local_life`，清空 `error_code`/`error_message`（行 253-255）
  - 不写 `response_mode`/`top_intent_route`——这些由外层 `h_intake_guard_router` 统一写（行 119-137）
- 关键细节：
  - `final_response` 写入 5 种固定回复，编码为 UTF-8 raw bytes（中文硬编码）
- 证据：
  - `[local_life_agent/engine/subgraphs/intake_guard_router.py:220-268](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L220)`（函数体）
  - `[local_life_agent/engine/subgraphs/intake_guard_router.py:241-249](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L241)`（final_response 写入）
  - `[local_life_agent/engine/subgraphs/intake_guard_router.py:115-137](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L115)`（外层路由决策）

### `merge_clarification`

- 文件 / 函数：
  - 外层：`local_life_agent/engine/subgraphs/merge_clarification.py:36-57`（`h_merge_clarification`）
  - 内部核心：`_h_check_pending` 行 60-194（~135 行，7 个分支）
- 读取：`pending_clarification`、`raw_text` / `normalized_text`、`session_state`
- 内部调用 `handle_clarification_reply`（`clarification.py:533-1046`，~514 行超长函数）
- 写入：
  - `pending_check_result`、`merge_clarification_result`、`clarification_result`、`clarification_resolution`、`resume_strategy`、`missing_slot_type`、`task_type_source`
  - 7 个分支各自写不同字段组合：
    | 分支 | 行号 | 写/清空的关键字段 |
    |---|---|---|
    | `restore` | 83-122 | 写 18+ 字段：`pending_clarification=None`、`restored_task`、`semantic_frame`、`task_type`、`task_type_source`、`resolved_target`、`resolve_shop_result`、`comparison_targets`、`selected_candidate`、`current_shop`、`selected_index`、`clarification_request=None`、`final_response=""` |
    | `topic_switch` | 124-149 | 清零 8 字段 + 清候选 + `final_response=""` |
    | `cancelled` | 151-163 | `pending_clarification=None`、`clarification_request=None`、`final_response=""` |
    | `expired` | 165-177 | `pending_clarification=None`、`final_response=result.get(...)` |
    | `invalid` | 179-189 | `final_response=result.get(...)` |
    | `out_of_range` | 179-189 | `final_response=result.get(...)` |
    | `pass` | 191-193 | 几乎无写 |
- 证据：`[merge_clarification.py:36-194](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/merge_clarification.py#L36)`

### `understanding_subgraph`

- 文件 / 函数：`local_life_agent/engine/subgraphs/understanding_subgraph.py:38-417`
- 读取：`normalized_text`、`top_intent`、`session_state_before`
- 写入：`semantic_frame`、`error_code`、`error_message`、`semantic_source`、`llm_backend`、`fallback_reason`、`llm_called`、`understanding_route`、`response_mode`
- 行为：
  - `_h_semantic_parse`（行 89-203）调用 LLM，返回 SemanticFrame；若失败则写 `error_code`
  - `_h_slot_extractor`（行 206-228）做规则补强（merchant_mentions、deictic_references、ordinal_references）
  - `_h_frame_validator`（行 231-255）做确定性验证，写 `error_code`
  - `_h_context_recovery`（行 258-417）做上下文恢复，可能写 `pending_clarification`、`resolved_target`、`comparison_targets`
- 关键细节：
  - `error_code` 在两个检查点影响路由：行 43（semantic_parse 后）和行 57（validator+recovery 后）
  - `_h_slot_extractor` 在此子图中只做 anchor 补强（mentions、deictic、ordinal），**不**覆盖 task_type
  - 但 `slot_extractor.extract_slots` 在其他模块（clarification.py:542、active_turn_resolver.py:221、intent_parser.py:619）被调用时**会**覆盖 task_type
- 证据：
  - `[understanding_subgraph.py:38-81](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L38)`
  - `[understanding_subgraph.py:89-203](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L89)`
  - `[understanding_subgraph.py:206-255](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L206)`
  - `[understanding_subgraph.py:258-417](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L258)`

### `state_update_plan`

- 文件 / 函数：`local_life_agent/engine/subgraphs/state_update_plan.py:34-194`
  - 外层：`h_state_update_plan_outer` 行 34-40
  - `_h_state_update_plan` 行 48-135（调用 `plan_state_update` + `build_state_patch`）
  - `_h_persist_session` 行 138-190（实际写回 session store）
  - `_h_emit_response` 行 193-194（只做日志）
- 读取：
  - `resolve_shop_result` / `resolved_target`
  - `pending_clarification`
  - `task_type`
  - `comparison_targets`
  - `comparison_target_resolution`
  - `semantic_frame`
  - `last_recommendation_list`
  - `active_constraints`
  - `user_location`
  - `evidence_pack`
  - `tool_result_set` / `tool_results`
  - `validated_plan` / `execution_plan`
  - `merge_clarification_result`、`restored_task`、`reference_resolution_source`、`task_type_source`、`clarification_resolution`、`resume_strategy`、`active_turn_result`、`resolution_stage` 等
- 写入：
  - `state_update_plan`（SessionWriteDirective）
  - `session_state`（写回 store）
  - `session_state_after`
  - `current_shop`、`last_recommendation_list`、`active_constraints`、`comparison_result`、`pending_clarification`、`comparison_targets`
- **关键事实**：session store 只有一个显式 `store.save(...)`（行 179），但 `_h_persist_session` 在行 160-177 还有**两段额外写逻辑**（不受 SessionWriteDirective 控制）：
  1. 行 160-168：如果 `comparison_target_resolution.status == "RESOLVED"`，直接写 `session_state.comparison_targets`
  2. 行 169-177：如果 `comparison_result.rows` 有值且无 pending，也写 `session_state.comparison_targets`
- 证据：
  - `[state_update_plan.py:48-135](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L48)`（_h_state_update_plan）
  - `[state_update_plan.py:138-179](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L138)`（_h_persist_session，含额外写逻辑）
  - `[session/store.py:17-31](D:/javacode/hm-dianping/local_life_agent/session/store.py#L17)`（store.save()）

## 真实字段基线

### `GraphState`

- 定义：`local_life_agent/domain/graph_state.py:38-260`
- 特征：
  - `raw_text`、`normalized_text`、`input_type`
  - `top_intent`、`task_type`
  - `semantic_frame`、`schema_validation_result`、`grounding_status`、`missing_slot_type`
  - `pending_clarification`、`clarification_request`
  - `current_shop`、`last_recommendation_list`、`active_constraints`、`comparison_targets`
  - `final_response`、`error_code`、`error_message`
  - `session_state_before`、`session_state_after`
  - `response_mode`、`intake_route`、`merge_clarification_route`、`understanding_route`
- 关键结论：`final_response`、`error_code`、`error_message` 都是 GraphState 级共享字段，不是某个节点私有字段
- 证据：`[graph_state.py:44-258](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L44)`

### `SessionState`

- 定义：`local_life_agent/domain/state.py:89-150`
- 现有字段已经混合了：
  - `current_shop`
  - `canonical_shop_entity`
  - `canonical_shop_entities`
  - `shop_resolution_trace`
  - `last_recommendation_list`
  - `active_constraints`
  - `pending_clarification`
  - `comparison_targets`
  - `comparison_result`
  - `suggested_shop`
  - `last_candidate_spec`
  - `last_candidate_set`
  - `active_goal`
  - `review_results`
  - `last_decision_plan`
  - `replan_counters`
- 关键结论：SessionState 已经很胖，且把多轮上下文、推荐列表、比较集合、目标、重规划计数混在一起
- 证据：`[state.py:105-150](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L105)`

### `SemanticFrame`

- 定义：`local_life_agent/domain/schemas.py:248-324`
- 真实字段覆盖：
  - `top_intent` / `intent`
  - `task_type`
  - `primary_task`
  - `workflow_hint`
  - `comparison_intent` / `comparison_structure` / `comparison_facets`
  - `exploration_stages`
  - `missing_slots`
  - `preferences` / `preference_signals`
  - `scene` / `time` / `location` / `category`
  - `shop_target` / `reference`
  - `location_reference` / `shop_reference` / `ordinal_reference` / `deictic_reference`
  - `facets` / `facet_set` / `target_resolution` / `conflicting_facets` / `ranking_policy`
  - `merchant_mentions` / `brand_mentions` / `branch_mentions` / `surface_hints` / `alias_hints` / `reference_mentions`
  - `comparison_targets` / `ordinal_references` / `deictic_references`
  - `focused_facets` / `comparison_focus`
  - `hard_constraints` / `soft_preferences` / `ranking_signals`
  - `follow_up`
  - `confidence`
  - `need_context`
  - `constraint_update`
  - `new_task_override`
  - `cancel_intent`
- 关键结论：SemanticFrame 已承担大量上下文、比较、偏好、跟进语义，实际上比“纯意图帧”更宽
- 证据：`[schemas.py:248-324](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L248)`

### `PendingClarification`

- 定义：`local_life_agent/domain/schemas.py:704-719`
- 字段：
  - `pending_id`
  - `original_task_type`
  - `candidate_targets`
  - `missing_slot_type`
  - `expected_reply_type`
  - `created_at`
  - `expires_at`
  - `original_text`
  - `original_semantic_frame`
  - `reason`
  - `source_node`
  - `already_resolved_targets`
  - `ambiguous_target_slot`
  - `resume_strategy`
- 结论：PendingClarification 本身已经带 TTL
- 证据：`[schemas.py:704-719](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L704)`、`[target/clarification.py:388-445](D:/javacode/hm-dianping/local_life_agent/target/clarification.py#L388)`

### `TopIntent`

- 定义：`local_life_agent/domain/enums.py:6-12`
- 取值只有：
  - `local_life`
  - `capability`
  - `chat`
  - `invalid`
  - `unsafe`
  - `out_of_scope`
- 结论：天然单标签，没有 mixed intent 结构
- 证据：`[enums.py:6-12](D:/javacode/hm-dianping/local_life_agent/domain/enums.py#L6)`

## 关键结论直答

1. `load_session` 是否在 `basic_validate` 之前？
   - 是，`receive_input -> load_session -> basic_validate`
   - 证据：`[intake_guard_router.py:45-48](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L45)`

2. `final_response` 是否在第一层多个节点中被提前写入？
- 是，至少 `basic_validate`（`intake_guard_router.py:183-189`）、`hard_guard`（`intake_guard_router.py:213-216`）、`top_intent_router`（`intake_guard_router.py:241-249`）、`merge_clarification`（`merge_clarification.py:118-170`）都会写
    - 证据：`[intake_guard_router.py:183-189](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L183)`、`[intake_guard_router.py:213-216](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L213)`、`[intake_guard_router.py:241-249](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L241)`、`[merge_clarification.py:118-170](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/merge_clarification.py#L118)`

3. `error_code` / `error_message` 是否是多个阶段共用的全局字段？
   - 是，GraphState 级共享，且 `basic_validate`、`top_intent_router`、`understanding_subgraph` 都会写
   - 证据：`[graph_state.py:212-213](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L212)`、`[intake_guard_router.py:183-195](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L183)`、`[understanding_subgraph.py:114-187](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py#L114)`

4. `pending_clarification` 和 `clarification_request` 是否重复表达同一个对象？
   - 是，`load_session` 直接把二者都指向 `existing.pending_clarification`
   - 证据：`[intake_guard_router.py:159-168](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L159)`

5. `hard_guard` 是否包含业务关键词放行逻辑？
   - 是，命中 `_BUSINESS_PATTERNS` 就直接 `safe`
   - 证据：`[hard_guard.py:25-60](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L25)`、`[hard_guard.py:93-99](D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py#L93)`

6. `top_intent_router` 是否只支持单标签 intent？
   - 是，`TopIntent` 只有一个枚举值，不支持混合标签

7. `top_intent_router` 对“便宜一点的呢 / 那有券吗 / 第二个怎么样”是否有足够上下文？
   - 现状是“部分有”，但没有独立的 query rewrite / contextualized turn 模型；依赖 session summary、active_turn_resolver、semantic frame 的隐式上下文
   - 证据：`[intent_parser.py:1021-1037](D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py#L1021)`、`[session_context_summary.py:73-162](D:/javacode/hm-dianping/local_life_agent/domain/session_context_summary.py#L73)`

8. 是否存在明确的 `query rewrite` / `conversation contextualization` / `contextualized turn` 层？
   - 没有找到独立模型或节点

9. `active_turn_resolver` 是否只处理 pending clarification？
   - 不是，它还承担 topic switch、规则、模糊匹配、可选 bounded LLM、语义 override

10. `merge_clarification restore` 是否能处理“选择 + 新增约束 / 新增 facet / 新任务”？
    - 能处理一部分，`constraint_update`、`new_task_override`、比较选择、位置补充都已存在；但没有显式 `restore_with_delta` 契约

11. `slot_extractor` 是否只做 anchor 提取？
    - 不是，它会决定 `task_type`、`primary_task`、`workflow_hint`、`preferences`、`comparison_targets`、`focused_facets` 等

12. `context_recovery`、`active_turn_resolver`、`slot_extractor`、`target_resolve` 是否职责重叠？
    - 是，均参与引用消解、比较目标、选店、topic switch 相关判断

13. `SessionState` 是否过胖？
    - 是，已混合当前店、推荐列表、比较集合、活跃约束、活跃目标、重规划计数等

14. 是否存在明确的 `FocusContext` 或等价模型？
    - 没有找到

15. 状态写回是否真的只有 `state_update_plan` 一个入口？
    - 运行时 session store 的显式 `save(...)` 只有 `state_update_plan._h_persist_session`
    - 但 GraphState 上的中间字段会在第一层多个节点被提前改写

16. `SessionState` 是否有 TTL / freshness / generated_at / expires_at 机制？
    - SessionState 本身没有；只有 `SessionValueMeta.ttl` 和 `PendingClarification.expires_at`

17. 营业状态、距离、优惠券、推荐列表等跨轮复用时是否有过期判断？
    - 有零散的 TTL / freshness 元信息，但不是统一的第一层契约

18. 用户位置上下文是否在第一层有清晰边界？
    - 不够清晰，当前是 `UserContext` + `build_missing_user_context()` + `GraphState.user_location` 混用

19. `InMemorySessionStore` 是否只是开发态实现？
    - 代码上就是进程内内存字典，没有 Redis / DB 边界

20. 第一层是否有统一 trace schema？
    - 没有第一层专属 `FirstLayerTrace`；现有只有更通用的 event / trace 工具

## 补充分析：六个关键点的真实代码证据

### A. Mixed Intent 的结构化表达

**真实代码现状：**

- `TopIntent`（`enums.py:6-12`）是单标签枚举，只有 6 个值，没有 mixed / composite / secondary 字段
  - `local_life` / `capability` / `chat` / `invalid` / `unsafe` / `out_of_scope`
- `_h_top_intent_router`（`intake_guard_router.py:220-268`）的 LLM 调用 `parse_top_intent`（`intent_parser.py:760-875`）接受 `top_intent` 返回格式，强制模型选一个标签
- 当用户说"你好，帮我推荐火锅"时，LLM 在 `greeting`（对应 `chat`）和 `local_life` 之间只能二选一
- 当前没有 `MixedIntent` / `IntentComponent` / `intent_scores` / `secondary_intent` 等结构

**证据：**

- `[enums.py:6-12](D:/javacode/hm-dianping/local_life_agent/domain/enums.py#L6)` — TopIntent 只有 6 个枚举值
- `[intake_guard_router.py:220-268](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L220)` — 路由逻辑只判断单一 top_intent
- `[intent_parser.py:760-875](D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py#L760)` — parse_top_intent 的 LLM 调用
- 仓库内没有 `MixedIntent` / `intent_scores` / `secondary_intent` 命名命中

### B. ContextualizedTurn 与 SemanticFrame 的权威边界

**真实代码现状：**

- `SemanticFrame`（`schemas.py:248-324`）约 75 个字段，已经混杂以下完全不同的职责层：

  | 职责层 | 字段示例 | 行号 |
  |---|---|---|
  | Intent 分类 | `top_intent`, `intent` | 252-253 |
  | Query 改写 | `follow_up`, `constraint_update`, `new_task_override` | 316-320 |
  | 任务类型 | `task_type`, `primary_task`, `workflow_hint` | 254-256 |
  | 偏好提取 | `preferences`, `preference_signals`, `hard_constraints`, `soft_preferences` | 258-259, 310-311 |
  | 比较结构 | `comparison_intent`, `comparison_structure`, `comparison_facets` | 260-262 |
  | 探索阶段 | `exploration_stages` | 263 |
  | 槽位缺失 | `missing_slots` | 268 |
  | 场景/时间/位置/品类 | `scene`, `time`, `location`, `category` | 269-272 |
  | 店铺/引用 | `shop_target`, `reference`, `merchant_mentions`, `brand_mentions`, `branch_mentions` | 275-282 |
  | 锚点引用 | `ordinal_references`, `deictic_references`, `location_reference`, `shop_reference`, `ordinal_reference`, `deictic_reference` | 277-280 |
  | Facet 规划 | `facets`, `facet_set`, `target_resolution`, `conflicting_facets`, `focused_facets`, `comparison_focus` | 283-290 |
  | 排序策略 | `ranking_policy`, `ranking_signals` | 291-292 |
  | 别名/表层 | `surface_hints`, `alias_hints`, `reference_mentions` | 282 |

- 仓库内没有 `ContextualizedTurn` 命名命中
- 当前上下文化的产出方式：`SessionContextSummary`（`session_context_summary.py:32-162`）被注入 LLM prompt 做隐式上下文化，没有显式 rewrite 产物

**边界结论：**

- `ContextualizedTurn`（新）只关注"当前 query 在上下文中完整表达是什么"，是 `SemanticFrame` 的前置输入
- `SemanticFrame` 应该缩窄职责：只做 "用户意图+槽位的事实提取"，不做 facet 规划、排序策略等

### C. FocusContext 的 item 级字段规范

**真实代码现状：**

- 焦点状态分散在 `SessionState`（`state.py:105-150`）的多个字段：
  ```python
  current_shop: ShopEntity | None                # 当前单店（如果有）
  last_recommendation_list: list[dict]            # 上次推荐的列表
  comparison_targets: list[dict]                  # 比较目标列表
  last_candidate_set: CandidateSet | None         # 最近候选集
  active_goal: str | None                         # 活跃目标字符串
  ```

- `context_recovery`（`understanding_subgraph.py:258-417`）在解析引用时需要从这些字段推断焦点优先级，但没有统一模型
- 现有方案草案的 `focus_items: list[dict]` 定义过于宽泛，缺乏每个 item 的字段约束

**需要明确的 item 级字段：**

```python
FocusItem:
    item_id: str                        # 唯一标识
    focus_type: Literal[                # 焦点类型
        "shop_entity",                  # 单店（current_shop）
        "recommendation_ranked",        # 推荐列表（有排序）
        "comparison_set",               # 比较集合
        "candidate_set",                # 候选集
        "general_search"                # 泛搜索（无明确目标）
    ]
    entity: dict                        # 实际实体数据（兼容 ShopEntity / dict）
    entity_source: str                  # 来源：tool_result / recommendation / LLM / user_input
    category: str | None                # 品类标签
    reference_priority: int             # 引用优先级（越高越优先匹配"这家"）
    mention_support: list[str]          # 被哪些用户 mention 支持过
    generated_at: str                   # 生成时间
    expires_at: str | None              # 过期时间
    freshness_policy: str | None        # "reuse_always" / "reuse_if_within_ttl" / "onetime"
```

### D. load_session 是否应后移到 basic_validate 之后

**真实代码调用顺序（`intake_guard_router.py:45-47`）：**

```
1. _h_receive_input       — 组装 TurnInput
2. _h_load_session        ← 当前在第 2 步
3. _h_basic_validate      ← 校验 raw_text
4. _h_normalize_text
5. _h_hard_guard
6. _h_active_turn_resolver
7. _h_top_intent_router
```

**`_h_load_session` 的副作用分析（`intake_guard_router.py:153-177`）：**

- 从 store 读 `SessionState`（I/O 操作）
- 展开写入 15+ 个 GraphState 字段：`session_state`, `session_state_before`, `session_state_after`, `current_shop`, `last_recommendation_list`, `active_constraints`, `comparison_result`, `pending_clarification`, `clarification_request`, `active_turn_result`, `active_turn_route`, `restored_task`, `comparison_targets`, `recommendation_candidates`, `pending_check_result`, `merge_clarification_result`, `clarification_result`

**后移的影响分析：**

- 如果后移到 `_h_basic_validate` 之后（即步骤 2.5 → 步骤 4）：
  - ✅ 空输入 / 超长输入 / 非法输入不走 session I/O
  - ❌ `_h_active_turn_resolver`（步骤 6）需要 `session_state.pending_clarification` 做 topic switch 检测
  - ❌ basic_validate 当前也检查 pending 状态（`validator.py:21-62` 无依赖 session），但如果后移则 validate 不再能感知 session 状态
  - ↔️ `hard_guard` 不需要 session，不受影响

**结论：**

- 简单"后移"不可行，因为 `active_turn_resolver` 和 `top_intent_router` 都依赖 session
- 可行的折中方案：
  1. 只把 session load 的"写 GraphState 展开字段"延迟到 validate 之后
  2. 或者：先 `basic_validate`，再只读 session（不展开），然后继续 normalize → hard_guard → active_turn_resolver → 展开
  3. 或者：validate 通过前，session 只做轻量校验级的读（如检查 session_id 有效性），不加载完整 SessionState

### E. InMemorySessionStore 到 Redis / DB 的生产迁移接口

**真实代码接口（`session/store.py:11-61`）：**

```python
class InMemorySessionStore:
    def load(self, session_id: str) -> SessionState | None
    def save(self, session_id: str, state: SessionState) -> None
    def clear(self, session_id: str) -> None
    def snapshot() -> dict[str, SessionState]  # 调试用
```

- 进程内 `dict[str, SessionState]`
- 进程级单例 `get_session_store()`（`store.py:44-60`）
- 无 TTL、无持久化、无并发控制、无多实例共享
- 序列化隐含：`SessionState` 是 Pydantic BaseModel（`state.py:89`），可 `model_dump_json()` / `model_validate_json()`

**生产迁移所需扩展：**

```python
class SessionStore(ABC):                    # 抽象基类
    @abstractmethod
    def load(self, session_id: str) -> SessionState | None
    @abstractmethod
    def save(self, session_id: str, state: SessionState, ttl: int | None = 1800) -> None
    @abstractmethod
    def delete(self, session_id: str) -> None
    @abstractmethod
    def touch(self, session_id: str, ttl: int | None = 1800) -> None  # 刷新 TTL
```

需要分离的两个职责：
1. **序列化层**：`SessionState ↔ bytes`（`model_dump_json(include=...)` 可按分区增量写入）
2. **后端层**：RedisHash / RedisJSON / Postgres JSONB / Memory 等实现

当前 `_h_load_session` 的"展开写 GraphState"本质上就是一次反序列化 + 字段投影，所以序列化策略可以同时优化 load 开销。

### F. 第一层和第二层 target_resolve 的职责切分

**第一层：`understanding_subgraph._h_context_recovery`（`understanding_subgraph.py:258-417`）**

- 做 **预解析** / **快速分辨**
- 调用 `context_recovery.py` 中的 `resolve_contextual_references` → 解析比较目标、店铺引用
- 写入 `resolved_target`, `comparison_targets`, `pending_clarification`
- 对显式 mention 调 `resolve_shop` 做一次快速条目级解析
- 主要目的：判断"是否需要澄清"以及"当前引用指向什么"
- 如果 ambiguous → 写 `pending_clarification`，不清入第二层

**第二层：`planning_subgraph._h_target_resolve`（`planning_subgraph.py:571-`）**

- 做 **全解析** / **证据级解析**
- 构建完整的 `CandidateSet`，对 shop entity 做完整解析（调用真正 shop API）
- 调用 `resolve_comparison_targets()` / `resolve_shop_entity()` 做详细实体级解析
- 区分 `recommendation` / `single_shop_query` / `comparison` 三种路径，各自走不同 resolver
- 调用 `resolve_shop_candidates` 做候选排名
- 有 `candidate_review` 步骤（`planning_subgraph.py:786-825`）做候选审查
- 如果 ambiguous → 也写 `pending_clarification`（第二层自己的澄清）

**重叠问题：**

- 两家店都做店铺解析和比较目标解析
- 第一层解析结果（`resolved_target`）被第二层消费（`planning_subgraph.py:597-632`），但解析路径可不同
- 第一层用的是规则/轻量级 resolver，第二层用的是完整 entity resolver + tool call
- 如果第一层解析出 shop A，第二层解析出 shop B（或认定 ambiguous），就会产生矛盾

**建议职责切分：**

| 阶段 | 第一层 context_recovery | 第二层 target_resolve |
|---|---|---|
| 引用识别 | ✅ 识别"这家/那家/第一家"是引用 | ❌ 不再做引用识别 |
| 引用匹配 | ✅ 匹配到具体 focus_item | ❌ 不再做第一轮匹配 |
| 是否需要澄清 | ✅ 判定 ambiguous → pending_clarification | ❌ 不再做确认性澄清 |
| 实体全量解析 | ❌ 不做深度 entity resolve | ✅ 调 shop API / CandidateSet |
| 候选排名 | ❌ 不做排名 | ✅ 做全排名 |
| 比较目标详细展开 | ❌ 只做列表级别比较引用 | ✅ 做每个比较目标的完整 entity 解析 |
| 最终证据构建 | ❌ 不涉及 | ✅ 构建 tool plan 所需的证据 |

## 文档与代码偏差

以下是本次核对后，和常见架构拆解最容易混淆的地方：

- `intake_guard_router` 不是单纯"门卫节点"，它内部已经串了 `load_session`、`basic_validate`、`normalize_text`、`hard_guard`、`active_turn_resolver`、`top_intent_router`
- `merge_clarification` 不是单纯的"恢复澄清"，它已经能处理 topic switch、比较补槽、选项选择、位置补全、直接店铺解析
- `understanding_subgraph` 不是纯 LLM 解析，它还包含 `slot_extractor`、`frame_validator`、`context_recovery`
- `top_intent_router` 是单标签分类，没有 mixed intent 结构
- `SessionState` 里并没有单独的 `FocusContext`，而是用多个字段分散表达焦点
- `state_update_plan` 是唯一显式 session store 写入口，但不是唯一会改 GraphState 中间字段的入口

