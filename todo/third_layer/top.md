请你严格基于当前仓库真实代码，调研并设计“第三层：回答层 / 可信表达层”的全面升级方案，将方案文档输出到 `todo/third_layer/` 目录。

重要要求：

1. 只做代码调研和方案文档，不要直接修改业务代码。
2. 不要根据经验脑补，必须以当前仓库真实代码为准。
3. 如果已有文档描述和真实代码不一致，以真实代码为准，并在报告中指出偏差。
4. 本次目标是：调研当前第三层真实实现，参考业界 generator-verifier / guardrail / response contract / claim-based verification / deterministic fallback / tracing 模式，设计可执行的升级方案。
5. 方案必须适配本地生活 Agent，不要给泛泛的 ChatBot 设计。
6. 最终请把所有分析和解决方案放到 `todo/third_layer/` 下。如果目录不存在，请创建。
7. 不要声称已经完成改造，只能说“已形成解决方案文档”。
8. 不要直接改业务代码，不要删除文件，不要迁移 import。
9. 必须关注回答效果、事实可信、运行速度、LLM 调用成本、降级质量、复杂回答一致性、trace 可观测、与第二层新架构衔接等问题。

本次调研范围：

重点扫描以下模块及其直接依赖：

* `local_life_agent/engine/subgraphs/response_subgraph.py`
* `local_life_agent/answer/generator.py`
* `local_life_agent/answer/llm_verbalizer.py`
* `local_life_agent/answer/verifier.py`
* `local_life_agent/answer/` 下所有回答生成、验证、模板、fallback 相关模块
* `local_life_agent/engine/workflows/direct_response_workflow.py`
* `local_life_agent/engine/workflows/deterministic_tool_workflow.py`
* `local_life_agent/engine/workflows/clarification_fallback_workflow.py`
* `local_life_agent/engine/workflows/exploration_planning_workflow.py`
* `local_life_agent/engine/workflow_runner.py`
* `local_life_agent/engine/workflow_registry.py`
* `local_life_agent/engine/_routes.py`
* `local_life_agent/domain/graph_state.py`
* `local_life_agent/domain/state.py`
* `local_life_agent/domain/schemas.py`
* 与 `AnswerPlan`、`DecisionPlan`、`EvidencePack`、`FinalDecisionPlan`、`GlobalEvidencePack`、`ResponseMode`、`ResponseContract`、`VerifierResult`、`SessionState`、`final_response`、`draft_response`、`response_route`、`response_mode` 相关的定义和测试

请优先确认当前第三层真实数据流：

```text
来自第二层:
  DecisionPlan / EvidencePack / pending_clarification / response_mode
        ↓
response_subgraph
        ↓
answer_plan_build
        ↓
answer_generate / LLM Verbalizer
        ↓
answer_verify
        ↓
pass / rewrite / fallback
        ↓
final_response
        ↓
state_update_plan
```

同时确认独立 workflow 的真实路径：

```text
workflow_runner
  → direct_response_workflow
  → deterministic_tool_workflow
  → clarification_fallback_workflow
  → exploration_planning_workflow
  → response_subgraph
  → state_update_plan
```

当前报告中提到的已知事实需要核验：

1. `response_subgraph` 是否根据 `response_mode` 分支处理 direct / reject / clarify / fallback / answer / tool_answer / comparison / exploration_plan。
2. `response_mode` 是否没有统一 Enum，而是分散字符串。
3. `_h_answer_plan_build` 是否读取 `p2_decision_plan`，写入 `answer_plan`。
4. `AnswerPlan` 是否包含 `allowed_claims`、`required_claims`、`forbidden_claims`、`must_mention_unknowns`、`factual_points`、`uncertainty_notes` 等字段。
5. `generate_answer()` 是否主要走 LLM verbalizer。
6. `ENABLE_LLM_VERBALIZER == False` 时是否返回固定占位符，而不是 deterministic composer。
7. LLM 失败 / 超时 / 输出空时当前 fallback 行为是什么。
8. `_compose_single_shop_response()` 是否只覆盖单店 coupon / open_status / distance 等有限 facet。
9. `verify_answer()` 是否在 evidence 为空或 draft_response 为空时直接 pass。
10. verifier 是否主要通过中文关键词 / 文本规则校验 coupon、open_status、distance、rating、price、comparison 等事实。
11. 是否存在 claim-based verification：从回答中抽取结构化 claims，再和 EvidencePack 对齐。
12. LLM verifier 是否只在 comparison / exploration_plan 等复杂类型触发。
13. `_h_rewrite` 是否只是递增 rewrite_count，并没有构造结构化 RewriteInstruction。
14. `MAX_REWRITE_ATTEMPTS` 的语义是否容易误解，实际重写次数是否等于配置值减一。
15. `_h_fallback_answer` 的覆盖范围是否主要集中在单店营业、优惠券、工具失败、熔断、unknown/unsupported。
16. `direct_response_workflow` 是否在第三层重新做关键词分类，例如退款、下单、你好、能做什么等。
17. `deterministic_tool_workflow` 是否在回答层边界内自行完成目标解析、工具调用、EvidencePack 构建、AnswerPlan 构建、文本回答、verify。
18. `exploration_planning_workflow` 是否在回答层边界内自行完成子目标构建、工具搜索、证据构建、确定性回答、verify。
19. 独立 workflow 是否会提前写 `final_response`，从而绕过统一 LLM verbalizer / verifier / ResponseContract。
20. 所有回答路径是否都有统一 `ResponseContract`。
21. 所有回答路径是否都能追踪 evidence_ref / claim_ref / verifier_result / degraded_reason。
22. 第三层是否会写入或污染跨轮 SessionState。
23. 第三层 trace 是否能解释 answer_plan、generation、verification、rewrite、fallback、final_response 的耗时和原因。

请输出到 `todo/third_layer/`，建议文件结构：

```text
todo/third_layer/
  01_third_layer_fact_baseline.md
  02_third_layer_problem_analysis.md
  03_third_layer_target_architecture.md
  04_third_layer_contract_design.md
  05_third_layer_response_pipeline_design.md
  06_third_layer_claim_verifier_design.md
  07_third_layer_fallback_rewrite_design.md
  08_third_layer_workflow_boundary_design.md
  09_third_layer_trace_eval_latency_design.md
  10_third_layer_migration_plan.md
  11_third_layer_test_plan.md
```

如果你认为合并更合适，可以合并，但必须保证内容完整。

一、`01_third_layer_fact_baseline.md`

请写清楚真实代码现状：

* 第三层真实调用链
* `response_subgraph` 的入口、分支、读写 state 字段
* 当前所有 `response_mode` / `response_route` 取值来源和消费位置
* `AnswerPlan` / `DecisionPlan` / `EvidencePack` / `final_response` / `draft_response` 的真实字段流转
* `generate_answer()` 和 `llm_verbalizer.py` 的真实行为
* `verify_answer()` 的真实校验路径
* deterministic verifier 和 LLM verifier 的触发条件
* rewrite 循环真实次数和预算逻辑
* fallback 真实覆盖范围
* direct_response / deterministic_tool / clarification_fallback / exploration_planning 四个 workflow 的真实职责
* 哪些独立 workflow 会执行工具、构建 evidence、生成 final_response
* 哪些路径可能绕过统一回答流水线
* 当前缺失能力：ResponseMode Enum、ResponseContract、ClaimExtractor、ClaimVerifier、RewriteInstruction、ResponsePolicy、multi-type deterministic composer、evidence_ref trace 等

要求：每个结论都要标注对应文件和函数名，最好带行号。

二、`02_third_layer_problem_analysis.md`

请按 P0 / P1 / P2 分析问题。

必须覆盖以下 P0 问题：

1. 第三层边界不纯
   风险：回答层混入工具执行、目标解析、EvidencePack 构建、探索规划执行，导致第二层和第三层职责重叠。

2. 独立执行型 workflow 放在回答层边界内
   风险：`deterministic_tool_workflow` / `exploration_planning_workflow` 可能应该归入第二层对应 workflow，而第三层只消费它们产出的 EvidencePack / DecisionPlan。

3. `response_mode` 没有统一 Enum
   风险：跨层字符串分散，容易出现某个模式误入错误分支，或绕过 verifier。

4. evidence 为空或 draft 为空时 verify 直接 pass
   风险：事实型回答在没有证据时也可能通过校验。

5. LLM verbalizer 关闭或失败时 fallback 不合理
   风险：返回“LLM 未启用”这类占位符，而不是基于 AnswerPlan / EvidencePack 生成可用回答。

6. 所有回答路径没有统一 ResponseContract
   风险：有的回答有 AnswerPlan，有的没有；有的经过 verifier，有的没有；有的有 evidence_ref，有的没有。

7. verifier 过度依赖文本规则
   风险：规则堆叠、表达覆盖不足、维护成本上升，LLM 换说法后误判或漏判。

8. 复杂回答缺少结构化 claim 对齐
   风险：推荐、对比、规划回答中每句话是否有证据支撑难以追踪。

必须覆盖以下 P1 问题：

9. `_h_rewrite` 只是递增计数，缺少结构化 RewriteInstruction。
10. `MAX_REWRITE_ATTEMPTS` 语义容易误解。
11. fallback composer 主要偏单店，推荐 / 对比 / 探索规划 fallback 不足。
12. `direct_response_workflow` 重新做关键词分类，与第一层 hard_guard / top_intent 可能重叠。
13. `AnswerPlan`、`DecisionPlan`、`FinalDecisionPlan` 字段命名和消费入口不统一。
14. `exploration_planning_workflow` 有模板化倾向，不适合继续留在回答层主边界。
15. 第三层 trace 不足，无法完整解释生成、校验、重写、降级原因。
16. 不同复杂度回答缺少 ResponsePolicy 控制格式、长度、未知项、trade-off。

必须覆盖以下 P2 问题：

17. `template_fallback` 覆盖范围有限。
18. 回答质量缺少 eval case 集。
19. latency / cost benchmark 不完整。
20. 多轮 continuity 对回答风格和上下文承接的约束不明确。
21. trusted_failure_message / fallback message 的来源和可信等级不统一。
22. response_subgraph 和独立 workflow 之间的 trace 字段可能不一致。

三、`03_third_layer_target_architecture.md`

请给出目标架构，参考业界模式，但必须适配本地生活 Agent。

目标形态：

```text
第三层 = 可信表达层，不再承担工具执行和证据规划

输入:
  DecisionPlan / FinalDecisionPlan
  EvidencePack / GlobalEvidencePack
  ResponsePolicy
  ClarificationRequest / FallbackDirective

输出:
  ResponseContract
  final_response
  preview_text
  verifier_result
  response_trace
```

建议目标流水线：

```text
response_subgraph
  → response_input_normalizer
  → answer_contract_builder
  → response_policy_resolver
  → verbalizer_or_composer
  → claim_extractor
  → claim_verifier
  → rewrite_or_fallback
  → final_response_builder
  → state_update_plan
```

请说明每个模块职责：

1. `response_input_normalizer`
   统一消费 DecisionPlan、FinalDecisionPlan、EvidencePack、GlobalEvidencePack、ClarificationRequest、FallbackDirective。

2. `answer_contract_builder`
   构建 AnswerContract / AnswerPlan，包括 allowed_claims、required_claims、forbidden_claims、unknowns、evidence_refs、response_sections。

3. `response_policy_resolver`
   按 answer_type / workflow_kind / task_complexity 决定回答风格、长度、是否展示 trade-off、是否必须展示 unknown、最大推荐数量。

4. `verbalizer_or_composer`
   优先 LLM verbalizer；LLM 不可用或简单事实场景走 deterministic composer。

5. `claim_extractor`
   从 draft_response 中抽取结构化 AnswerClaim。

6. `claim_verifier`
   将 AnswerClaim 与 EvidencePack / GlobalEvidencePack 对齐，判断 supported / unsupported / contradicted / unknown。

7. `rewrite_or_fallback`
   基于 VerifierViolation 生成 RewriteInstruction，必要时 deterministic fallback。

8. `final_response_builder`
   生成统一 ResponseContract 和 final_response。

请强调：

* 第三层不执行远程工具。
* 第三层不做目标解析。
* 第三层不构建 EvidencePack。
* 第三层不做推荐排序。
* 第三层不写 SessionState。
* 第三层只负责把第二层已经确定的事实和决策安全表达出来。

四、`04_third_layer_contract_design.md`

请设计或建议新增这些契约对象，并说明它们属于 GraphState、Domain DTO、Trace 还是 Response DTO：

```python
ResponseMode
ResponseRoute
AnswerType
ResponseInput
AnswerContract
AnswerClaim
ClaimSupportStatus
ClaimVerificationResult
VerifierViolation
RewriteInstruction
ResponsePolicy
FallbackDirective
ClarificationResponsePlan
ResponseContract
ResponseTrace
GenerationTrace
VerificationTrace
RewriteTrace
FallbackTrace
```

必须说明：

* `ResponseMode` 必须统一 Enum，禁止散落字符串。
* `ResponseInput` 是第三层统一入口。
* `AnswerContract` 是 verbalizer 和 verifier 的共同约束。
* `AnswerClaim` 必须包含 claim_type、shop_id、value、evidence_ref、support_status。
* `ResponseContract` 是所有回答路径统一输出。
* Direct response、clarification、fallback、answer、tool_answer、comparison、exploration_plan 都必须输出 ResponseContract。
* Worker 或独立 workflow 不能直接写 final_response 后绕过 ResponseContract。
* 如果第二层未来输出 FinalDecisionPlan / GlobalEvidencePack，第三层必须能兼容。

五、`05_third_layer_response_pipeline_design.md`

请设计新的 response_subgraph。

必须覆盖以下路径：

### 1. Direct response

输入：

```text
DirectResponsePlan / Capability / Unsafe / OutOfScope / Invalid
```

输出：

```text
ResponseContract(answer_type="direct" / "error" / "clarification")
```

要求：

* 不重新做复杂意图分类。
* 只消费第一层 / 第二层已经给出的 direct response directive。
* 可以用确定性 composer。

### 2. Clarification response

输入：

```text
pending_clarification / ClarificationRequest / resolve_shop_result
```

输出：

```text
ClarificationResponsePlan → ResponseContract
```

要求：

* 问题要短。
* 多候选时展示编号。
* expired / invalid / out_of_range 要有清晰提示。
* 不进入 LLM verbalizer 大链路。

### 3. Fallback response

输入：

```text
FallbackDirective / error_code / failed_facets / unknown_facets / degraded_reason
```

输出：

```text
FallbackComposer → ResponseContract
```

要求：

* 不暴露内部错误。
* 说明能确认什么、不能确认什么。
* 本地生活场景要区分工具失败、没有结果、证据不足、能力不支持、系统降级。

### 4. Normal answer

输入：

```text
DecisionPlan / EvidencePack
```

流程：

```text
AnswerContract
→ LLM Verbalizer / DeterministicComposer
→ ClaimExtractor
→ ClaimVerifier
→ pass / rewrite / fallback
→ ResponseContract
```

### 5. Complex answer

输入：

```text
FinalDecisionPlan / GlobalEvidencePack / EvidenceConflict
```

流程：

```text
AnswerContract
→ ResponsePolicy
→ LLM Verbalizer
→ ClaimExtractor
→ ClaimVerifier
→ trade-off / unknown / conflict disclosure
→ ResponseContract
```

要求：

* 不能拼接多个 worker 的自然语言。
* 必须基于 FinalDecisionPlan 统一表达。
* 对冲突事实必须透明表达 unknown / trade-off。

六、`06_third_layer_claim_verifier_design.md`

请专门设计 claim-based verification 方案。

当前 verifier 可以保留为快速 deterministic guard，但目标应升级为：

```text
draft_response
  → ClaimExtractor
  → AnswerClaim[]
  → ClaimVerifier
  → ClaimVerificationResult
```

必须覆盖本地生活 claim 类型：

```python
coupon_available
coupon_empty
open_status_open
open_status_closed
distance_value
distance_type
rating_value
avg_price_value
review_summary_claim
recommendation_ranking
comparison_winner
dimension_winner
scene_fit_claim
business_hours_claim
unknown_facet_notice
degraded_notice
```

每个 claim 至少包含：

```python
claim_id
claim_type
shop_id
shop_name
facet
value
text_span
evidence_ref
support_status
violation_code
```

support_status：

```text
supported
unsupported
contradicted
unknown_required
not_applicable
```

必须说明：

* 工具事实优先于 LLM 表述。
* unknown 不能被说成 available / empty / open / closed。
* 直线距离不能说成步行 / 开车 / ETA，除非 evidence 支持。
* 推荐排名不能被 LLM 改写。
* 对比 winner 不能与 comparison_matrix / FinalDecisionPlan 冲突。
* 有 unknown_facets 时必须在回答中提及。
* 如果 claim extraction 失败，复杂回答应进入 LLM verifier 或 conservative fallback。

七、`07_third_layer_fallback_rewrite_design.md`

请设计 fallback 和 rewrite。

### RewriteInstruction

不要只递增 rewrite_count。必须设计：

```python
RewriteInstruction:
    violation_codes
    unsupported_claims
    contradicted_claims
    required_additions
    forbidden_claims
    unknowns_to_mention
    claims_to_keep
    max_length
    tone
```

### RewritePolicy

按 answer_type 控制：

```text
single_shop_fact:
  max_rewrite_rounds = 0~1
  prefer deterministic composer

recommendation:
  max_rewrite_rounds = 1
  require ranking preserved

comparison:
  max_rewrite_rounds = 1
  require winner preserved

exploration_plan:
  max_rewrite_rounds = 1
  require itinerary stages preserved

complex:
  max_rewrite_rounds = 1
  require FinalDecisionPlan preserved
```

### DeterministicComposer

必须补齐多类型 fallback：

```text
SingleShopFactComposer
RecommendationComposer
ComparisonComposer
ExplorationPlanComposer
ClarificationComposer
SystemFallbackComposer
```

要求：

* LLM disabled / timeout / empty output 时，不要返回占位符。
* 只要 AnswerContract + EvidencePack 足够，就输出可用的确定性回答。
* 如果证据不足，输出可信降级回答。
* fallback 不能编造。
* fallback 必须进入 ResponseContract。

八、`08_third_layer_workflow_boundary_design.md`

请专门分析并设计第三层和独立 workflow 的边界迁移。

必须回答：

1. `deterministic_tool_workflow` 是否应该迁移到第二层 `single_shop_fact_workflow`？
2. `exploration_planning_workflow` 是否应该迁移到第二层 `exploration_planning_workflow`？
3. `direct_response_workflow` 是否可以保留在第三层，还是应改为第一层 / 第二层产出 DirectResponsePlan，第三层只负责表达？
4. `clarification_fallback_workflow` 是否应该收敛为 ClarificationResponsePlan / FallbackDirective？
5. 当前哪些 workflow 会直接写 final_response？
6. 哪些路径绕过统一 AnswerPlan / Verifier / ResponseContract？
7. 迁移时如何保留 legacy alias 和回归稳定？

目标边界：

```text
第一层：输入、上下文、澄清恢复、意图识别
第二层：任务决策、目标解析、工具执行、证据构建、推荐/对比/规划决策
第三层：可信表达、回答验证、重写、降级、最终 ResponseContract
```

九、`09_third_layer_trace_eval_latency_design.md`

请设计 trace、eval 和性能方案。

Trace 至少包含：

```text
response_input_span
answer_contract_span
generation_span
claim_extraction_span
verification_span
rewrite_span
fallback_span
final_response_span
```

每个 span 记录：

```text
input_summary
output_summary
answer_type
response_mode
source
latency_ms
llm_called
token_estimate
verifier_passed
violation_codes
rewrite_count
fallback_reason
degraded
evidence_ref_count
unknown_facet_count
```

Eval 必须覆盖：

* 单店有券
* 单店无券
* 单店营业中
* 单店未营业
* 距离直线距离
* 推荐排序
* 推荐 unknown facet
* 多店对比 winner
* comparison_matrix 不允许被改写
* 探索规划时间线
* 复杂 FinalDecisionPlan 回答
* LLM 关闭
* LLM timeout
* verifier 失败 rewrite
* rewrite 超限 fallback

Latency / cost benchmark：

* direct response 不调用 LLM。
* clarification 不调用 LLM。
* single_shop_fact 简单回答优先 deterministic composer。
* recommendation / comparison 允许 LLM verbalizer，但限制 rewrite。
* complex answer 允许 LLM verbalizer + claim verifier，但不能多轮无限重写。

十、`10_third_layer_migration_plan.md`

请给出渐进式迁移计划，不要推倒重来。

建议阶段：

### Phase A：事实冻结与边界测试

* 输出第三层真实调用链。
* 输出所有 response_mode / response_route 值域。
* 输出所有 final_response 写入位置。
* 输出所有 verifier pass / skip 条件。
* 输出所有 fallback 来源。
* 不改业务代码。

### Phase B：统一 ResponseMode / ResponseRoute Enum

* 收敛散落字符串。
* 增加边界测试。
* 保持兼容旧值。

### Phase C：新增 ResponseInput / ResponseContract

* 所有回答路径统一输出 ResponseContract。
* direct / clarify / fallback / answer 都纳入统一契约。

### Phase D：修复 verifier 高风险 pass 条件

* evidence 为空不能让事实型 answer pass。
* draft 为空不能 pass。
* trusted direct / clarification / fallback 可按 ResponseMode 跳过事实 verifier。

### Phase E：LLM disabled / failed fallback 改造

* 不再返回占位符。
* 走 deterministic composer / fallback composer。

### Phase F：引入 ResponsePolicy

* 按 answer_type 控制格式、长度、unknown、trade-off、max_items。

### Phase G：引入 ClaimExtractor / ClaimVerifier

* 先保留当前 deterministic verifier。
* 逐步把 coupon / open_status / distance / comparison / recommendation 迁移到 claim-based verifier。
* LLM verifier 作为复杂回答兜底。

### Phase H：结构化 RewriteInstruction

* verifier 输出 violation → rewrite instruction。
* 不再只递增 rewrite_count。

### Phase I：补多类型 DeterministicComposer

* recommendation / comparison / exploration / complex fallback 都有可信回答能力。

### Phase J：收敛独立 workflow 边界

* 将执行型 workflow 迁往第二层方案中对应 workflow。
* 第三层只消费 DecisionPlan / EvidencePack / FinalDecisionPlan / GlobalEvidencePack。
* 保留 legacy alias 过渡。

### Phase K：trace / eval / latency 验收

* 全量测试。
* latency benchmark。
* cost benchmark。
* 回答可信性 eval。
* 多复杂度场景 E2E。

十一、`11_third_layer_test_plan.md`

请给出测试计划，不要编造当前已存在的测试文件名。新增建议测试必须用 `TODO_ADD_TEST:` 标记。

必须覆盖：

1. 所有 `response_mode` 都来自统一 Enum。
2. 未知 response_mode 被安全 fallback，不误入正常 answer。
3. direct response 输出 ResponseContract。
4. clarification 输出 ResponseContract。
5. fallback 输出 ResponseContract。
6. normal answer 输出 ResponseContract。
7. fact answer 没有 evidence 时 verifier 不 pass。
8. draft_response 为空时 verifier 不 pass。
9. LLM verbalizer disabled 时不返回占位符，走 deterministic composer。
10. LLM timeout 时走 deterministic composer 或 fallback composer。
11. 单店 coupon claim 正确对齐 evidence。
12. coupon unknown 不能被说成有券或无券。
13. open_status unknown 不能被说成营业中或已打烊。
14. distance 直线距离不能被说成步行/开车/预计时间。
15. rating / price 数值不能被 LLM 改写。
16. recommendation ranking 不能被 LLM 改写。
17. comparison winner 不能和 DecisionPlan / comparison_matrix 冲突。
18. unknown_facets 必须被提及。
19. verifier violation 能生成 RewriteInstruction。
20. rewrite 后仍不通过会进入 fallback。
21. rewrite 不改变 winner / ranking / factual claims。
22. RecommendationComposer 能在 LLM 失败时输出可信简短回答。
23. ComparisonComposer 能在 LLM 失败时输出 winner + trade-off。
24. ExplorationPlanComposer 能在 LLM 失败时输出时间线。
25. complex FinalDecisionPlan 不允许拼接 worker 自然语言。
26. 独立 workflow 直接写 final_response 的路径被列出并纳入迁移计划。
27. 第三层不执行工具调用。
28. 第三层不写 SessionState。
29. response trace 包含 generation / verification / rewrite / fallback span。
30. direct / clarification 不调用 LLM。
31. single_shop_fact 简单回答 LLM 调用次数不增加。
32. comparison / recommendation 主链路不退化。
33. exploration planning 回答不编造未查证地点或距离。
34. fallback 不暴露内部异常。
35. trusted_failure_message 必须有可信来源和 trace。

建议新增测试文件用：

```text
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_response_mode_enum.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_response_contract.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_verifier_no_empty_pass.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_llm_disabled_fallback.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_extractor.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier_coupon.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier_open_status.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier_distance.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier_recommendation.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier_comparison.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_rewrite_instruction.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_deterministic_composers.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_workflow_boundary.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_trace_contract.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_latency_budget.py
```

最终输出要求：

1. 输出实际扫描的文件列表。
2. 输出第三层真实调用链。
3. 输出文档与真实代码偏差。
4. 输出所有 `response_mode` / `response_route` 值域和来源。
5. 输出所有 `final_response` 写入位置。
6. 输出 P0 / P1 / P2 问题清单。
7. 输出目标架构。
8. 输出 ResponseContract / ClaimVerifier / RewriteInstruction / ResponsePolicy 设计。
9. 输出 direct / clarify / fallback / normal / complex 五类回答路径设计。
10. 输出 claim-based verification 设计。
11. 输出 deterministic fallback composer 设计。
12. 输出独立 workflow 边界迁移方案。
13. 输出 trace / eval / latency / cost 设计。
14. 输出渐进迁移计划。
15. 输出测试计划和验收标准。
16. 所有文档写入 `todo/third_layer/`。
17. 不要修改业务代码。
18. 不要删除旧 workflow。
19. 不要声称已经完成修复。
20. 如果发现当前第三层报告结论与真实代码不一致，请单独列出，不要直接覆盖原报告。
