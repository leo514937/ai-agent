# 第三层文件级实施计划

本文件按 Phase 列出每步需要新增/修改的具体文件、兼容策略、新增测试和回滚方式。

---

## Phase A：事实冻结与边界测试（安全不动）

**目标**：不修改代码，只运行现有测试验证基线。

| 操作 | 具体内容 |
|---|---|
| 运行基线 | `pytest local_life_agent/tests/test_answer_verifier.py test_llm_verbalizer.py test_p4_evidence_decision_answer_protocol.py test_phase7_workflows.py test_e2e_llm_main_path.py -q` |
| 记录基线延迟 | 单店 simple fact 回答的端到端延迟 |
| 验证所有 test case | 确认当前所有回答层测试为绿色 |

**新增文件**：无
**修改文件**：无
**旧字段兼容策略**：不需要
**新增测试**：无
**验收标准**：所有现有测试通过
**回滚方式**：无变更，无需回滚

---

## Phase B：统一 ResponseMode Enum

**目标**：不再依赖散落字符串，替换 GraphState 中的 `response_mode` 字段。

> ⚠️ **语义完整性**：`REJECT` 与 `DIRECT` 保持独立（`reject` 是安全拒答，非普通回答）；`COMPARISON` 与 `ANSWER` 保持独立（comparison 有 `ComparisonMatrix`/`winner`/`trade-off` 约束）

### ResponseMode 定义

```python
class ResponseMode(str, Enum):
    DIRECT = "direct"              # 替代 "direct_response" / "direct"
    REJECT = "reject"              # 独立语义：安全拒答 / 非法请求
    CLARIFY = "clarify"            # 替代 "clarify"
    FALLBACK = "fallback"          # 替代 "fallback"
    ANSWER = "answer"              # 替代 "answer"
    TOOL_ANSWER = "tool_answer"    # 替代 "tool_answer"
    COMPARISON = "comparison"      # 替代 "comparison"
    EXPLORATION_PLAN = "exploration_plan"  # 替代 "exploration_plan"
```

### 新增文件

| 文件 | 职责 |
|---|---|
| `domain/enums.py`（追加） | 新增 `ResponseMode(str, Enum)` |

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `engine/subgraphs/response_subgraph.py` | `_h_response_subgraph()` 分支从字符串改为 `ResponseMode` 枚举比较 | 保留旧字符串分支作为 fallback |
| `engine/workflows/deterministic_tool_workflow.py:906` | `response_mode = "direct"` → `response_mode = ResponseMode.DIRECT` | 旧值不再写入 |
| `engine/workflows/direct_response_workflow.py:156` | 同上 | 同上 |
| `engine/workflows/exploration_planning_workflow.py:1093` | 同上 | 同上 |
| `engine/workflows/clarification_fallback_workflow.py:230` | 同上 | 同上 |
| `engine/_routes.py:310-320` | `_route_workflow_runner` 的字符串比较改为枚举比较 | 保留旧字符串做兼容 fallback |
| `observability/trace.py` | `TurnTrace.response_mode` 类型改为 `ResponseMode` | 序列化时 `str()` 输出 |

### 旧字段兼容策略

```text
Phase B 期间：
  response_mode 写入新 Enum 值
  消费方优先检查 Enum 值，未匹配则 fallback 到旧字符串比较
  Phase H 删除所有旧字符串分支
```

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_response_mode.py` | ResponseMode 枚举值覆盖所有旧字符串 |

### 验收标准

- `ResponseMode` 的每个枚举值能正确映射到旧字符串
- 所有 production 路径写入 Enum 而非字符串
- 所有字符串消费方在 Enum 未匹配时正确 fallback

### 回滚方式

```bash
# restore enum branch comparison to string comparison
git checkout -- engine/_routes.py engine/subgraphs/response_subgraph.py engine/workflows/*.py
```

---

## Phase C：引入 ResponseContract V1（最小兼容版本）

**目标**：新增统一输出合同 DTO，但采用最小字段集，不一次性引入全部增强字段。

> ⚠️ **字段拆分原则**：`ResponseContract` 分最小版（V1）和增强版（Phase K）。V1 只包含所有出口路径必须提供的基础字段，避免一次性改造面过大。

### `ResponseContract V1` 字段

```python
class ResponseContractV1(BaseModel):
    answer_text: str
    answer_type: str
    response_mode: ResponseMode
    trace_id: str | None
    verifier_result: VerifierResult | None
    fallback_reason: str | None
    uncertainty_notices: list[UncertaintyNotice] = []
```

**Phase K 再添加的增强字段**（不在 V1 中）：
- `claims: list[AnswerClaim]`
- `citations: list[EvidenceCitation]`
- `cards: list[ClaimCard]`
- `confidence_band: ConfidenceBand | None`
- `response_policy: ResponsePolicy | None`
- `clarification: str | None`  → 改为在 `fallback_reason` 中区分
- `safety_notice: str | None`

### 新增文件

| 文件 | 职责 | 包含 |
|---|---|---|
| `answer/response_contract.py` | `ResponseContractV1` / `AnswerContract` DTO | V1 字段定义、序列化、验证 |
| `answer/response_policy.py` | `ResponsePolicy` DTO | 按 answer_type 的策略定义（增强版 Phase K 再引入） |

### `AnswerContract` 字段（保持与 V1 兼容）

```python
class AnswerContract(BaseModel):
    allowed_claims: list[str]          # 改自 list[str]，Phase K 升级为 list[AnswerClaim]
    required_claims: list[str]         # 同上
    forbidden_claims: list[str]
    must_mention_unknowns: list[str]
    response_sections: list[str]
    uncertainty_policy: UncertaintyPolicy | None
```

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `domain/schemas.py` | 新增 `ResponseContractV1` 类型导入 | 旧 `AnswerPlan` 字段完全保留 |
| `answer/final_response_builder.py` | 新增 `build_response_contract_v1()` 方法，返回 `ResponseContractV1` | `build_final_response()` 保留为兼容壳 |
| `engine/subgraphs/response_subgraph.py` | `_h_final_response()` 额外输出 `ResponseContractV1` 到 GraphState | `final_response` / `preview_text` 字段完全保留 |

### 旧字段兼容策略

```text
Phase C 期间：
  final_response      ← 继续写入（兼容层）
  preview_text        ← 继续写入（兼容层）
  ResponseContractV1  ← 新增写入（暂存，Phase K 前仅用于 trace）
  
Phase K（增强版）之后：
  ResponseContract    ← 升级为增强版（全字段）
  final_response      ← 从 ResponseContract 派生
  preview_text        ← 从 ResponseContract 派生
```

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_response_contract.py` | ResponseContractV1 字段完整、序列化/反序列化正确 |
| `test_third_layer_uncertainty_notice.py` | UncertaintyNotice facet/reason/severity 正确 |

### 验收标准

- `ResponseContractV1` 可在 GraphState 中创建、读取、序列化
- `build_response_contract_v1()` 返回正确的 DTO
- 旧 `final_response` 和 `preview_text` 值与 Phase A 一致
- 所有测试通过

### 回滚方式

```bash
git checkout -- answer/response_contract.py answer/response_policy.py
git checkout -- domain/schemas.py
git checkout -- answer/final_response_builder.py engine/subgraphs/response_subgraph.py
```

---

## Phase D：修 verify 空 evidence / 空 draft pass

**目标**：修复 **P0 风险**——`response_subgraph.py:290-298` 在 evidence 或 draft 为空时直接 `verify_result="pass"`。

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `engine/subgraphs/response_subgraph.py:290-298` | `_h_answer_verify()` 中的 `if not evidence or not draft_response: return {"verify_result": "pass"}` 改为标记 `unverifiable`，触发 `_h_fallback_answer` | 保留旧逻辑为 fallback（当 `unverifiable` 标记无法处理时） |
| `answer/verifier.py` | `verify_answer()` 在 evidence 为空或 draft 为空时返回 `VerifierResult(passed=False, recoverable=True, issues=["empty_evidence_or_draft"])` | 旧 behavior（直接 pass）不再使用 |

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_verify_empty_evidence.py` | 空 evidence → 不 pass，走 fallback；空 draft → 不 pass，走 fallback |

### 验收标准

- 空 evidence 或空 draft 时 verifier 不返回 `"pass"`
- 空 evidence 或空 draft 时至少走 `_h_fallback_answer` 输出有意义兜底
- 回归测试通过

---

## Phase E：LLM disabled 时提供有意义 fallback

**目标**：修复 **P0 风险**——`generator.py:664-670` 在 `config.ENABLE_LLM_VERBALIZER == False` 时返回固定占位符，不基于证据生成回答。

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `answer/generator.py:664-670` | 当 `ENABLE_LLM_VERBALIZER == False` 时，不走固定占位符，改为调用 deterministic composer 基于 `AnswerPlan` / `EvidencePack` 生成回答 | 旧占位符保留为最末 fallback（当 composer 也失败时） |

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_llm_disabled_fallback.py` | ENABLE_LLM_VERBALIZER=False 时仍输出有意义的单店/推荐/对比文本 |

### 验收标准

- `ENABLE_LLM_VERBALIZER == False` 时不输出 `"【LLM 服务未启用】无法生成自然语言回答。"`
- 单店事实查询在 LLM 禁用时输出基于证据的确定性回答
- composer 路径无 LLM 调用

---

## Phase F：升级 rewrite（引入 RewriteInstruction）

**目标**：从 `rewrite_count += 1` 升级为结构化 `RewriteInstruction`。

### 新增文件

| 文件 | 职责 |
|---|---|
| `answer/rewrite_instruction_builder.py` | 从 `VerifierViolation` 列表生成 `RewriteInstruction` |

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `engine/subgraphs/response_subgraph.py:339-342` | `_h_rewrite` 从递增计数改为消费 `RewriteInstruction` | `rewrite_count` 保留为日志字段 |
| `answer/llm_verbalizer.py:134-152` | rewrite prompt 从纯文本改为结构化指令输入 | 旧 prompt 保留为 fallback |
| `answer/generator.py` | rewrite 路径消费 `RewriteInstruction` | 旧逻辑保留 |

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_rewrite_instruction.py` | VerifierViolation → RewriteInstruction 映射正确 |

### 验收标准

- `_h_rewrite` 不再只做计数递增
- LLM verbalizer 收到结构化 rewrite 指令
- `rewrite_count` 值仍然正确记录

### 回滚方式

```bash
git checkout -- answer/rewrite_instruction_builder.py
git checkout -- engine/subgraphs/response_subgraph.py
git checkout -- answer/llm_verbalizer.py
```

---

## Phase G：引入 ClaimExtractor + ClaimVerifier（分三级落地）

**目标**：从纯文本规则升级为 claim-based verification，但承认中文 claim 抽取的复杂度，分三级实施。

> **难度说明**：本地生活中文回答混有多种 claim 类型——事实 claim（"有 3 张优惠券"）、偏好 claim（"更适合约会"）、排序 claim（"A 比 B 好"）、unknown notice（"券的信息我没查到"）、trade-off claim（"A 评分高但 B 距离近"）。不能靠简单正则一次覆盖，需分三级。
>
> | 级别 | 策略 | 覆盖范围 | 前置依赖 |
> |---|---|---|---|
> | **Level 1** | 从 `AnswerPlan` / `DecisionPlan` 的 `allowed_claims` / `required_claims` 直接生成 `expected claims` | 单店事实 claim（coupon/open_status/distance/rating/price） | Phase F（RewriteInstruction） |
> | **Level 2** | 从 deterministic composer 输出的文本中回填 claim span（位置标注） | 单店 + 推荐排序 claim | Phase I（多类型 composer） |
> | **Level 3** | 对 LLM verbalizer 输出使用 LLM structured extraction，再由 deterministic verifier 对齐 EvidencePack | 全部类型（comparison/exploration/LLM generated） | Phase K（ResponseContract 增强版） |
>
> **当前 Phase G 只实施 Level 1**。Level 2 在 Phase I 之后，Level 3 在 Phase K 之前。

### 新增文件

| 文件 | 职责 |
|---|---|
| `answer/claim_extractor.py` | Level 1：从 `AnswerPlan.allowed_claims` 生成 `AnswerClaim` 列表（factual_points / uncertainty_notes 直接映射） |
| `answer/claim_verifier.py` | 将 `AnswerClaim` 与 `EvidencePack` 对齐，输出 `supported/unsupported/contradicted/unknown` |

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `answer/verifier.py` | 新增 `claim_based_verify()` 路径 | 旧 `verify_answer()` 保留为 fallback |
| `answer/b2_mini_verifier.py` | 新增 claim 级 LLM 校验指令 | 旧整体判断方式保留 |
| `engine/subgraphs/response_subgraph.py` | `_h_answer_verify` 增设 claim-based verify 分支 | 旧 verify 路径保留 |

### 旧字段兼容策略

```text
Phase G 期间（Level 1）：
  verify_answer() 同时输出：旧 issues: list[str] + 新 VerifierViolation: list[VerifierViolation]
  claim_verifier 输出存到新字段 answer_claim_verify_result
  仅覆盖确定性来源的 claim（DecisionPlan factual_points / uncertainty_notes）
  
Phase I（Level 2）后：
  claim_extractor 增加对 composer 文本的 span 回填
  Phase K（Level 3）后：
  claim_extractor 增加 LLM structured extraction
```

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_claim_extractor.py` | Level 1：单店事实 claim 从 DecisionPlan 直接映射正确 |
| `test_third_layer_claim_verifier.py` | supported/unsupported/contradicted/unknown 判定正确 |
| `test_third_layer_verifier_contract.py` | VerifierResult + VerifierViolation 命名正确 |

### 验收标准

- Level 1：ClaimExtractor 正确生成单店事实 expected claims（coupon/open_status/distance/rating/price）
- ClaimVerifier 正确定位 unsupported/contradicted claims
- 旧 `verify_answer()` 结果与新 `claim_verifier` Level 1 结果不矛盾

### 回滚方式

```bash
git checkout -- answer/claim_extractor.py answer/claim_verifier.py
git checkout -- answer/verifier.py
git checkout -- engine/subgraphs/response_subgraph.py
```

---

## Phase H：收敛 workflow bypass final_response（⚠️ P0 第一优先级）

> **核心原则**：此 Phase 必须在 Phase K（增强版 ResponseContract）之前完成。因为只要独立 workflow 还能直接写 `final_response`，加再多 ResponseContract / ClaimVerifier 都无法保证覆盖所有回答路径。这是第一批优先实施的能力。

**目标**：将 8 个 `final_response` 写入位置减少到 1 个。

### 修改文件

| 文件 | 行号 | 修改内容 |
|---|---|---|
| `engine/workflows/deterministic_tool_workflow.py` | 933 | `_build_success_patch()` 改为写 `answer_plan` + `evidence_pack`，不再写 `final_response` |
| `engine/workflows/exploration_planning_workflow.py` | 824 | `_build_success_patch()` 同上 |
| `engine/workflows/direct_response_workflow.py` | 159 | 改为写 `direct_response_payload`，由统一管线包装 |
| `engine/workflows/clarification_fallback_workflow.py` | 233 | 改为写 `clarify_request` + `fallback_directive` |
| `engine/subgraphs/response_subgraph.py` | 382-418 | `_h_clarify_response` 输出统一为 `ResponseContract.clarification` |
| `engine/subgraphs/response_subgraph.py` | 422-491 | `_h_fallback_answer` 输出统一为 `ResponseContract.fallback` |
| `engine/_routes.py` | 311-320 | 所有 bypass 路径写 `response_route = "bypass"` |

### 旧字段兼容策略

```text
Phase H 期间：
  deterministic_tool_workflow 仍写入 final_response（兼容层）
  但增加写入 answer_plan + evidence_pack（新路径）
  response_subgraph 同时消费两种路径
  Phase K（增强版）删除 final_response 兼容写入
```

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_workflow_boundary.py` | 所有 bypass 路径不绕过 ResponseContract |
| `test_third_layer_response_subgraph_boundary.py` | pass-through / clarify / fallback 路径正确 |
| `test_third_layer_unified_final_response.py` | 只有 1 个 final_response 写入位置 |

### 验收标准

- `final_response` 只有 1 个写入位置：`_h_final_response`
- 所有 bypass 路径的 `response_route` 被 trace 正确记录
- 回归测试全量通过

### 回滚方式

```bash
git checkout -- engine/workflows/deterministic_tool_workflow.py
git checkout -- engine/workflows/exploration_planning_workflow.py
git checkout -- engine/workflows/direct_response_workflow.py
git checkout -- engine/workflows/clarification_fallback_workflow.py
git checkout -- engine/subgraphs/response_subgraph.py
git checkout -- engine/_routes.py
```

---

## Phase I：多类型 DeterministicComposer

**目标**：从单一单店 composer 扩展到 6 类 composer。

### 新增文件

| 文件 | 职责 |
|---|---|
| `answer/composers/__init__.py` | composer 注册入口 |
| `answer/composers/single_shop_composer.py` | 8 facet 单店事实 composer |
| `answer/composers/recommendation_composer.py` | 推荐排序 composer |
| `answer/composers/comparison_composer.py` | 对比 trade-off composer |
| `answer/composers/exploration_composer.py` | 探索阶段 composer |
| `answer/composers/clarify_composer.py` | 澄清文案 composer |
| `answer/composers/fallback_composer.py` | 兜底 composer |

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `answer/generator.py` | `generate_answer()` 中增加 composer 路径选择 | LLM verbalizer 路径保留为默认 |
| `engine/subgraphs/response_subgraph.py:44-125` | 将 `_compose_single_shop_response` 委托给 `single_shop_composer` | 旧实现保留为 fallback |
| `engine/subgraphs/response_subgraph.py:422-491` | `_h_fallback_answer` 改为按 task_type 选择对应 composer | 旧逻辑保留 |

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_rule_based_verbalizer.py` | 6 类 composer 的输出格式正确 |
| `test_third_layer_fallback_policy.py` | fallback 策略按 answer_type 分发正确 |

### 验收标准

- 6 类 composer 各自输出不同于"抱歉"的有意义文案
- `_compose_single_shop_response` 扩展到 8 个 facet
- composer 路径的 latency ≤ LLM verbalizer 路径的 20%

### 回滚方式

```bash
git checkout -- answer/composers/
git checkout -- answer/generator.py engine/subgraphs/response_subgraph.py
```

---

## Phase J：统一 trace / eval / latency + 结构化预览

**目标**：
- 第三层 trace 从 1 个粗粒度 span 拆分为 8 个阶段级 span
- preview 层从纯文本过滤升级为结构化 `PreviewPolicyResult`

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `observability/trace.py` | 新增 `ResponseTraceSpan` 类型；`build_turn_trace()` 拆分 8 个 span |
| `engine/subgraphs/response_subgraph.py` | 每个阶段插入 `record_span()` 调用 |
| `streaming/preview_policy.py` | `can_emit_preview()` 返回 `PreviewPolicyResult` | 旧 `tuple[bool, str]` 保留为兼容方法 |
| `app.py:120-166` | `event_stream()` 消费新 `PreviewPolicyResult` | 旧过滤逻辑保留 |

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_preview_policy.py` | PreviewPolicyResult 字段完整，未验证 claim 被正确过滤 |
| 全量 35 个 test case（详细列表见 `11_third_layer_test_plan.md`） |

### 验收标准

- trace 能解释每个阶段的耗时和决策原因
- preview 层结构化输出已验证
- 所有新增测试在 CI 中运行通过
- benchmark 不超过当前基线 +20%
- 无 LLM 调用的单店场景 latency 不增长

### 回滚方式

```bash
git checkout -- observability/trace.py
git checkout -- engine/subgraphs/response_subgraph.py
git checkout -- streaming/preview_policy.py app.py
git checkout -- local_life_agent/tests/test_third_layer_*.py
```

---

## Phase K：ResponseContract 增强版 — 唯一权威出口

**目标**：将 `ResponseContract` 从 V1 最小版本升级为增强版，成为所有回答路径的唯一权威出口。

> ⚠️ **此 Phase 必须在 Phase H（workflow boundary 收敛）之后执行**——因为只有所有 workflow 不再直接写 `final_response` 后，ResponseContract 才能成为真正唯一的出口。

### 增强字段（V1 基础上增加）

```python
class ResponseContract(BaseModel):
    # V1 已有字段
    answer_text: str
    answer_type: str
    response_mode: ResponseMode
    trace_id: str | None
    verifier_result: VerifierResult | None
    fallback_reason: str | None
    uncertainty_notices: list[UncertaintyNotice] = []
    
    # Phase K 新增
    claims: list[AnswerClaim]               # 从 ClaimExtractor L3 输出
    citations: list[EvidenceCitation]       # claim → evidence 绑定
    cards: list[ClaimCard]                  # 面向 UI 的事实卡片
    confidence_band: ConfidenceBand | None   # 整体置信度
    response_policy: ResponsePolicy | None   # 表达策略记录
    clarification: str | None                # 结构化澄清文本
    safety_notice: str | None                # 安全拒答说明
```

### 修改文件

| 文件 | 修改内容 | 兼容策略 |
|---|---|---|
| `answer/response_contract.py` | `ResponseContractV1` → `ResponseContract` 升级为全字段版本 | V1 字段保留兼容 getter |
| `answer/final_response_builder.py` | `build_response_contract_v1()` → `build_response_contract()` 升级 | V1 方法保留为 deprecated 别名 |
| `engine/subgraphs/response_subgraph.py` | `_h_final_response()` 输出增强版 `ResponseContract`，作为 GraphState 最终字段 | `final_response` / `preview_text` 标记 deprecated，仍写但不再消费 |
| `app.py:194-226` | `event_stream()` 最终 payload 从 `ResponseContract` 派生 | 旧 `final_response` + `cards` 直接组装保留为兼容 fallback |

### 旧字段兼容策略

```text
Phase K 之后：
  ResponseContract（增强版）← 唯一权威出口
  final_response            ← 标记 deprecated，从 ResponseContract.answer_text 派生
  preview_text              ← 标记 deprecated，从 ResponseContract + PreviewPolicyResult 派生
  answer_source             ← 标记 deprecated，从 ResponseContract.verifier_result 派生
  所有 workflow 路径统一写 ResponseContract
```

### 新增测试

| 测试文件 | 测试点 |
|---|---|
| `test_third_layer_response_contract_enhanced.py` | 增强版字段完整、V1 到增强版向后兼容 |
| `test_third_layer_response_contract_authority.py` | 所有 8 个回答路径统一输出 ResponseContract |

### 验收标准

- `ResponseContract` 增强版包含 V1 全部字段 + 新增字段
- 所有 8 个 `final_response` 写入位置已缩减到 1 个（`_h_final_response`）
- V1 消费者兼容（V1 字段值不变）
- 回归测试全量通过

---

## 实施顺序依赖图

```
Phase A（事实冻结）
  └── Phase B（ResponseMode Enum）──────────────────────────┐
        └── Phase C（ResponseContract V1 最小版本）──────────┤
              └── Phase D（修 verify 空 evidence pass）──────┤
              └── Phase E（LLM disabled 有意义 fallback）───┤
                    └── Phase F（RewriteInstruction）────────┤
                          └── Phase G（ClaimExtractor L1）───┤
                                └── Phase H（Workflow 边界）─┤
                                      └── Phase I（Composer）┤
                                            └── Phase J（Trace/Eval）──┐
                                                  └── Phase K（ResponseContract 增强版）──┘
```

Phase D 和 Phase E 可并行。Phase F 依赖 D+E。Phase H（收敛 workflow bypass）必须在 K 之前完成。
Phase I（composer）在 H 之后启动，因为 composer 产出需要经过统一 final_response 出口。
Phase J（trace）只需要有最小 ResponseContract 就能接入。Phase K 需要在所有 builder/verifier/composer 稳定后将全线输出收敛到增强版 ResponseContract。

## 风险清单

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| `final_response` 减少写入位置导致间隙空回答 | 用户看不到回复 | Phase H 保留旧字段兼容写入 2 个迭代 |
| `ResponseMode` Enum 漏覆盖某个字符串路径 | 路由中断 | Phase B 保留旧字符串 fallback |
| `ClaimExtractor` 准确率不足 | verifier 误判 | Phase G 保留旧 verifier 作为双轨校验 |
| `DeterministicComposer` 延迟增加 | 单店回答变慢 | Phase I 要求 composer latency ≤ LLM 的 20% |
| 修改过多文件导致合并冲突 | 集成困难 | 按 Phase 分批提交，每 Phase 独立 PR |
