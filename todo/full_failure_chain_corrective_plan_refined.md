# Full Failure Chain Corrective Plan Refined

## 1. Executive Summary

这次故障不能简单归因成“小 bug”。从当前仓库代码和已有审计报告看，它是一次典型的：

- 架构收口问题
- 工具契约问题
- 局部规则 bug

三者叠加后被 LLM 重试与 fallback 放大，最终表现为 108 秒的长尾耗时、`resolve_shop` 重复调用、距离工具跳过、优惠券信息丢失、以及 `evidence_review` / `decision_planner` 之间的空决策断层。

正确修复方向不是重写整条 LangGraph，也不是给某个关键词打硬编码补丁，而是先把以下链路收口：

```text
LLM semantic parser
  -> strict schema validation
  -> semantic frame
  -> deterministic policy guard
  -> workflow selection
  -> typed tool planning
  -> EvidencePack
  -> DecisionPlan
  -> answer generation
```

本轮建议只做“统一入口、补契约、加幂等、加 guard、补测试”，并保留 legacy 作为受控 fallback，不直接删除。

---

## 2. Current Failure Nature: Architecture vs Contract vs Bug

### 2.1 Architecture Problems

这类问题不是局部 if/else 能彻底修好的，必须先收口架构边界：

- 低置信 semantic signal 可以直接触发高成本工具链。
- workflow 准入条件不够严格，语义层的局部词片段能进入比较链路。
- `resolve_shop` 的 legacy resolver 和 gateway/entity resolver 并列，导致一次错误输入被双路径放大。
- 同一 turn 缺少 tool-call budget，重复解析没有上限。
- LLM retry 没有改变失败条件，重试只是重复付费。
- `evidence_review`、`decision_planner`、`answer` 之间缺少统一事实载体，导致事实在 fallback 中再次丢失。

### 2.2 Contract Problems

这类问题应优先修 schema / DTO / contract，而不是写更多规则：

- `location={}` / `location=null` / `location_text` / `coordinates` 混用。
- `SemanticFrame.preferences` 与实际 Pydantic schema 的表达方式不稳定。
- `EvidenceReviewResult` 和 `DecisionPlan` 对 candidates / evidence 的字段理解不一致。
- fallback answer 没有统一读取 `EvidencePack`。
- 已查到 coupon evidence，但最终回答重新判空。
- distance facet 依赖坐标，但上游只传自然语言地点。

### 2.3 Local Bugs

这些是要修，但不能把它们误判成全部问题：

- “性价比”误触发 comparison。
- 截断 query 被当成店名传给 `resolve_shop`。
- 同一 query 缺少 per-turn dedupe。
- fallback top1 裁剪过激。
- schema validation 失败后的 fallback 状态没有显式暴露。

---

## 3. What Existing Report Got Right

现有 `todo/full_failure_chain_audit_report.md` 的方向基本正确，尤其是下面几点：

1. `semantic_parse` 的超时与 schema 失败确实是长尾耗时来源之一。
2. `reference_resolver.py` 中确实存在比较词过宽和显式解析双路径放大的风险。
3. `evidence_planner.py` 在没有坐标时会跳过 distance 规划。
4. `evidence_review` 不是纯规则，它会走 LLM review，天然存在重试成本。
5. `decision_planner` 可能在证据充分但候选或 schema 不匹配时退化成 `unsupported` / 空候选。
6. fallback 路径确实有把已经拿到的 coupon / distance 信息再次丢掉的风险。

需要补强的是：把这些结论从“问题清单”收敛成“分层修复策略 + 契约 + 验收标准”，避免演变成一次性大重构建议。

---

## 4. What Needs Refinement Before Implementation

### 4.1 不要把所有问题都当成同一级别

建议明确优先级：

- P0：会继续放大故障、影响正确性和链路可用性的收口项。
- P1：性能与 retry 策略优化。
- P2：可观测性和回归测试强化。

### 4.2 不要直接建议大规模重写

以下做法不建议现在做：

- 重写整个 `graph_builder`
- 新增一套完全独立 workflow runner
- 把所有路由都交给一个全局 LLM agent
- 删除所有 legacy 代码
- 把 `active_turn_resolver` 扩成大型 ContextGate
- 把 `state_update_plan` 分散到各节点
- 为了架构漂亮破坏已有 single_coupon / comparison / recommendation 链路

### 4.3 迁移原则

推荐的落地原则是：

```text
先统一入口、补契约、加幂等、加 guard、补测试，再逐步替换 legacy。
```

---

## 5. P0 Fix Plan

### 5.1 Semantic Frame and Comparison Guard

目标：

- “性价比”不能触发 comparison。
- 单字“比”不能直接触发 comparison。
- comparison workflow 必须满足结构化准入条件。

建议准入条件：

```text
intent == comparison
AND comparison_targets >= 2
AND compare_facets is not empty
AND confidence >= threshold
AND semantic_parse_status in [success, degraded_but_valid]
```

如果只是 value_for_money，应进入 recommendation，不应进入 comparison。

验收样例：

```text
“北京邮电大学附近性价比高的火锅” -> recommendation
“A 和 B 哪家更便宜” -> comparison
“帮我对比海底捞和巴奴的优惠券” -> comparison
“附近火锅推荐，要性价比高” -> recommendation
```

正确方向：

- LLM 负责语义理解，但不能无约束决定工作流。
- 必须先做 strict schema validation，再进入 deterministic policy guard。

不建议的错误修法：

- 给“性价比”写 hardcode 特判后就结束。
- 只靠关键词“比”触发 / 禁止 comparison。

### 5.2 Resolve Shop Gateway, Idempotency and Tool Budget

目标：

- 所有店铺实体解析统一进入一个 gateway。
- legacy resolver 不能和 entity resolver 并列重复调用。
- 同一 turn + 同一 normalized query + 同一 location context 只允许一次真实解析。
- 低置信 query 不允许进入精确店铺解析。

建议设计：

```text
resolve_shop_gateway(
  query,
  location_context,
  turn_id,
  confidence,
  source
) -> ResolveShopResult
```

建议 dedupe key：

```text
dedupe_key = turn_id + normalized_query + normalized_location_context
```

建议预算：

```text
max_resolve_shop_per_turn = 3
max_same_query_resolve_per_turn = 1
max_tool_retry_per_call = 1
```

迁移边界：

- legacy 路径暂时保留为 gateway 内部 fallback adapter。
- 本轮不要直接删除 legacy。
- 先把所有调用方迁到统一 gateway，再逐步减少旧入口。

不建议的错误修法：

- 继续让 legacy resolver 和 gateway resolver 并列调用。
- 一次性删除 legacy path。
- 为了修复重复调用，直接扩大重试次数。

### 5.3 GeoContext and Geocode Tool Contract

目标：

- 不再让自然语言地点直接进入距离规划。
- 先将地点解析成统一 GeoContext。
- 有坐标时才算距离。
- 没有坐标时要显式说明原因，而不是静默跳过。

建议新增或收敛为：

```text
geocode_location(location_text, city_hint?, user_location_hint?) -> GeoContext
```

建议 GeoContext 结构：

```json
{
  "location_text": "北京邮电大学",
  "lat": 39.0,
  "lng": 116.0,
  "city": "北京",
  "geo_status": "resolved | ambiguous | unresolved | out_of_scope",
  "source": "poi_lookup | db | user_profile | fallback",
  "confidence": 0.0
}
```

`search_shops` 的行为建议：

- 有 lat/lng：按距离过滤 + 排序。
- 有 city：至少按城市过滤。
- geo ambiguous：进入澄清或保守搜索。
- geo unresolved：不要做全国泛搜污染推荐，必须记录 missing_reason。

正确方向：

- 地名是输入事实，不是距离输入。
- 距离 facet 依赖坐标，坐标必须显式进入工具契约。

不建议的错误修法：

- 没有 GeoContext 就直接全国搜索并排序。
- 直接在 fallback 里根据文本猜位置。

### 5.4 EvidencePack Contract

目标：

- 已获取的事实不能在后续 decision / fallback 中丢失。
- coupon、distance、shop candidate 都必须通过统一 EvidencePack 传递。
- fallback answer 只能基于 EvidencePack 保守表达，不能重新判空。

建议 EvidencePack 至少包含：

```json
{
  "shop_evidence": [],
  "coupon_evidence": [],
  "distance_evidence": [],
  "ranking_evidence": [],
  "missing_evidence_reasons": [],
  "tool_errors": [],
  "degradation_reasons": []
}
```

必须强调：

- 只要 `coupon_evidence` 非空，最终回答不能说“无法确认优惠”。
- 只要 `distance_evidence` 非空，最终回答不能丢距离。
- 如果 distance 缺失，必须说明是因为 `GeoContext` unresolved / ambiguous，而不是说没有距离信息。

正确方向：

- 事实先进入 EvidencePack，再进入 DecisionPlan，再进入 answer generation。
- fallback 不能重新查 state 或重新判空。

不建议的错误修法：

- 在 fallback answer 中重新查 state。
- 在 fallback answer 中重新判空后丢弃已经拿到的事实。

### 5.5 Evidence Review and DecisionPlan Alignment

目标：

- `evidence_review` 认为 sufficient 时，`decision_planner` 不应返回空 candidates。
- 如果证据部分充分，应产出 conservative_decision，而不是 unsupported。
- 空决策应记录为异常事件，不作为正常业务路径。

建议 DecisionPlan 包含：

```json
{
  "decision_type": "recommendation | comparison | answer | conservative | unsupported",
  "selected_candidates": [],
  "ranking_reasons": [],
  "used_evidence_ids": [],
  "missing_evidence_reasons": [],
  "degradation_reason": null
}
```

必须补充：

- `unsupported` 只能用于确实无法回答的场景。
- 有候选、有 coupon、有部分 evidence 时，不应返回 `unsupported + []`。

正确方向：

- review 与 decision 共享同一套候选 / 证据 schema。
- `evidence_review` 只负责判断是否可继续，不应该把事实改写掉。

不建议的错误修法：

- 让 `evidence_review` 用 LLM 判断 coupon 是否存在这种结构化事实。
- `evidence sufficient` 后仍允许 `decision_planner` 返回空候选且视为正常。

### 5.6 Evidence-Based Fallback Answer

目标：

- fallback 不再生成“事实清空式回答”。
- fallback 只做保守表达。
- fallback 必须展示已获取证据和缺失原因。

示例：

错误 fallback：

```text
无法确认该店是否有优惠，也无法确认距离。
```

正确 fallback：

```text
我查到了 3 张优惠券，但当前位置没有解析成坐标，所以暂时不能可靠计算距离。
```

正确方向：

- 回答可以保守，但不能把已经拿到的事实说没了。
- fallback 必须读取 EvidencePack。

---

## 6. P1 Latency and Retry Strategy

不要把“把 timeout 从 20 秒改成 40 秒”当作核心修复。提高 timeout 只能减少单次 timeout，但可能放大总耗时。

正确做法：

```text
1. semantic_parse 超时后，不要用同样 prompt 重试；
2. 第二次尝试应切换短 prompt / repair prompt / lightweight extraction；
3. schema validation 失败后要显式返回 parse_status=failed 或 degraded_but_valid；
4. evidence_review 前先做 deterministic precheck；
5. LLM review 只处理语义权衡，不判断 coupon 是否存在这种结构化事实；
6. review 输入必须压缩，只传候选摘要和 evidence ids，不传完整冗余上下文；
7. 每个 LLM stage 有独立 timeout、retry、fallback policy。
```

建议：

- `semantic_parse` 可以适度延长 timeout，但必须配合“第二次尝试换策略”。
- `evidence_review` 不能把重心放在本来就已结构化的事实判断上。
- retry 策略要改变失败条件，不要重复同样的失败。

---

## 7. P2 Observability and Regression Tests

### 7.1 必须记录的 span / metrics

```text
semantic_parse_status
semantic_parse_retry_count
comparison_guard_decision
resolve_shop_call_count_per_turn
resolve_shop_dedupe_hit
geo_status
distance_planning_skipped_reason
coupon_evidence_count
candidate_count_before_decision
candidate_count_after_decision
decision_type
fallback_used
evidence_preserved_in_answer
total_tool_call_count
total_llm_call_count
```

### 7.2 必须新增的回归测试

```text
test_value_for_money_not_comparison
test_comparison_requires_two_targets
test_resolve_shop_dedupe_same_query
test_low_confidence_fragment_not_resolved_as_shop
test_geocode_location_text_to_geo_context
test_search_shops_city_filter_before_ranking
test_distance_calculation_when_geo_resolved
test_distance_missing_reason_when_geo_unresolved
test_coupon_evidence_preserved_in_fallback
test_evidence_sufficient_no_empty_decision
test_conservative_decision_when_partial_evidence
test_no_more_than_max_resolve_shop_per_turn
test_schema_validation_failure_exposes_parse_status
```

### 7.3 测试目标

这些测试不是为了“证明流程能跑”，而是为了证明：

- comparison guard 不再误触发。
- resolve_shop 不会被同一输入重复放大。
- 有 GeoContext 才会算距离。
- evidence sufficient 时不会空决策。
- fallback 不会把券和距离证据丢掉。

---

## 8. Code Audit Checklist

> 说明：以下按仓库实际文件名填写。用户提示里的 `graph_state.py` 在仓库中实际存在于 `local_life_agent/domain/graph_state.py`。

### 8.1 `local_life_agent/semantic/intent_parser.py`

- 当前观察到的问题：LLM 语义解析有超时与 schema 失败风险，重试策略可能没有改变失败条件。
- 建议修改点：失败后切换短 prompt 或规则兜底；显式暴露 parse_status。
- 是否 P0：是。
- 是否会影响已有链路：会，影响所有依赖 semantic frame 的工作流入口。
- 需要补哪些测试：长上下文超时、schema fail 后降级、规则解析兜底。

### 8.2 `local_life_agent/target/reference_resolver.py`

- 当前观察到的问题：`_infer_comparison_mentions_from_text` 比较词过宽，且 `_resolve_explicit` 存在 legacy/entity 双路径放大。
- 建议修改点：comparison guard 收紧；显式解析只走一个主入口；加幂等。
- 是否 P0：是。
- 是否会影响已有链路：会，主要影响 comparison / recommendation / nearby search。
- 需要补哪些测试：`性价比` 不触发 comparison、同一 query 不重复解析、低置信片段不进入精确解析。

### 8.3 `local_life_agent/target/shop_resolver.py`

- 当前观察到的问题：legacy resolve 与 entity resolve 的关系需要统一收口。
- 建议修改点：把 legacy 作为 gateway 内部 fallback adapter，而不是并列入口。
- 是否 P0：是。
- 是否会影响已有链路：会，但属于可控迁移。
- 需要补哪些测试：legacy fallback 正常、gateway 主路径正常、重复调用被 dedupe。

### 8.4 `local_life_agent/planning/evidence/evidence_planner.py`

- 当前观察到的问题：`has_location` 依赖坐标，没坐标时 distance facet 直接跳过。
- 建议修改点：引入 GeoContext；无坐标时显式记录 missing_reason；避免静默跳过。
- 是否 P0：是。
- 是否会影响已有链路：会，影响距离、ETA、附近推荐。
- 需要补哪些测试：地名 resolved / unresolved 两种路径、distance skip reason、坐标存在时 distance facet 被规划。

### 8.5 `local_life_agent/planning/evidence/evidence_review.py`

- 当前观察到的问题：LLM review 可能偏重，且容易与 decision 层 schema 断层。
- 建议修改点：review 前做 deterministic precheck；review 只处理语义权衡；共享候选 / evidence schema。
- 是否 P0：是。
- 是否会影响已有链路：会，但可以通过保守输出控制。
- 需要补哪些测试：evidence sufficient、partial insufficient、unknown/failed 显式暴露。

### 8.6 `local_life_agent/planning/decision/decision_planner.py`

- 当前观察到的问题：可能在 evidence sufficient 时返回 unsupported / 空 candidates。
- 建议修改点：允许 conservative_decision；空决策视为异常；对候选提取做契约校验。
- 是否 P0：是。
- 是否会影响已有链路：会，影响推荐、比较、单店问答的最终决策。
- 需要补哪些测试：sufficient 不空决策、部分证据保守决策、unsupported 仅限真不可答。

### 8.7 `local_life_agent/planning/decision/candidate_decision.py`

- 当前观察到的问题：候选集容易被解析污染，距离 / 城市过滤依赖上游 location 质量。
- 建议修改点：在候选生成前加入 city / geo 约束；不要让跨城店混入最终排名。
- 是否 P0：是。
- 是否会影响已有链路：会，但属于正确性修复。
- 需要补哪些测试：同城过滤、跨城剔除、距离 score 依赖坐标。

### 8.8 `local_life_agent/answer/generator.py`

- 当前观察到的问题：答案生成路径有 fallback 丢事实风险，coupon / distance evidence 可能在降级后消失。
- 建议修改点：统一从 EvidencePack 读事实；fallback 输出必须保守但不清空事实。
- 是否 P0：是。
- 是否会影响已有链路：会，影响最终文本。
- 需要补哪些测试：coupon evidence 保留、distance 缺失原因保留、fallback 不重新判空。

### 8.9 `local_life_agent/answer/verifier.py`

- 当前观察到的问题：verifier 需要确认 answer 是否正确引用证据，但不能反向改写事实。
- 建议修改点：增强对 coupon / distance 的证据一致性检查；不要让 verifier 导致事实被擦除。
- 是否 P1：是。
- 是否会影响已有链路：中等，主要影响最终校验与重写。
- 需要补哪些测试：优惠券存在时回答必须提及、距离有值时必须提及、unknown 不能被写成 no。

### 8.10 `local_life_agent/tools/db_tools.py`

- 当前观察到的问题：distance 计算工具本身可用，但前提是上游必须传入坐标。
- 建议修改点：保持工具纯粹；补充对缺少 origin/destination 的明确错误语义。
- 是否 P0：否，更多是契约配合。
- 是否会影响已有链路：低，只要不改变已存在工具返回结构。
- 需要补哪些测试：坐标存在时距离计算、坐标缺失时错误明确。

### 8.11 `local_life_agent/engine/workflow_registry.py`

- 当前观察到的问题：工作流注册是白名单式的，这很好，但需要确保新增 guard 不绕开 registry。
- 建议修改点：保持单一注册入口；新增工作流必须显式注册；不要引入平行 runner。
- 是否 P1：是。
- 是否会影响已有链路：低到中，主要影响新增 / 替换工作流时的安全性。
- 需要补哪些测试：未注册 workflow 拒绝、注册表查找、合法 workflow 正常分发。

### 8.12 `local_life_agent/domain/graph_state.py`

- 当前观察到的问题：GraphState 是跨节点事实传递的中心，需要承载 semantic_frame / evidence_pack / decision 的一致性。
- 建议修改点：确认 location / geo / evidence / decision 字段命名统一；不要把事实分散写到多个节点私有 state。
- 是否 P0：是。
- 是否会影响已有链路：会，属于事实载体对齐。
- 需要补哪些测试：state 写回完整性、evidence_pack 传递、fallback 不丢字段。

---

## 9. Anti-Patterns to Avoid

1. 只把 LLM timeout 从 20 秒改到 40 秒。
2. 只给“性价比”写 hardcode 特判。
3. 继续让 legacy resolver 和 gateway resolver 并列调用。
4. 在 fallback answer 中重新查 state 或重新判空。
5. 没有 GeoContext 就直接全国搜索并排序。
6. `evidence_review` 用 LLM 判断 coupon 是否存在。
7. evidence sufficient 后允许 `decision_planner` 返回 unsupported + []。
8. 为了修本问题重写整个 LangGraph `graph_builder`。
9. 一次性删除 legacy path。
10. 新增工具但不注册到统一 tool gateway / workflow registry。

---

## 10. Acceptance Criteria

文档所描述的方案，至少要能回答并满足以下问题：

1. 这次问题到底是架构问题、契约问题还是 bug？
2. 哪些必须 P0 修？
3. 哪些不应该现在重构？
4. `resolve_shop` 如何避免重复调用？
5. “性价比”如何不再误触发 comparison？
6. 地名如何变成坐标？
7. 没有坐标时如何保守降级？
8. 查到优惠券但 decision 降级时，为什么最终回答不能丢券？
9. `evidence_review` sufficient 时，为什么不能空决策？
10. 如何通过测试防止回归？

验收标准建议写成：

- 主链路不再出现同一 query 的重复解析风暴。
- 有地名时先 geocode，再决定是否 distance planning。
- 已获得 coupon evidence 不会在 fallback 中丢失。
- `decision_planner` 在 sufficient 场景下不会输出空候选。
- 回归测试能稳定覆盖 comparison、location、coupon、distance、decision 四条关键链路。

---

## 11. Migration Strategy

### 11.1 Phase 0: 先收口，不重写

- 统一 semantic frame 与 GeoContext 的最小契约。
- 给 resolve_shop 加幂等与预算。
- 让 EvidencePack 成为事实传递的唯一主干。

### 11.2 Phase 1: 逐步替换 legacy

- 先让 gateway 吸收 legacy。
- 再减少 legacy 调用点。
- 最后再考虑下线 legacy adapter。

### 11.3 Phase 2: 提升可观测性

- 增加 span / metrics。
- 增加 P0 回归测试。
- 观察是否还有空决策、重复解析、证据丢失。

### 11.4 迁移边界

本轮只建议做：

- 统一入口
- 补契约
- 加幂等
- 加 guard
- 补测试

本轮不建议做：

- 重写整个图编排
- 推翻现有 workflow registry
- 删除 legacy
- 用单个超级 LLM 代理替代流程控制

---

## 12. Final Recommendation

最终建议是：

1. **先修 P0 链路**
   - comparison guard
   - resolve_shop 单入口 + 幂等 + budget
   - GeoContext / geocode 契约
   - EvidencePack 统一传递
   - evidence_review / decision_planner 对齐
   - evidence-based fallback

2. **再修 P1 性能**
   - 改 retry 策略
   - 改 review 输入压缩
   - 改 stage timeout

3. **最后修 P2 可观测性**
   - span / metrics
   - 回归测试

核心原则不变：

```text
LLM 用来理解语义，不用来无约束决定流程。
流程用契约和 guard 收口，事实用 EvidencePack 贯通。
```

