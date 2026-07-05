# Phase 1 SemanticFrame Schema Completion Report

## 1. Conclusion

- `PHASE_1_STATUS`: `PASS`
- `CAN_ENTER_PHASE_2`: `true`
- `CAN_ENTER_PHASE_3`: `false`
- `Main conclusion`: 本轮已完成 `SemanticFrame` / `GraphState` / `GraphStateModel` 的 schema 补齐与兼容对齐，本地生活核心语义可以在 schema 层稳定表达；但 parser prompt、router 主决策、grounding、clarification resume 仍保留给后续阶段。

## 2. Scope

本轮只做 Phase 1 的 schema 与运行时状态承载能力补齐，未修改 prompt，也未重写 parser / router 主逻辑。

覆盖范围：

- `SemanticFrame` 字段补齐与标准化
- 语义枚举与 typed model 补齐
- `GraphState` / `GraphStateModel` 兼容字段对齐
- `SessionState` 边界确认与最小注释说明
- schema 相关测试补充

明确不做：

- Phase 2 / Phase 3 实现
- `local_life_parser.md` 修改
- `intent_parser.py` 主流程重写
- `slot_extractor.py` 重写
- `orchestration_router.py` 重写

## 3. Files Changed

| File | Change | Reason | Risk |
| --- | --- | --- | --- |
| [local_life_agent/domain/enums.py](/D:/javacode/hm-dianping/local_life_agent/domain/enums.py) | 新增语义源、grounding、偏好、过滤、引用、多轮、比较、缺失槽位枚举 | 让 schema 具备稳定的语义值域 | 低，均为兼容性枚举 |
| [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py) | 补齐 `SemanticFrame` 字段、typed model、validator、兼容镜像 | 让 LLM 解析结果有可落地的稳定 schema | 中，涉及字段镜像与兼容归一化 |
| [local_life_agent/domain/graph_state.py](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py) | 增加语义观测字段 | 让运行时 GraphState 承载 Phase 1 观测信息 | 低 |
| [local_life_agent/domain/graph_state_model.py](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state_model.py) | 增加兼容字段并镜像 `semantic_frame` 观测值 | 保持 dict 状态与验证模型一致 | 中，需避免 enum 字符串污染 |
| [local_life_agent/domain/state.py](/D:/javacode/hm-dianping/local_life_agent/domain/state.py) | 补充 SessionState 边界说明 | 明确语义观测留在 GraphState，不扩张会话对象 | 低 |
| [local_life_agent/tests/test_domain_schemas.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_domain_schemas.py) | 增加 schema 覆盖、序列化、GraphStateModel 兼容测试 | 验证 schema 能表达核心本地生活语义 | 低 |
| [local_life_agent/tests/test_semantic_parser.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_semantic_parser.py) | 增加 parser 输出与扩展 schema 的 roundtrip 测试 | 确认旧 parser 输出不被 schema 扩展破坏 | 低 |
| [local_life_agent/tests/test_semantic_router_policy_alignment.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_semantic_router_policy_alignment.py) | 增加 Phase 1 schema 字段兼容样例 | 确认 router 边界测试不因 schema 扩展失效 | 低 |

## 4. Existing Fields Reused

| Existing Field | Reused For | Notes |
| --- | --- | --- |
| `primary_task` | 任务主语义 | 继续承载 recommendation / comparison / single_shop_query |
| `merchant_mentions` | 商家提及 | 作为商家实体候选的旧入口 |
| `brand_mentions` | 品牌提及 | 与商家提及并行保留 |
| `branch_mentions` | 门店分店提及 | 兼容原有实体抽取 |
| `ordinal_references` | 序数引用 | 继续承载“第一家/第二家”这类指代 |
| `deictic_references` | 示指引用 | 继续承载“这家/那家”这类引用 |
| `reference` | 通用引用容器 | 用于兼容多种引用载体 |
| `comparison_targets` | 比较对象 | 继续作为比较对象集合 |
| `comparison_facets` | 比较维度 | 继续承载比较关注维度 |
| `comparison_focus` | 比较侧重点 | 用于 value_for_money / overall 等聚焦 |
| `preferences` | 软偏好旧载体 | 继续兼容当前 slot extractor 输出 |
| `hard_constraints` | 硬约束 | 继续作为确定性约束容器 |
| `soft_preferences` | 软偏好 | 继续作为排序/偏好容器 |
| `ranking_signals` | 排序信号 | 继续作为排序与推荐提示容器 |
| `follow_up` | 多轮补充信息 | 继续兼容旧 follow-up 结构 |
| `need_context` | 是否需要上下文 | 继续用于澄清与上下文恢复 |
| `semantic_source` | 旧语义来源 | 保持兼容，并镜像到 `parse_source` / `semantic_parse_source` |
| `fallback_reason` | 兜底原因 | 保持现有行为不变 |
| `llm_called` | 是否调用 LLM | 保持现有观测逻辑 |
| `llm_backend` | LLM 后端标识 | 保持现有观测逻辑 |

## 5. New / Standardized Fields

| Field | Type | Purpose | Compatible With Old Schema? |
| --- | --- | --- | --- |
| `intent` | `TopIntent | None` | 语义意图镜像，和 `top_intent` 同步 | `true` |
| `comparison_structure` | `ComparisonStructure` | 标准化比较结构表达 | `true` |
| `exploration_stages` | `list[ExplorationStageSpec]` | 表达 scene / time / constraints 的探索阶段 | `true`，可从旧字符串回退 |
| `preference_signals` | `list[SemanticPreference]` | 标准化偏好 signal | `true` |
| `filter_signals` | `list[SemanticFilter]` | 标准化过滤 signal | `true` |
| `location_reference` | `SemanticReference | None` | 位置引用 | `true` |
| `shop_reference` | `SemanticReference | None` | 商家引用 | `true` |
| `ordinal_reference` | `SemanticReference | None` | 序数引用 | `true` |
| `deictic_reference` | `SemanticReference | None` | 示指引用 | `true` |
| `parse_source` | `SemanticParseSource` | 标准化语义解析来源 | `true`，可由 `semantic_source` 镜像 |
| `semantic_parse_source` | `SemanticParseSource` | 标准化语义解析来源镜像 | `true`，可由 `semantic_source` 镜像 |
| `grounding_status` | `GroundingStatus` | 语义 grounding 状态观测 | `true` |
| `discourse_marker` | `str` | 多轮语篇标记 | `true` |
| `constraint_update` | `bool` | 约束更新标记 | `true` |
| `new_task_override` | `bool` | 新任务覆盖标记 | `true` |
| `cancel_intent` | `bool` | 取消意图标记 | `true` |
| `missing_slot_type` | `MissingSlotType` | 标准化澄清缺失槽位类型 | `true`，可与 `missing_slots` 对齐 |
| `schema_validation_result` | `dict[str, Any]` | GraphState 运行时 schema 校验结果 | `true` |

## 6. Validators Added

| Validator | Purpose | Failure Behavior |
| --- | --- | --- |
| `confidence` clamp | 保证置信度在 `0.0 ~ 1.0` | 超界会被裁剪到边界值 |
| `intent` / `top_intent` mirror | 保证新旧语义意图字段一致 | 不一致时抛 `ValueError` |
| `parse_source` / `semantic_parse_source` enum coercion | 保证解析来源值域稳定 | 非法值回落到 `unknown` |
| `grounding_status` enum coercion | 保证 grounding 观测值域稳定 | 非法值回落到 `unknown` |
| `comparison_intent` gate | 保证比较语义有可表达载体 | 缺少 targets / structure / facets 时抛 `ValueError` |
| `cancel_intent` gate | 保证取消意图不和新任务覆盖混用 | 同时为真时抛 `ValueError` |
| `missing_slots` / `missing_slot_type` alignment | 避免缺失槽位双重冲突表达 | 不一致时抛 `ValueError` |
| `exploration_stages` coercion | 兼容旧字符串阶段并标准化为结构体 | 旧字符串自动转成 `stage_type` |
| reference signal coercion | 兼容旧 dict / string 引用载荷 | 自动补齐 `reference_type` |

## 7. Semantic Coverage

| Semantic Need | Supported? | Field / Model | Test |
| --- | --- | --- | --- |
| `value_for_money` | `true` | `preference_signals` + `SemanticPreference(preference_type=value_for_money)` | `test_core_semantic_axes_are_supported` |
| `relative_price_preference` | `true` | `preference_signals` + `SemanticPreference(preference_type=relative_price_preference)` | `test_core_semantic_axes_are_supported` |
| `scene_preference` | `true` | `PreferenceType.scene_preference` | `test_preference_filter_reference_and_multiturn_models_roundtrip` |
| `quality_preference` | `true` | `PreferenceType.quality_preference` | 枚举覆盖测试 |
| `coupon_filter` | `true` | `SemanticFilter(filter_type=coupon_filter)` | `test_preference_filter_reference_and_multiturn_models_roundtrip` |
| `open_now_filter` | `true` | `SemanticFilter(filter_type=open_now_filter)` | `test_preference_filter_reference_and_multiturn_models_roundtrip` |
| `distance_preference` | `true` | `PreferenceType.distance_preference` | 枚举覆盖测试 |
| `location_reference` | `true` | `location_reference` / `SemanticReference` | `test_core_semantic_axes_are_supported` |
| `shop_reference` | `true` | `shop_reference` / `SemanticReference` | `test_core_semantic_axes_are_supported` |
| `ordinal_reference` | `true` | `ordinal_reference` / `SemanticReference` | `test_core_semantic_axes_are_supported` |
| `deictic_reference` | `true` | `deictic_reference` / `SemanticReference` | `test_core_semantic_axes_are_supported` |
| `constraint_update` | `true` | `constraint_update: bool` | `test_core_semantic_axes_are_supported` |
| `new_task_override` | `true` | `new_task_override: bool` | `test_phase1_schema_fields_can_be_serialized_without_router_changes` |
| `cancel_intent` | `true` | `cancel_intent: bool` | `test_cancel_intent_cannot_coexist_with_new_task_override` |
| `discourse_marker` | `true` | `discourse_marker: str` | `test_core_semantic_axes_are_supported` |
| `comparison_structure` | `true` | `ComparisonStructure` | `test_core_semantic_axes_are_supported` |
| `comparison_targets` | `true` | existing field | `test_core_semantic_axes_are_supported` |
| `comparison_facets` | `true` | existing field | existing comparison tests |
| `exploration_stages` | `true` | `ExplorationStageSpec` | `test_exploration_and_missing_slot_types_are_supported` |
| `missing_slot_type` | `true` | `MissingSlotType` | `test_exploration_and_missing_slot_types_are_supported` |
| `grounding_status` | `true` | `GroundingStatus` | `test_roundtrip_preserves_parse_and_grounding_metadata` |
| `confidence` | `true` | `SemanticFrame.confidence` | `test_core_semantic_axes_are_supported` |
| `semantic_parse_source` | `true` | `SemanticParseSource` | `test_roundtrip_preserves_parse_and_grounding_metadata` |

## 8. GraphState / SessionState Compatibility

- `GraphState` 已新增 `semantic_parse_source`、`schema_validation_result`、`grounding_status`、`missing_slot_type`，可直接承载 Phase 1 的语义观测信息。
- `GraphStateModel` 已同步补齐同名字段，并在验证后从 `semantic_frame` 镜像 `semantic_parse_source`、`grounding_status`、`missing_slot_type`。
- `SessionState` 未被扩成无边界大对象。
- `StateUpdatePlan` 的写回边界未改变，`current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 仍保留 deterministic 写回控制。
- 这次没有把语义观测写进 persistent session 主结构，避免会话对象膨胀。

## 9. Tests Added or Updated

| Test File | What Was Added / Updated |
| --- | --- |
| [local_life_agent/tests/test_domain_schemas.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_domain_schemas.py) | 新增 `SemanticFrame` 核心语义、探索阶段、缺失槽位、parse source / grounding、GraphStateModel roundtrip、枚举覆盖测试 |
| [local_life_agent/tests/test_semantic_parser.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_semantic_parser.py) | 新增 parser 输出与扩展 schema 的 roundtrip 测试，确认旧语义来源兼容 |
| [local_life_agent/tests/test_semantic_router_policy_alignment.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_semantic_router_policy_alignment.py) | 新增 Phase 1 schema 字段可序列化样例，确认不影响现有路由对齐测试 |

## 10. Regression Commands Run

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_domain_schemas.py -q
pytest local_life_agent/tests/test_semantic_parser.py -q
pytest local_life_agent/tests/test_semantic_router_policy_alignment.py -q
pytest local_life_agent/tests/test_router_rule_policy_guard.py -q
pytest local_life_agent/tests/test_workflow_registry.py -q
pytest local_life_agent/tests/test_workflow_runner.py -q
```

结果：

- `python -m compileall local_life_agent`: 通过
- `test_domain_schemas.py`: `66 passed`
- `test_semantic_parser.py`: `29 passed`
- `test_semantic_router_policy_alignment.py`: `5 passed`
- `test_router_rule_policy_guard.py`: `40 passed`
- `test_workflow_registry.py`: `5 passed`
- `test_workflow_runner.py`: `3 passed`

## 11. Known Remaining Issues

以下问题明确留给 Phase 2 / Phase 3：

- parser prompt 未改；
- router 仍未切换为只消费 `SemanticFrame`；
- keyword rule 仍未全部降级；
- grounding 仍未在本阶段修复；
- clarification resume 仍未在本阶段修复。

补充说明：

- 当前 `SemanticFrame` 的 `parse_source` / `semantic_parse_source` 仍保留对旧 `semantic_source` 的兼容镜像，这是刻意保留，不是遗漏。

## 12. Final Gate

- `PHASE_1_SCHEMA_READY`: `true`
- `SEMANTIC_FRAME_CAN_EXPRESS_CORE_LOCAL_LIFE_SEMANTICS`: `true`
- `GRAPH_STATE_COMPATIBLE`: `true`
- `SESSION_STATE_NOT_OVEREXPANDED`: `true`
- `BACKWARD_COMPATIBILITY_KEPT`: `true`
- `CAN_START_PHASE_2`: `true`
- `CAN_START_PHASE_3`: `false`

