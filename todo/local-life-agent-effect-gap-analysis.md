# 本地生活 Agent 效果增强问题排查报告

> 排查日期: 2026-06-10
> 排查范围: learning-agent-service 全代码库
> 排查方式: 只读代码分析 + 测试运行，未修改任何业务代码

---

## 0. 总结结论

### 当前整体成熟度: **65/100**

系统在路由、单店/多店区分、证据过滤、质量门控方面已有较好基础。但缺少显式的 intent 成功标准、统一的追问策略管理、结构化比较模板、按 intent 分类的黄金集、以及问题类型-失败类型映射。

### 最核心的 3 个问题（排查当时结论）

1. **比较能力不完整**: `answer_style="comparison"` 在 `validate_answer_against_contract()` 中直接返回原文，无结构化对比模板。问"A和B哪个更适合约会"只能靠 LLM prompt 硬撑，没有按维度对比、差异分析、最终建议的标准输出。
2. **黄金集严重不足**: 仅 7 个用例，缺少营业状态、距离、比较、澄清、兜底等关键 intent 的覆盖。无自动化 CI 集成。
3. **追问策略分散且无统一管理**: 追问逻辑分散在 `target_shop_policy.py`、`answer_contract.py`、`answer_structure_composer.py`、`phase3_review.py` 等 4+ 个文件中，没有统一的追问策略管理器。

### 最应该优先改的 3 个方向（排查当时结论）

1. **建立问题类型-失败类型映射表** (P0) — 当前无显式映射，修问题全靠人工猜
2. **扩展黄金集到 50+ 用例** (P0) — 覆盖 7 大类 intent + edge case
3. **增强比较能力** (P1) — 增加结构化对比模板，支持按维度对比

### 不建议现在做的事

- 不要重构 route_gate（当前职责边界基本清晰）
- 不要重写 compose_answer（God Node 风险可通过拆分模板缓解）
- 不要接入新的 LLM fallback（当前 fallback 机制已够用）
- 不要大规模改 tests（当前测试基础尚可）

### 当前状态更新（2026-06-11 代码事实回写）

- `Intent 成功标准` 已有独立文档 [docs/local-life-intent-success-criteria.md](D:/javacode/hm-dianping/docs/local-life-intent-success-criteria.md)，原文“完全缺失”结论已过时。
- `黄金集` 已从排查时的 7 条扩展到当前仓库可见的 73 条，且 `CI` 已接入 `evaluation` job；原文“仅 7 条、无自动化 CI”已过时。
- `显式对话状态机`、`统一降级提示`、`商家信息过旧提示`、`retry 质量评估`、`业务指标增强` 均已有代码落点，后文统一按“已完成 / 进行中 / 待回查”重新标注。
- 当前仍然最值得优先跟进的未完成项，收敛为 `Task 9-11` 和少量待闭环的 P0/P1 问题，详见第 15 节和第 18 节。

---

## 1. 当前真实架构概览

### 主链路

```
START -> load_context -> request_legality -> hard_guard -> query_safety
  -> query_merge_for_local_life -> merged_query_safety -> understand_turn
  -> top_level_intent_router -> resolve_target_shop -> build_answer_contract
  -> build_source_contract -> complexity_router
    -> [simple] direct_executor -> rule_review
    -> [standard] workflow_executor -> select_required_sources -> rag/tool/recommendation_executor
    -> [complex] planner_node -> plan_validator -> plan_executor -> execute_plan_step
  -> final_answer -> final_answer_safety -> response_builder -> persist_session -> emit_final -> END
```

### 路由层

| 阶段 | 文件 | 职责 |
|------|------|------|
| Phase 0 | `phase0_quality.py` | 输入质量门控（空输入、纯标点） |
| Phase 1 | `phase1_intent.py` | Intent 识别 + Facet 拆解 + 数据源类型判断 |
| Phase 2 | `phase2_slots.py` | Slot 提取 + 代词消解 |
| Phase 3 | `phase3_review.py` | 路由审查 + 路线升级 |
| Phase 4 | `phase4_plan.py` | Task Plan 生成（可选） |
| Phase 5 | `phase5_retrieval.py` | RAG 检索执行 |
| Phase 6 | `phase6_tool.py` | 工具调用执行 |
| Phase 7 | `phase7_compose.py` | 答案合成 + 质量门控 + 审计 |
| 顶层 | `top_level_intent_router.py` | 顶层意图路由（identity/capability/comparison 等） |

### RAG 层

| 模块 | 文件 | 职责 |
|------|------|------|
| 查询路由 | `query_router.py` | 6 条检索策略：realtime_tool / general_chat / compare_multi_parent / guide_rule_rag / structured_first / merchant_reasoning |
| 证据检索 | `local_life_retrieval.py` | parent-child 混合检索 |
| 证据护栏 | `rag_guardrail.py` | 跨店过滤、forbidden facet 过滤、sibling 去重 |
| 证据打包 | `evidence_pack.py` | 按 shop 分组、去重、排序 |
| 证据范围 | `evidence_scope_guard.py` | 单店模式严格过滤跨店 evidence |
| 排序 | `ranker.py` | 商家排序 + Rerank |

### 工具层

| 工具 | 用途 |
|------|------|
| `get_coupon_list` | 查询实时优惠券 |
| `check_open_status` | 查询营业状态 |
| `get_distance_eta` | 查询距离和到达时间 |
| `search_restaurants` | 搜索附近餐厅 |
| `getShopDetail` | 获取商家详情 |
| `recommendShops` | 推荐商家 |

### 生成层

| 模块 | 文件 | 职责 |
|------|------|------|
| 答案契约 | `answer_contract.py` | 根据 user_need 构建 allowed_facets / forbidden_facets / answer_style |
| 答案深度 | `answer_depth_policy.py` | 根据 evidence 数量决定 detailed/normal/short |
| 答案结构 | `answer_structure_composer.py` | 模板化结构化答案（单店/多店/对比/facet组合） |
| 答案模板 | `response_builder/answers.py` | 具体答案文本生成 + lint 校验 + fallback |
| LLM 辅助 | `assistant.py` | LLM 辅助答案生成（compose_answer_plan） |
| 答案校验 | `grounded_verifier.py` | 验证 evidence 是否支撑 answer |
| 答案 lint | `answer_linter.py` | 检测 forbidden_facet 泄露、cross_shop_leak 等 |
| 最终审计 | `final_answer_audit.py` | 最终答案质量审计 |

### 会话状态层

| 模块 | 职责 |
|------|------|
| `PersistentSessionContext` | 跨轮持久化：current_shop / last_candidates / pending_clarification / recent_entities 等 33 个字段 |
| `TurnRuntimeState` | 当前轮运行时状态：60+ 字段 |
| `GraphState` | LangGraph 图状态 |
| `LocalLifeTurnState` | 本地生活轮状态 |

---

## 2. 支持范围矩阵检查

| 问题类型 | 当前支持程度 | 代码证据 | 缺口 | 风险 | 建议 |
|----------|-------------|---------|------|------|------|
| 商家详情 | ✅ 完整 | `answer_style="single_shop_review"`, `_compose_single_shop_review()` | 无 | 低 | - |
| 推荐/附近推荐 | ✅ 完整 | `answer_style="multi_shop_recommendation"`, `recommendation_executor` | 无 | 低 | - |
| 优惠券/团购 | ✅ 完整 | `answer_style="coupon_only"`, `get_coupon_list` tool | 无 | 低 | - |
| 营业状态 | ✅ 完整 | `answer_style="open_status_only"`, `check_open_status` tool | 无 | 低 | - |
| 距离/位置 | ✅ 完整 | `answer_style="distance_only"`, `get_distance_eta` tool | 无 | 低 | - |
| 比较/选择 | ⚠️ 部分 | `answer_style="comparison"`, `compare_multi_parent` 路由 | **无结构化对比模板**，依赖 LLM | **中** | 增加 comparison 模板 |
| 澄清/补充信息 | ✅ 完整 | `answer_style="clarification"`, `ClarificationCard` | 追问策略分散 | 低 | 统一追问管理 |
| 非本地生活兜底 | ✅ 完整 | `top_level_intent_router` -> `out_of_scope_response` | 无 | 低 | - |
| 多轮上下文继承 | ✅ 完整 | `PersistentSessionContext` + 代词消解 | 无 | 低 | - |
| 实时信息（券/营业/距离） | ✅ 完整 | `realtime_facets` + 对应 tool | 无 | 低 | - |
| 场景适配（约会/家庭/聚餐） | ✅ 完整 | `scene_fit` facet + `_scene_label()` | 无 | 低 | - |

**已支持**: 10/11
**部分支持**: 1/11 (比较/选择)
**缺失**: 0
**风险**: 比较能力是当前最大缺口

### 当前状态更新（2026-06-11）

- 本节的“支持程度”描述的是**功能是否有入口**，不是策略完成度。
- 因此，`澄清/补充信息` 与 `场景适配` 虽然已有能力入口，但并不代表 `Task 10` 与 `Task 11` 已完成；这两项的实现深度以第 11 节、第 15 节和第 18 节的状态回写为准。

---

## 3. Intent 成功标准检查

| Intent | 当前是否定义成功标准 | 缺失项 | 建议成功标准 |
|--------|---------------------|--------|-------------|
| `merchant_detail` | ❌ 隐式 | 无显式"必须命中目标店、不能串店"定义 | 必须命中目标店；不能串店；必须围绕用户关心点输出；禁止推荐其他店 |
| `coupon_query` | ❌ 隐式 | 无显式"必须区分实时券和历史券"定义 | 必须调用 get_coupon_list；必须说明是否可用；不能答环境/口味 |
| `open_status` | ❌ 隐式 | 无显式"必须给出当前营业判断"定义 | 必须调用 check_open_status；必须给出当前营业判断；无法确认要说明不确定 |
| `nearby_recommendation` | ❌ 隐式 | 无显式"必须和位置绑定"定义 | 必须绑定位置；必须能解释推荐理由；不能随机推荐 |
| `comparison` | ❌ 隐式 | 无显式"必须输出对比维度"定义 | 必须识别比较对象；必须确定比较维度；必须分别检索两家证据；必须按维度组织差异；必须有最终建议 |
| `address/distance` | ❌ 隐式 | 无显式定义 | 必须调用 get_distance_eta；不能猜测距离 |
| `clarification` | ❌ 隐式 | 无显式定义 | 必须识别缺失信息；不能直接回答 |
| `out_of_scope` | ❌ 隐式 | 无显式定义 | 不能进入 resolve_target_shop；不能进入 RAG/tool |

**结论（排查当时）**: 所有 intent 均**无显式的成功标准定义**。成功标准隐含在代码逻辑中，但没有文档化或结构化定义。

### 当前状态更新（2026-06-11）

- 已新增独立文档 [docs/local-life-intent-success-criteria.md](D:/javacode/hm-dianping/docs/local-life-intent-success-criteria.md)，覆盖 `merchant_detail`、`coupon_query`、`open_status`、`nearby_recommendation`、`comparison`、`clarification`、`out_of_scope` 等 intent 的成功标准、失败模式和评估指标。
- 因此，本节应视为**排查时状态记录**，而不是当前状态结论。
- 当前更准确的判断是：`Intent 成功标准文档化` 已落地，但主文档此前未将其纳入统一叙事。

---

## 4. 追问策略检查

### 当前追问发生位置

| 位置 | 文件 | 触发条件 | 行为 |
|------|------|---------|------|
| `is_low_information_query()` | `target_shop_policy.py:164-171` | 空输入、纯标点、"啊"/"嗯"/"1"/"..." | should_clarify=True |
| `TargetShopPolicy.resolve_target()` | `target_shop_policy.py:442-451` | 低信息量且无店铺线索 | 返回 clarification |
| `UserNeedParser` | `user_need_parser.py:268-271` | location slot 缺失且需要推荐 | missing_slots=["location"] |
| `phase3_review.py` | `phase3_review.py:150-226` | 代词引用失败 | 进入 clarify 路径 |
| `answer_contract.py` | `answer_contract.py:113-116` | intent="clarify" | answer_style="clarification" |
| `answer_structure_composer.py` | `answer_structure_composer.py:~200` | style="clarification" | "我还需要你补充一点信息" |
| `top_level_intent_router.py` | `top_level_intent_router.py:220-228` | bare follow-up 无 current_shop | requires_current_shop=True |
| `_top_level_intent_route()` | `builder.py:701-706` | requires_current_shop=True 且无 current_shop | route="clarification_node" |

### 分散点

追问逻辑**分散在 4+ 个文件**中，没有统一的追问策略管理器。每个节点各自决定是否追问。

### 问题案例

1. **该追问时没有追问**: 问"附近有什么好吃的"但无位置时，`top_level_intent_router` 可能直接识别为 `local_life`，然后进入 `resolve_target_shop` 才发现需要位置，最终通过 `clarification_node` 澄清——但链路较长。
2. **上下文足够继承时可能重复追问**: 如果 session 已有 `current_shop="海底捞"`，用户问"有券吗"，系统能正确继承。但如果 `current_shop` 和 `last_candidates` 同时存在，追问决策可能不一致。
3. **追问策略分散**: 同一个"需要澄清"的意图，可能在 `target_shop_policy`、`phase3_review`、`top_level_intent_router`、`_top_level_intent_route` 等多处触发。

### 建议统一策略

建议新增 `ClarificationStrategy` 统一管理追问决策：
- 规则1: 有明确店名但缺少位置 → 先答店相关内容，再补位置确认
- 规则2: 只有"附近/推荐"但没有位置 → 优先追问
- 规则3: 连续多轮问同一家店 → 不重复追问
- 规则4: 上下文足够继承时 → 不重复追问

---

## 5. 事实来源优先级检查

### 当前事实来源体系

`RequiredFacet.data_source` 定义了 7 种数据源类型（`schemas.py:78-86`）：
- `slot` — 用户输入 slot
- `static_rag` — RAG 检索
- `dynamic_tool` — 实时工具
- `business_api` — 结构化商家数据
- `memory` — 记忆
- `client_context` — 客户端上下文
- `mixed` — 混合来源

### 实时工具 / 结构化数据 / RAG / LLM 的边界

| 字段 | 数据源 | 保护机制 |
|------|--------|---------|
| 券 | `dynamic_tool` (get_coupon_list) | `realtime_facets` 隔离，RAG 不提供券信息 |
| 营业状态 | `dynamic_tool` (check_open_status) | `realtime_facets` 隔离 |
| 距离 | `dynamic_tool` (get_distance_eta) | `realtime_facets` 隔离 |
| 地址 | `static_rag` (business_api) | `answer_linter` 检测 |
| 当前店名 | `client_context` / `slot` | `target_shop_policy` 解析 |
| 环境/口味/服务 | `static_rag` (RAG 检索) | `evidence_scope_guard` 过滤跨店 |
| 推荐理由 | `static_rag` + `mixed` | `fusion.py` 合成 |

### 高风险字段保护状态

| 字段 | 是否有事实源保护 | 保护机制 |
|------|-----------------|---------|
| 券 | ✅ 有 | `realtime_facets` + tool 优先 + 数量校正 |
| 营业状态 | ✅ 有 | `realtime_facets` + tool 优先 |
| 距离 | ✅ 有 | `realtime_facets` + tool 优先 |
| 地址 | ⚠️ 部分 | RAG 提供，无实时验证 |
| 当前店名 | ⚠️ 部分 | `target_shop_policy` 解析，但可能误解析 |
| 价格/人均 | ⚠️ 部分 | RAG 提供，可能过时 |
| 营业时间 | ⚠️ 部分 | RAG 提供，可能与实时状态冲突 |

### 是否存在 LLM 自由补事实

**是**。`LocalLifeModelAssistant.compose_answer_plan()` 在 evidence 不足时可能用 LLM 推断。虽然有 `GroundedVerifier` 检测，但 `evidence_used <= 1` 才触发 insufficient warning，阈值较宽松。

### 是否区分实时券和历史券

**部分区分**。`VoucherRecord` 有 `begin_time`/`end_time` 字段，但 `build_coupon_only_answer()` 没有显式过滤过期券。

### 是否有事实冲突处理

**排查时没有显式冲突处理**。当时若 RAG 检索到的营业时间与 `check_open_status` 工具返回结果冲突，无优先级裁决逻辑。

### 当前状态更新（2026-06-11）

- 当前仓库已新增 `realtime_conflict_resolver.py`，定义了 `TOOL_REALTIME > CLIENT_CONTEXT > SESSION_CONTEXT > RAG_HISTORICAL` 的优先级。
- `rag_guardrail.py` 已接入 `resolve_realtime_conflict()` 与 `ScenePolicy.apply()`，说明“实时信息无冲突处理”不再是纯缺失项。
- 但是否已覆盖所有实时 facet 的回答链路与降级链路，仍建议在第 18 节按 `待回查` 处理，而不再列为“明确未完成”。

---

## 6. 单店链 / 多店链检查

### 当前链路区分方式

区分发生在 `answer_contract.py::build_contract()` 中（L62-185）：

| 模式 | 判断条件 | answer_style |
|------|---------|-------------|
| 单店 | `has_explicit_shop_hint=True` + 非 recommendation | `single_shop_review` |
| 多店推荐 | `intent="restaurant_recommendation"` 且 `target_shop is None` | `multi_shop_recommendation` |
| 对比 | `intent="restaurant_comparison"` | `comparison` |
| 券专项 | `inferred_coupon=True` 且无其他 | `coupon_only` |
| 营业专项 | `inferred_open=True` 且无其他 | `open_status_only` |
| 距离专项 | `inferred_distance=True` 且无其他 | `distance_only` |
| 多 facet 组合 | 多个 realtime facet 同时请求 | `facet_multi` |

### 单店/多店共用部分

- **共用 `answer_contract`**: 单店和多店共用 `AnswerContract.build_contract()`，通过 `answer_style` 区分
- **共用 `route_gate`**: 单店和多店都经过 `route_gate` 节点
- **共用 `compose_answer`**: 最终答案生成都在 `compose_answer` 中

### 风险案例

1. **问单店却答成推荐**: 如果 `target_shop_policy` 解析失败，`answer_style` 可能从 `single_shop_review` 变为 `multi_shop_recommendation`
2. **问推荐却输出单店详情**: 如果 `recommendation_query_should_not_lock_single_shop` 逻辑被意外触发
3. **问比较却只讲一家**: `answer_style="comparison"` 无模板，LLM 可能只输出单店评价
4. **候选店污染 current_shop**: `last_candidates` 中的店可能被误设为 `current_shop`

### 建议拆分方式

当前拆分基本合理，主要风险在 `comparison` 无模板。建议：
1. 为 `comparison` 增加结构化对比模板
2. 确保 `validate_answer_against_contract()` 中 `comparison` 不再直接返回原文

---

## 7. 比较/选择能力检查

### 当前能力

| 能力 | 实现状态 | 代码证据 |
|------|---------|---------|
| 比较意图识别 | ✅ | `_COMPARE_KEYWORDS` (9 个关键词), `IntentType.COMPARE` |
| 比较路由 | ✅ | `compare_multi_parent` 路由, parent_top_k=8, child_top_k=40 |
| 比较 RAG 检索 | ✅ | `multi_parent_rag` 检索策略 |
| 比较答案模板 | ⚠️ 部分 | `answer_structure_composer.py::_compose_comparison()` 已接入 comparison 分支 |
| 按维度对比 | ⚠️ 部分 | 当前已有 `综合评分 / 人均消费 / 距离 / 用户评价` 维度 |
| 差异分析 | ⚠️ 部分 | 已有结构化对比输出，但仍缺更细的环境/口味/服务维度 |
| 最终建议 | ⚠️ 部分 | 已有 `综合建议` 段落，但建议逻辑仍较粗粒度 |

### 缺口

1. **对比模板已存在但维度仍偏少**: 当前 comparison 分支可输出结构化文本，但主要覆盖评分、价格、距离、首条用户评价
2. **环境/口味/服务等目标维度仍未稳定落地**: 尚未形成计划中的细粒度对比模板
3. **差异分析仍偏浅**: 目前更多是并列罗列，而不是面向场景的深度差异总结
4. **最终建议仍较粗**: 主要依据评分或通用兜底话术，未充分利用场景和用户偏好

### 典型问题

- "A 和 B 哪个更适合约会" → 只能靠 LLM prompt 硬撑，输出质量不稳定
- "哪家更安静" → 没有按"安静"维度对比的逻辑
- "哪家更便宜" → 没有按价格维度对比的逻辑

### 当前状态更新（2026-06-11）

- 当前 `comparison` 已不是“完全无模板”，而是**基础模板已存在、增强维度未完成**。
- 因此 `Task 9` 的正确状态应为 `进行中`，而不是“尚未启动”。

### 建议比较链路

```
comparison 意图识别
  -> 确定比较对象（A 和 B）
  -> 确定比较维度（从 user_need 或 query 中提取）
  -> 分别检索两家的证据
  -> 按维度组织差异
  -> 给出最终建议
  -> 输出结构化对比答案
```

---

## 8. 自修复回路检查

### 当前 retry / rewrite / fallback 机制

| 机制 | 代码位置 | 触发条件 | 行为 |
|------|---------|---------|------|
| `ReviewReport.decision` | `domain/contracts.py:212-221` | 答案验证失败 | 6 种修复动作 |
| `LoopCounter` | `domain/contracts.py:224-230` | 重试计数 | 防止无限循环 |
| `RewriteDecision` | `domain/contracts.py:377-386` | query rewrite | 重写查询 |
| `retry_rag` | `builder.py` 中路由 | RAG 结果不满意 | 重新检索 |
| `retry_tool` | `builder.py` 中路由 | 工具结果不满意 | 重试工具 |
| `repair_answer` | `builder.py` 中路由 | 答案质量问题 | 修复答案 |
| `replan` | `builder.py` 中路由 | 计划失败 | 重新规划 |
| `degrade` | `builder.py` 中路由 | 无法修复 | 降级回答 |

### 是否有完整图级 retry

**部分有**。`ReviewReport` 支持 6 种修复动作，但：
- `max_retry_count` 默认为 0（在 `ReviewReport` 中定义），意味着**默认不重试**
- `retry_rag` 只是重试，没有自动改写 query（`RewriteDecision` 在 phase1 中生成，但 retry_rag 不一定使用）
- `retry_tool` 没有换策略的逻辑

### 缺口

1. **默认不重试**: `max_retry_count=0` 意味着大多数情况下不会触发 retry
2. **retry 没有改写 query**: `retry_rag` 只是重试，没有自动改写 query
3. **没有扩大召回策略**: retry 时没有换 top_k 或换检索策略
4. **没有 retry 质量评估**: retry 后没有检查新结果是否真的更好

### 建议图级自修复方案

1. 设置合理的 `max_retry_count`（建议 1-2）
2. retry_rag 时自动触发 query rewrite
3. retry 时扩大 top_k（如从 5 扩到 8）
4. retry 后评估新结果质量，如果更好才采用

---

## 9. 黄金集和评估指标检查

### 当前测试/评估现状

| 维度 | 现状 |
|------|------|
| 测试文件数 | 80+ 个测试文件 |
| 黄金集用例数 | **排查时为 7 个**（当前仓库 `golden_cases.jsonl` 已扩展到 73 条） |
| 评估指标体系 | 3 套：Golden Cases（7 项）、Local Life RAG（12 项）、通用 RAG 检索（5 项） |
| 自动化 CI | **当前已接入** `evaluation` job，调用 `scripts/run_evaluation.py` |

### 黄金集覆盖的 intent

| Intent | 用例数 | 覆盖 |
|--------|--------|------|
| single_shop_review | 2 | D1-1, D1-3-2 |
| coupon_only | 1 | D2-1 |
| real_time_tool | 1 | D4-1 |
| recommendation | 2 | D5-1, D6-1 |
| multi_turn | 2 | D1-3-2, D7-1 |
| **open_status** | **0** | ❌ 未覆盖 |
| **distance** | **0** | ❌ 未覆盖 |
| **comparison** | **0** | ❌ 未覆盖 |
| **clarification** | **0** | ❌ 未覆盖 |
| **out_of_scope** | **0** | ❌ 未覆盖 |

### 缺失指标

| 指标 | 当前状态 |
|------|---------|
| 串店率 | ✅ `business_metrics.py` 已有显式统计 |
| 错店率 | ✅ `business_metrics.py` 已有显式统计 |
| 过度追问率 | ✅ `business_metrics.py` 已有显式统计 |
| 兜底率 | ⚠️ 本节未看到统一显式口径，建议继续核对 |
| 工具调用命中率 | ✅ `business_metrics.py` 已有显式统计 |
| 空召回率 | ⚠️ `empty_rate` 在 RAG eval 中有 |
| 实时信息错误率 | ⚠️ 成功标准文档已有目标值，但 runtime 统计闭环仍建议继续核对 |
| 幻觉率 | ⚠️ 仍未见统一显式口径 |

### 建议黄金集字段

每条黄金样本应包含：
```json
{
  "case_id": "D1-1",
  "intent": "merchant_detail",
  "description": "显式单店评价",
  "turns": [{"user": "海底捞水晶城店怎么样?"}],
  "expected_route": "resolve_target_shop",
  "expected_entity": "海底捞(水晶城购物中心店)",
  "expected_tool": null,
  "expected_output_contains": ["海底捞"],
  "forbidden_output": ["推荐其他店"],
  "expected_metrics": {"single_shop_mode": true},
  "failure_modes": ["cross_shop", "wrong_entity"]
}
```

### 当前状态更新（2026-06-11）

- `golden_cases.jsonl` 当前实际条数为 **73**，因此“仅 7 条”已属于历史结论。
- `.github/workflows/ci.yml` 已增加 `evaluation` job，并调用 `python scripts/run_evaluation.py`，因此“无自动化 CI”已过时。
- `Task 7` 更准确的状态应为：**已显著扩展，但是否达到“80+”原目标仍待确认**。
- `Task 8` 更准确的状态应为：**核心业务指标已实现，但个别指标口径仍建议继续核对**。

---

## 10. 问题类型-失败类型映射

### 当前隐式映射（排查当时）

排查当时代码中没有显式的映射表，但存在以下隐式分类：

**证据层面 (rag_guardrail.py)**:
| drop_reason | 含义 |
|-------------|------|
| `cross_shop` | 单店模式下 evidence 不属于 target_shop |
| `forbidden_facet` | facet 在禁止列表 |
| `realtime_facet_from_rag` | 实时 facet 不应从 RAG 获取 |
| `low_relevance` | relevance 等级为 weak 或 irrelevant |

**答案 lint (answer_linter.py)**:
| issue | 含义 |
|-------|------|
| `forbidden_facet_violated` | 回答中出现禁止 facet |
| `unsolicited_recommendation` | 非推荐合同中出现推荐语言 |
| `unsupported_realtime_claim` | 未调用工具但答案中有实时关键词 |
| `cross_shop_leak` | 单店合同下出现多店名 |

**Eval failure 格式 (run_golden_cases.py)**:
| 格式 | 含义 |
|------|------|
| `missing:{keyword}` | 回答缺少预期关键词 |
| `forbidden:{keyword}` | 回答包含禁止关键词 |
| `route_branch:{value}` | 路由分支不匹配 |
| `rag_mode:{value}` | RAG 模式不匹配 |

### 建议映射表

| 问题类型 | 典型失败 | 可能原因 | 应该归属模块 | 建议测试 |
|----------|---------|---------|-------------|---------|
| 问券却答环境 | answer 包含"环境" | forbidden_facet 未生效 | answer_contract + answer_linter | coupon_only 禁止 environment |
| 问当前营业却用了历史信息 | 无 tool 调用 | realtime_facet 未触发 tool | route_gate + tool_planner | open_status 必须调用 tool |
| 问附近却没追问位置 | 直接回答推荐 | location slot 缺失未检测 | user_need_parser + clarification | nearby 无 city 必须澄清 |
| 问比较却只答单店 | 只输出一家店 | comparison 无模板 | answer_structure_composer | comparison 必须输出两家 |
| 问单店却答成推荐 | 输出推荐列表 | target_shop 解析失败 | target_shop_policy | single_shop 不得推荐 |
| 问 A 店答 B 店 | 串店 | cross_shop 过滤失败 | evidence_scope_guard | 单店模式不允许跨店 |
| 无证据硬答 | 编造信息 | evidence 不足未检测 | grounded_verifier | evidence<=1 必须降级 |
| RAG 召回不相关 | 证据不匹配 | 检索质量差 | query_router + rag | facet_hit_rate 低 |
| 工具结果被忽略 | 有 tool 结果但未使用 | compose_answer 忽略 | compose_answer | tool_called 必须体现 |
| 上下文错误继承 | 继承了错误的 current_shop | 代词消解失败 | target_shop_policy | multi_turn 继承正确 |

---

### 当前状态更新（2026-06-11）

- 当前仓库已新增 `failure_mode_mapping.py`，定义了 `FailureMode`、`ProblemType`、`FailureModeDetector` 以及更细的 `realtime / comparison / clarification / stale / scene` 检测规则。
- [docs/local-life-intent-success-criteria.md](D:/javacode/hm-dianping/docs/local-life-intent-success-criteria.md) 也已包含独立的“失败类型映射”表。
- 因此，“问题类型-失败类型映射”不再是纯缺失项；更准确的状态应为：**基础映射已落地，但 runtime 检测、文档映射、eval 使用是否完全闭环仍待回查**。

## 11. 答案模板和场景化策略检查

### 当前模板现状

| answer_style | 模板函数 | 完整度 |
|-------------|---------|--------|
| `coupon_only` | `build_coupon_only_answer()` | ✅ 完整 |
| `open_status_only` | `build_open_status_only_answer()` | ✅ 完整 |
| `distance_only` | `build_distance_only_answer()` | ✅ 完整 |
| `single_shop_review` | `build_single_shop_review_answer()` + `_compose_single_shop_review()` | ✅ 完整 |
| `multi_shop_recommendation` | `build_multi_shop_recommendation_answer()` + `_compose_multi_shop_recommendation()` | ✅ 完整 |
| `facet_multi` | `_build_facet_driven_answer()` + `_compose_facet_multi()` | ✅ 完整 |
| `comparison` | `_compose_comparison()` | ⚠️ 部分 |
| `clarification` | `_compose_clarification()` | ⚠️ 部分 |

### 各模板定义

| 模板 | 必答项 | 可选项 | 禁止项 | 长度上限 |
|------|--------|--------|--------|---------|
| `coupon_only` | 券信息 | 无 | 环境/口味/服务/推荐 | 28字 |
| `open_status_only` | 营业状态 | 无 | 环境/口味/服务/推荐/券 | 28字 |
| `distance_only` | 距离信息 | 无 | 环境/口味/服务/推荐/券 | 28字 |
| `single_shop_review` | 总体结论 + 核心优点 + 可能不足 + 适合场景 + 到店建议 | 环境/口味/服务/券/营业/距离 | 推荐其他店 | 120-220字 |
| `multi_shop_recommendation` | 每店: 推荐理由 + 适合场景 + 注意事项 + 综合建议 | 环境/口味/服务/券/营业/距离 | 串店 | 120-220字 |
| `comparison` | 综合评分 / 人均消费 / 距离 / 用户评价 / 综合建议 | 可根据证据补维度 | 只答单店 | 结构化多段 |
| `clarification` | 按缺失 slot 输出具体追问 | 店名 / 位置 / 品类 | 直接回答 | 简短追问 |

### 缺口

1. **comparison 模板已存在但维度仍不足**: 当前有结构化 comparison 输出，但未覆盖环境/口味/服务等目标维度
2. **clarification 模板已从纯硬编码兜底升级为按缺失 slot 追问**，但仍缺与统一追问策略的完整闭环
3. **场景化策略已接入规则层**: `scene_policy.py` 已接入 `rag_guardrail.py`，但当前规则仅覆盖少量场景，覆盖面仍偏弱

### 建议模板分层

为 comparison 增加模板：
```
[对比维度说明]
- 维度1: ...
- 维度2: ...

[每个维度对比]
维度1:
  - 店A: ...
  - 店B: ...
维度2:
  - 店A: ...
  - 店B: ...

[最终建议]
建议选择: ...
理由: ...
```

### 当前状态更新（2026-06-11）

- `comparison` 与 `clarification` 已经都有独立模板入口，不能再描述为“完全没有模板”。
- `Task 9` 更准确的状态是 `进行中`：基础模板已落地，但增强维度未完成。
- `Task 10` 更准确的状态是 `未完成`：虽已有 `clarification_strategy.py` 和结构化澄清模板，但缺少重复追问规避、追问优先级等计划中的核心规则。
- `Task 11` 更准确的状态是 `进行中`：规则层已接入，但当前 `scene_policy.py` 只覆盖少量场景，尚未扩展到商务、朋友、深夜、单人等计划目标。

---

## 12. 对话状态机检查

### 当前 session 状态

`PersistentSessionContext` 维护 33 个字段（`domain/contracts.py:732-764`）：

| 类别 | 字段 |
|------|------|
| 话题追踪 | `current_topic`, `current_shop`, `current_shop_anchor` |
| 代词消解 | `recent_entities`, `selected_shop_id`, `selected_shop_name` |
| 澄清管理 | `pending_user_need`, `clarification_result`, `pending_clarification` |
| 历史记忆 | `history_summary`, `open_questions`, `confirmed_facts`, `next_steps` |
| 偏好/约束 | `local_life_preferences`, `local_life_avoid`, `current_city`, `current_location` |
| 阶段追踪 | `route_decision`, `current_stage`, `stage_status`, `stage_timeline` |

### 是否有任务状态机

**排查时没有显式的任务状态机**。当时主要通过 `PersistentSessionContext` 的字段组合来隐式维护状态，没有定义状态流转图。

### 缺失的状态字段

| 缺失字段 | 用途 |
|---------|------|
| `current_task` | 当前任务类型（查询/推荐/比较/澄清） |
| `active_intent` | 当前活跃 intent |
| `comparison_targets` | 当前比较对象列表 |
| `pending_slots` | 待确认的 slot 列表 |
| `task_state` | 任务状态（进行中/已完成/已澄清） |

### 多轮风险

| 场景 | 风险 | 当前处理 |
|------|------|---------|
| 先问海底捞怎么样，再问有券吗 | current_shop 继承 | ✅ 正常 |
| 先推荐几家，再问第二家怎么样 | last_candidates 继承 | ✅ 正常 |
| 先问 A 和 B 对比，再问哪家更便宜 | **comparison_targets 可能丢失** | ⚠️ 风险 |
| 先被追问位置，再补充位置 | pending_clarification 消费 | ✅ 正常 |

---

### 当前状态更新（2026-06-11）

- 当前仓库已新增 `dialog_state_machine.py`，并在 `PersistentSessionContext` 中增加 `dialog_state`、`dialog_task`、`dialog_intent`、`dialog_comparison_targets`、`dialog_pending_slots`、`dialog_transition_count` 等字段。
- `builder.py` 中也已存在 `dialog_state_machine` 的接入逻辑，因此 `Task 1` 不能再写成“完全缺失”。
- 当前更准确的判断是：`显式对话状态机` 已完成主干落地，剩余工作更多属于后续验证和体验层完善，而非文档中的原始缺口状态。

## 13. 产品边界提示检查

### 当前兜底方式

| 场景 | 兜底方式 | 代码证据 |
|------|---------|---------|
| 非本地生活 | `out_of_scope_response` | `top_level_intent_router.py:376-383` |
| 缺少位置 | `clarification_node` | `builder.py:701-706` |
| 实时券无法确认 | `fallback_message_for_facet()` | `realtime_contract.py` |
| 商家信息过旧 | `boundary_prompts.py` + `realtime_conflict_resolver.py` | 已有 `outdated_info` / `stale_evidence` 提示 |
| RAG 无证据 | `RAG_NO_ANSWER` 模板 | `rag_guardrail.py:326-343` |
| 证据不足 | `degraded_reason` | `grounded_verifier.py:96-105` |
| 低信息输入 | `clarification_node` | `target_shop_policy.py:442-451` |
| 不可服务位置（北极/南极） | `location_unavailable` | `base.py:57` |

### 缺口

1. **"商家信息过旧"提示已存在**: `boundary_prompts.py` 中已有 `outdated_info` / `stale_evidence`
2. **统一提示框架已落地**: `realtime_contract.py` 和 `realtime_conflict_resolver.py` 已引用统一边界提示
3. **仍需继续验证覆盖完整性**: 并非所有降级场景都能仅凭当前文档确认已完整收口

### 建议统一提示策略

```python
BOUNDARY_PROMPTS = {
    "no_location": "我需要知道您所在的位置才能推荐附近的商家，请告诉我您的城市或位置。",
    "no_coupon_evidence": "我暂时无法确认这家店的优惠券信息，建议您直接查看商家页面。",
    "outdated_info": "这家店的信息可能不是最新的，建议您直接联系商家确认。",
    "service_unavailable": "抱歉，该位置暂时无法提供服务。",
    "evidence_insufficient": "我目前没有足够的信息来回答这个问题，您可以尝试换一种问法。",
}
```

### 当前状态更新（2026-06-11）

- `Task 3` 与 `Task 4` 已有明确代码落点，不再属于“完全未处理”。
- 当前更准确的状态是：`统一降级消息` 与 `商家信息过旧提示` 已完成主干实现，但边界覆盖完整性仍值得后续继续验证。

---

## 14. 架构冗余和 God Node 风险

### route_gate 是否膨胀

**轻微膨胀**。`route_gate` 在 `subgraphs.py` 中承担了：
- 执行模式判断
- RAG/Tool/Recommendation 路由
- 单店/多店模式判断

但职责边界基本清晰，没有明显 God Node 风险。

### compose_answer 是否膨胀

**中度膨胀**。`compose_answer` 在 `builder.py` 的 `_final_answer_node` 中：
- 调用 `services.compose_answer(state)`
- 处理 plan_execution_answer
- 设置 final_answer_ready

实际逻辑在 `phase7_compose.py` 中，包含：
- 答案合成
- 质量门控
- 审计
- 安全检查

**建议**: 可考虑将质量门控和审计拆分为独立节点。

### resolve_target_shop 是否承担过多职责

**轻微**。`resolve_target_shop` 主要做：
- 调用 `route_gate(state)`
- 记录 trace 信息

实际解析在 `target_shop_policy.py` 中，职责清晰。

### RAG / tool / answer contract 是否边界清楚

**基本清楚**。RAG 负责证据检索，tool 负责实时信息，answer contract 负责约束生成。边界通过 `AnswerContract` 的 `allowed_facets` / `forbidden_facets` / `realtime_facets` 控制。

---

## 15. 优先级改造清单

### 当前状态总表（按原始优先级回写）

| 问题 | 原始优先级 | 当前状态 | 当前结论 | 后续动作 |
|------|------------|----------|----------|----------|
| 问题类型-失败类型映射 | P0 | 待回查 | 已有 `failure_mode_mapping.py` 和成功标准文档映射表，但 runtime / eval / 文档是否完全闭环仍待核对 | 回查检测、评估、文档三层是否全部接通 |
| 黄金集扩展 | P0 | 待回查 | `golden_cases.jsonl` 已扩展到 73 条，显著高于排查时的 7 条，但是否达到原定 `80+` 目标仍待确认 | 确认目标值是否继续保持 `80+`，并回写覆盖矩阵 |
| 业务指标增强 | P0 | 已完成 | `business_metrics.py` 已有 `cross_shop / wrong_shop / over_clarification / tool_hit / retry / staleness / scene_violation` 等核心指标 | 后续只需补口径核对和使用说明 |
| comparison 结构化模板 | P0 | 进行中 | comparison 模板已存在，但维度仍不足，`Task 9` 未完成 | 继续补环境 / 口味 / 服务 / 场景化建议等维度 |
| 实时信息冲突处理 | P0 | 待回查 | `realtime_conflict_resolver.py` 已存在且已接入 `rag_guardrail.py`，不再是纯缺失项 | 回查是否覆盖所有实时 facet 与回答链路 |
| Intent 成功标准文档化 | P1 | 已完成 | 已有 [docs/local-life-intent-success-criteria.md](D:/javacode/hm-dianping/docs/local-life-intent-success-criteria.md) | 主文档完成引用整合即可 |
| 统一追问管理器 | P1 | 未完成 | 已有 `clarification_strategy.py`，但仅覆盖基础规则，缺少重复追问规避与优先级规则 | 继续完成 `Task 10` |
| 自修复默认不重试 / retry 治理 | P1 | 待回查 | `max_retry_count` 已为 1，且有 retry 质量指标，但重写策略、扩大召回等是否闭环仍待核对 | 继续核对图级 retry 的完整链路 |
| clarification 模板升级 | P1 | 待回查 | `_compose_clarification()` 已按缺失 slot 输出具体追问，但是否达到完整策略目标仍待核对 | 与 `Task 10` 一起收口 |
| 场景规则引擎 | P1 | 进行中 | `scene_policy.py` 已接入规则层，但当前只覆盖少量场景 | 继续完成 `Task 11` |
| 显式对话状态机 | P2 | 已完成 | `dialog_state_machine.py`、`PersistentSessionContext dialog_*` 字段和 `builder.py` 接入均已存在 | 后续只需验证效果 |
| 评估自动化 CI | P2 | 已完成 | `.github/workflows/ci.yml` 已增加 `evaluation` job 并调用 `scripts/run_evaluation.py` | 后续只需维护评估稳定性 |
| 降级消息优化 | P2 | 已完成 | `boundary_prompts.py` 已统一提示框架，并被多处引用 | 后续只需补覆盖核验 |
| 商家信息过旧提示 | P2 | 已完成 | 已有 `outdated_info` / `stale_evidence` 提示与新鲜度检测逻辑 | 后续只需补体验验证 |
| retry 后质量评估 | P2 | 已完成 | `business_metrics.py` 已提供 `retry_improved / retry_degraded` 相关指标 | 后续只需补链路核验 |

---

## 16. 推荐落地顺序

| 顺序 | 当前优先事项 | 原因 |
|------|--------------|------|
| 1 | `Task 9: 增强 comparison 模板维度` | 当前仍是最明确的体验缺口，且代码已具备基础模板，继续补齐收益最高 |
| 2 | `Task 10: 增强 clarification_strategy 规则` | 追问策略仍未统一闭环，直接影响重复追问和缺位追问 |
| 3 | `Task 11: 增强 scene_policy 场景` | 规则层已接入，但覆盖面不足，仍明显依赖 LLM |
| 4 | 回查 `问题类型-失败类型映射` 是否闭环 | 当前已有映射实现和文档，但需要确认是否真正贯通 runtime / eval / 文档 |
| 5 | 回查 `黄金集扩展` 是否达到目标 | 当前为 73 条，需明确是继续扩到 `80+` 还是回写目标变更 |
| 6 | 回查 `retry 策略整体治理` 与 `实时信息冲突处理` | 两项都已有实现入口，但是否全链路收口仍待验证 |

---

## 17. 不建议现在做的事

| 事项 | 原因 |
|------|------|
| 重构 route_gate | 当前职责边界基本清晰，重构收益不确定 |
| 重写 compose_answer | 可通过拆分模板缓解，不需要大规模重构 |
| 接入新 LLM fallback | 当前 fallback 机制已够用，优先解决规则层问题 |
| 大规模改 tests | 当前测试基础尚可，优先扩展黄金集 |
| 新增"看起来很智能"的节点 | 没有评估闭环的新节点只会增加复杂度 |
| 统一所有状态字段命名 | P2 技术债，不紧急 |
| 重写 target_shop_policy | 当前解析逻辑基本正确，小修即可 |

---

## 18. 当前未完成项整理（2026-06-11 回写）

### 整理口径

当前未完成内容按两个层级维护，避免混淆：

1. **执行层（checklist）**：只看 Task 清单是否完成
2. **问题层（backlog）**：只看 P0 / P1 / P2 问题是否仍然开放

默认口径如下：
- `Task 1-8` 已完成
- `Task 9-11` 未完成
- 主文档保留 `2026-06-10` 的排查语境；若与当前代码冲突，以本节和第 15 节的回写状态为准
- 状态词统一使用：`已完成 / 进行中 / 未完成 / 待回查 / 历史结论（已过时）`

### 18.1 严格按 checklist 的未完成项

| 状态 | 任务 | 说明 |
|------|------|------|
| `进行中` | `Task 9: 增强 comparison 模板维度` | 比较类回答仍缺少稳定的结构化模板、维度组织和最终建议能力 |
| `未完成` | `Task 10: 增强 clarification_strategy 规则` | 追问策略仍需统一，需解决重复追问、缺位追问、上下文继承不一致等问题 |
| `进行中` | `Task 11: 增强 scene_policy 场景` | 规则层已接入，但场景覆盖面仍未达到计划目标 |

### 18.2 按 backlog 视角仍然开放的缺口

#### A. 明确未完成

| 类型 | 项目 | 说明 |
|------|------|------|
| `Task` | `Task 9: 增强 comparison 模板维度` | 对应 comparison 结构化模板能力缺口 |
| `Task` | `Task 10: 增强 clarification_strategy 规则` | 对应统一追问管理和澄清策略缺口 |
| `Task` | `Task 11: 增强 scene_policy 场景` | 对应规则引擎场景策略缺口 |
| `P1 backlog` | `clarification 策略闭环` | 模板和策略文件都已存在，但重复追问规避、优先级等规则尚未完成 |

#### B. 可能部分完成，但需要回查是否真正闭环

| 项目 | 回查原因 |
|------|----------|
| `问题类型-失败类型映射` | 已有 `failure_mode_mapping.py` 和成功标准文档映射表，但 runtime / eval / 文档三层闭环仍待核对 |
| `结构化 clarification 模板` | `_compose_clarification()` 已支持按缺失 slot 输出具体追问，但仍需和策略规则一起验收 |
| `retry 策略整体治理（不只是质量评估）` | `max_retry_count=1` 和 retry 指标已存在，但 query rewrite / 扩大召回 / 采用策略是否闭环仍待核对 |
| `黄金集扩展` | 当前文件为 73 条，已显著扩展，但是否达到原 `80+` 目标仍待确认 |
| `实时信息冲突处理` | 冲突解析器和新鲜度提示已存在且已接入，但是否覆盖所有回答链路仍待核对 |

#### C. 已完成但文档未回写关闭

| 项目 | 对应已完成任务 |
|------|----------------|
| `显式对话状态机` | `Task 1` |
| `评估自动化 CI` | `Task 2` |
| `降级消息优化` | `Task 3` |
| `商家信息过旧提示` | `Task 4` |
| `retry 后质量评估` | `Task 5` |
| `业务指标增强` | `Task 8` |
| `Intent 成功标准文档化` | 独立文档已落地 |

### 18.3 建议作为后续执行入口的最终未完成清单

后续如果只保留一份面向执行的未完成列表，建议使用下面这版：

#### 优先跟进

1. `Task 9: 增强 comparison 模板维度`
2. `Task 10: 增强 clarification_strategy 规则`
3. `Task 11: 增强 scene_policy 场景`
4. 回查 `问题类型-失败类型映射` 是否已形成闭环
5. 回查 `黄金集扩展` 是否达到目标并同步口径

#### 回查后决定是否关闭

1. `问题类型-失败类型映射`
2. `结构化 clarification 模板`
3. `retry 策略整体治理（不只是质量评估）`
4. `黄金集扩展`
5. `实时信息冲突处理`

---

## 附录: 测试运行结果

### 命令 1: 顶层意图路由测试

```bash
pytest tests/test_top_level_intent_routing.py -v
```

**结果**: 23 passed, 0 failed

### 命令 2: 路由相关测试（排除 local_life）

```bash
pytest tests -k "intent or route or rag or tool or recommendation or coupon or comparison or clarification" --ignore=tests/test_api_contracts.py --ignore=tests/test_policy_settings_and_guards.py --ignore=tests/local_life -q
```

**结果**: 231 passed, 4 failed, 1 skipped, 213 deselected

**失败用例**:
1. `test_heuristic_metadata_retriever_uses_configured_threshold` — qdrant filter builder 测试，与效果增强无关
2. `test_simple_execution_mode_can_route_directly_to_tool_subgraph` — router degradation 测试，与效果增强无关
3. `test_route_review_upgrades_nearby_recommendations_when_location_context_exists` — Phase1 routing 测试，recommendation_reason 数据源类型为 mixed 而非 static_rag
4. `test_recommendation_mermaid_matches_exported_topology` — Mermaid 图测试，拓扑已更新但测试未同步

**与效果增强相关**: 仅 #3 与推荐场景的数据源优先级相关，其余 3 个为历史遗留问题。

---

## 附录: 未修改代码的确认说明

本轮排查**严格只读**，未修改任何业务代码。所有分析基于代码阅读和测试运行。文档中的建议仅为下一步改进方向，未实际实现。
