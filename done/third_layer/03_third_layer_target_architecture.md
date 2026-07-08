# 第三层目标架构

本文件参考业界回答层模式，但严格适配当前本地生活 Agent 的真实代码边界。

## 目标

第三层的目标不是“再生成一次答案”，而是把第二层输出的结构化决策与证据，稳定、可解释、可验证地表达给用户，并最终落到统一 `ResponseContract`。

核心要求：

- 不编造
- 不把不确定说成确定
- 不把连续性 metadata 当事实
- 对可验证事实给出明确表达
- 对不可验证部分显式标注不确定性
- 与 preview / final / trace 保持一致

## 推荐目标架构

```text
decision_plan / evidence_pack
  -> answer_plan_builder
  -> answer_renderer
  -> answer_verifier
  -> ResponseContract
  -> final_response / preview_text / response_trace
```

其中：

- `answer_plan_builder` 负责把决策和证据映射成回答结构
- `answer_renderer` 负责自然语言表达
- `answer_verifier` 负责事实一致性和 claim 合法性
- `ResponseContract` 负责最终对外输出合同

## 目标职责分层

### 1. `answer_plan_builder`

职责：

- 从 `DecisionPlan` / `EvidencePack` 中提取回答结构
- 生成 `answer_type`
- 生成 `response_sections`
- 生成 `allowed_claims`
- 生成 `required_disclaimers`
- 生成 `unknown_facets` / `failed_facets`

当前实现：

- `local_life_agent/answer/answer_plan_builder.py:54-245`
- `local_life_agent/domain/decision.py:120-236`

### 2. `answer_renderer`

职责：

- 将结构化 `AnswerPlan` 转成人类可读的自然语言
- 支持不同 answer_type：
  - `single_shop`
  - `recommendation`
  - `comparison`
  - `exploration_plan`
  - `clarification`
- 对单店事实做保守模板化兜底

当前实现：

- `local_life_agent/answer/generator.py:605-700`
- `local_life_agent/answer/llm_verbalizer.py:231-558`

### 3. `answer_verifier`

职责：

- 校验回答是否严格遵循 `AnswerPlan` 和 `EvidencePack`
- 区分 deterministic verify 与 LLM verify
- 提供 `passed / issues / suggested_fix / recoverable`

当前实现：

- `local_life_agent/answer/verifier.py:219-232`
- `local_life_agent/answer/verifier.py:625-664`
- `local_life_agent/answer/b2_mini_verifier.py:362-558`

### 4. `response_envelope`

职责：

- 统一对外响应合同
- 同时支持：
  - `answer_text`
  - `preview_text`
  - `cards`
  - `clarification`
  - `final_safety_status`
  - `trace_id`
- 不让 graph 内部字段直接裸露给前端

当前现状：

- `build_final_response()` 已存在，但不是主链路权威出口
- `app.event_stream()` 直接组装流式 final payload

证据：

- `local_life_agent/answer/final_response_builder.py:6-17`
- `local_life_agent/app.py:194-226`

## 推荐工作流

### A. 单店事实回答

```text
decision_plan / evidence_pack
  -> answer_plan_builder
  -> conservative renderer
  -> deterministic verifier
  -> final_response
```

特点：

- 尽量少依赖 LLM
- 先表达事实，再表达不确定性

### B. 推荐回答

```text
decision_plan / evidence_pack
  -> answer_plan_builder
  -> llm verbalizer
  -> verifier
  -> final_response
```

特点：

- 允许 LLM 做自然语言组织
- 排名和硬约束必须已由第二层完成

### C. 对比回答

```text
decision_plan / evidence_pack / comparison_matrix
  -> answer_plan_builder
  -> llm verbalizer or rule-based fallback
  -> verifier
  -> final_response
```

特点：

- 比较结论必须锚定 evidence
- 必须保留 trade-off

### D. 规划型回答

```text
exploration stages + evidence
  -> answer_plan_builder
  -> stage-aware renderer
  -> verifier
  -> final_response
```

特点：

- 阶段式表达
- 需要明确“不完整”的阶段

### E. 澄清 / fallback

```text
pending_clarification / failure state
  -> explicit clarification or trusted failure message
  -> final_response
```

特点：

- 不应硬凑自然语言结论

## 目标架构的关键原则

### 原则 1：答案结构先于答案文本

先定义回答合同，再生成自然语言。

### 原则 2：可信表达不等于 deterministic

规则化模板只能兜底，不能替代结构化可信表达。

### 原则 3：preview 不是 final

`preview_text` 只服务流式显示，不能代替最终 `response_envelope`。

### 原则 4：verification 不是补丁

验证器要参与表达链，不只是失败后再报错。

### 原则 5：会话连续性只做提示

`conversation_continuity` 只能作为 metadata，不可直接作为事实源。

## 当前与目标的偏差

- 当前主链路是 `response_subgraph`，不是独立 `answer_subgraph`
- 当前 `generate_answer()` 仍是 LLM verbalizer 主导
- 当前 `build_final_response()` 未成为主出口
- 当前缺少统一的 `ResponseContract`
- 当前缺少显式 `citation` / `confidence` / `uncertainty` 结构

## 缺失的 7 个模块设计

以下模块在"规范管线"中有定义但当前设计文档中没有完整设计。

### 模块 1：`response_input_normalizer`

**职责**：
- 统一消费 6 种输入源：`DecisionPlan`、`FinalDecisionPlan`、`EvidencePack`、`GlobalEvidencePack`、`ClarificationRequest`、`FallbackDirective`
- 把 `response_subgraph` 从直接消费散落 GraphState 字段改为通过规格化入口

**输入**：
| 来源 | GraphState 字段 | 当前消费位置 |
|---|---|---|
| `DecisionPlan` | `p2_decision_plan` | `response_subgraph.py:181-188` |
| `FinalDecisionPlan` | `final_decision_plan` | `response_subgraph.py:181-188`（通过 `decision_to_answer_plan`） |
| `EvidencePack` | `evidence_pack` | `verifier.py:625-664` 直接消费 |
| `GlobalEvidencePack` | `global_evidence_pack` | 多个 workflow 内部调用 |
| `ClarificationRequest` | `pending_clarification` + `resolve_shop_result` | `response_subgraph.py:375-419` |
| `FallbackDirective` | `fallback_reason` + `error_message` | `response_subgraph.py:422-491` |

**输出**：归一化的 `NormalizedResponseInput` DTO，包含：
- `answer_type`（从 `AnswerPlan.answer_type` 派生）
- `structured_claims`（从 `DecisionPlan.allowed_claims` 派生）
- `evidence_items`（从 `EvidencePack` 派生）
- `clarification_request`（如果有）
- `fallback_directive`（如果有）

**约束**：
- 不引入新事实
- 不执行工具
- 不做目标解析

### 模块 2：`response_policy_resolver`

**职责**：
- 按 `answer_type` / `workflow_kind` / `task_complexity` 选择表达策略
- 决定当前回答的：是否使用 LLM verbalizer、最大长度、是否展示 trade-off、是否必须展示 unknown、最大推荐数量

**策略矩阵**：

| answer_type | 允许 LLM | 允许 deterministic | 必须展示 unknown | 显示 trade-off | 最大推荐数 |
|---|---|---|---|---|---|
| `single_shop` | 否（优先 template） | 是 | 是 | n/a | n/a |
| `recommendation` | 是 | 否 | 是 | 否 | 5 |
| `comparison` | 是 | 是（作为 fallback） | 是 | 是 | n/a |
| `exploration_plan` | 是 | 否 | 是 | n/a | n/a |
| `clarify` | 否 | 是 | n/a | n/a | n/a |
| `fallback` | 否 | 是 | n/a | n/a | n/a |

**输出**：`ResponsePolicy`（包含 `max_length`、`max_recommendations`、`must_show_unknown`、`show_tradeoff`、`allow_llm_verbalizer`、`allow_deterministic_composer`）

**当前零覆盖区域**：当前没有任何 `ResponsePolicy` 对象。`_needs_llm_verification()`（`verifier.py:219-232`）的硬编码判断是这个模块的前身，但不是策略化的。

### 模块 3：`claim_extractor`

> ⚠️ **难度说明**：本地生活中文回答混有多种 claim 类型——事实 claim（"有 3 张优惠券"）、偏好 claim（"更适合约会"）、排序 claim（"A 比 B 好"）、unknown notice（"券的信息我没查到"）、trade-off claim（"A 评分高但 B 距离近"）。不能靠简单正则一次覆盖。因此分三级落地：

| 级别 | 策略 | 覆盖范围 | 前置依赖 |
|---|---|---|---|
| **Level 1** | 从 `AnswerPlan` / `DecisionPlan` 的 `allowed_claims` / `required_claims` 直接生成 `expected claims` | 单店事实 claim（coupon/open_status/distance/rating/price） | RewriteInstruction |
| **Level 2** | 从 deterministic composer 输出的文本中回填 claim span（位置标注） | 单店 + 推荐排序 claim | 多类型 composer |
| **Level 3** | 对 LLM verbalizer 输出使用 LLM structured extraction，再由 deterministic verifier 对齐 EvidencePack | 全部类型（comparison/exploration/LLM generated） | ResponseContract 增强版 |

**职责**：
- 从 `draft_response` 中抽取结构化 `AnswerClaim`
- 为 verifier 提供可对齐单元

**支持抽取的回答类型**：
- 单店事实：coupon / open_status / distance / rating / avg_price / review_summary
- 推荐：排序 claim（"A 比 B 更适合"）
- 对比：trade-off claim（"A 的评分更高，B 的距离更近"）
- 探索：阶段 claim（"第一阶段：...，第二阶段：..."）

**输出**：`List[AnswerClaim]`，每项包含 `claim_id`、`facet`、`value`、`evidence_ids`、`confidence`、`allow_verbalization`、`must_mention`

**当前零覆盖区域**：当前 verifier 没有任何 `ClaimExtractor` 模块。当前 `verifier.py:243-346` 的 `_facet_rules` 只能检测关键词存在性，不能抽取结构化 claim。

### 模块 4：`claim_verifier`

**职责**：
- 将 `AnswerClaim` 列表与 `EvidencePack` / `GlobalEvidencePack` 对齐
- 逐条判断：`supported`、`unsupported`、`contradicted`、`unknown`

**对齐类型**：

| claim 类型 | 证据来源 | 对齐方式 |
|---|---|---|
| coupon | `ToolResult(coupon_list)` | 对比 claim 中的券类型/数量与证据中券列表 |
| open_status | `ToolResult(business_status)` | 对比 claim 中的营业状态字符串与证据 |
| distance | `ToolResult(distance)` | 对比 claim 中的距离数值与证据 |
| rating | `ToolResult(rating)` | 对比 claim 中的评分数值与证据 |
| price | `ToolResult(avg_price)` | 对比 claim 中的人均价格与证据 |
| comparison | `ComparisonMatrix` | 对比 claim 中的比较结论与 matrix |

**输出**：`VerifierResult`：
- `passed: bool`
- `issues: list[VerifierViolation]`（每条含 `code`、`message`、`claim_id`、`severity`、`recoverable`）
- `verifier_mode: Literal["deterministic", "llm"]`

**当前零覆盖区域**：当前没有任何按 claim 粒度的对齐逻辑。`verifier.py:625-664` 的 `verify_answer()` 返回整体结果。

### 模块 5：`rewrite_or_fallback`

**职责**：
- 基于 `VerifierViolation` 列表生成结构化 `RewriteInstruction`
- 能重写时优先局部修复
- 不能重写时降级为 deterministic fallback / clarify / trusted failure

**决策矩阵**：

| 条件 | 动作 |
|---|---|
| 仅 `unsupported_claims` 且 < 3 个 | 生成 `RewriteInstruction` 移除/修正这些 claim |
| 含 `contradicted_claims` | 生成 `RewriteInstruction` 修正为 `unknown` |
| `passed` 且无 violation | 直接输出 |
| violation 过多或不可 recover | 降级为 `deterministic_fallback` |
| 已达 rewrite 上限 | 降级为 `clarify`（告知用户无法确认）或 `fail`（信任失败） |

**`RewriteInstruction` 字段**：
- `instruction_id: str`
- `target_claim_ids: list[str]`（需修改的 claim）
- `remove_claim_ids: list[str]`（需删除的 claim）
- `strengthen_claim_ids: list[str]`（需加强证据引用的 claim）
- `add_uncertainty_notices: list[str]`（需补充的不确定说明）
- `preserve_tradeoff: bool`
- `fallback_mode: Literal["rewrite", "deterministic_fallback", "clarify", "fail"]`

**当前零覆盖区域**：当前 `_h_rewrite`（`response_subgraph.py:339-342`）只递增计数器，没有任何指令生成逻辑。

### 模块 6：`final_response_builder`（升级版）

**当前状态**：
- `final_response_builder.py:6-17`：仅返回 `answer_text`、`trace_id`、`session_id`、`clarification`、`cards`

**升级目标**：
- 接收 `AnswerPlan` + `final_response` 文本 + `VerifierResult` + `EvidenceRefs` + `ResponsePolicy`
- 输出 `ResponseContract`（包含 `answer_text`、`answer_type`、`claims`、`citations`、`uncertainty_notices`、`confidence_band`、`cards`、`clarification`、`fallback_reason`、`safety_notice`、`trace_id`、`verifier_result`）

**约束**：
- `ResponseContract` 成为唯一权威出口
- 旧字段（`final_response`、`preview_text`、`answer_source`）保留为兼容层

### 模块 7：`state_update_plan`（响应式状态更新）

**职责**：
- 第三层只通过 `StateUpdatePlan` 间接影响 `SessionState`
- 不在第三层内直接写 `SessionState`

**写 `SessionState` 的当前实际位置**（需要清理）：
| 文件 | 行号 | 写入内容 | 风险 |
|---|---|---|---|
| `deterministic_tool_workflow.py:293-596` | 目标解析中读/写 session_state | 绕过 |
| `exploration_planning_workflow.py:1046` | `apply_state_update_plan` | 潜在绕过 |

**目标**：
- `StateUpdatePlan` 只包含：`updated_focus`、`clarification_history`、`failed_intents`、`fallback_noted`
- `response_subgraph` 只消费，不直接写入

## 5 条约束边界（第三层不该做的）

### 约束 1：第三层不执行远程工具

**代码证据**：
- `response_subgraph.py:1-516`：没有任何工具调用代码
- 所有工具调用在第二层（workflow）完成

### 约束 2：第三层不做目标解析

**代码证据**：
- `response_subgraph.py:181-188`：`_h_answer_plan_build` 消费 `p2_decision_plan`，但不生成
- `deterministic_tool_workflow.py:293-596`：目标解析在 workflow 内完成，不在 response_subgraph 内

### 约束 3：第三层不构建 `EvidencePack`

**代码证据**：
- `response_subgraph.py:290-298`：`_h_answer_verify` 消费 `evidence_pack`，但不构建
- `evidence_builder.py`：证据构建在第二层

### 约束 4：第三层不做推荐排序

**代码证据**：
- `comparison_matrix` 和 `ranking_snapshot_id` 在 `AnswerPlan` 中（`schemas.py:1304-1354`），但由第二层构建
- `response_subgraph` 不调用排序逻辑

### 约束 5：第三层不直接写 `SessionState`

**代码证据**：
- `response_subgraph.py` 中 `_h_answer_generate()` 调用 `_build_conversation_continuity(state)`（第 203 行），后者（`_compat.py:586-632`）只读取 `SessionState`，不写入
- `deterministic_tool_workflow.py:293-596` 和 `exploration_planning_workflow.py:1046` 的写入行为属于违反约束的已知异常

## 5 条 pipeline 路径的输入→处理→输出→约束

### 路径 1：Direct Response（闲聊/拒答/能力说明）

**输入**：
- `raw_text`（用户输入）
- `response_mode = "direct_response"`（由`direct_response_workflow.py:156` 写入）

**当前处理**：
- `direct_response_workflow.py:63-85`：`_classify_direct_response` 做关键词分类（forbidden/capability/chat）
- `direct_response_workflow.py:156-159`：分类后直接写 `final_response`
- `response_subgraph.py:133`：pass-through（继续走 `_h_final_response`）

**输出**：`final_response`（字符串）

**约束**：
- 不执行远程工具
- 不构建 EvidencePack
- 不进入 verifier
- `final_response` 应被统一 `ResponseContract` 包装

### 路径 2：Clarify（缺信息/歧义）

**输入**：
- `pending_clarification`
- `resolve_shop_result`
- `error_message`
- `response_mode = "clarify"`（由 `clarification_fallback_workflow.py:230` 写入）

**当前处理**：
- `clarification_fallback_workflow.py:233`：直接写 `final_response`（不经过 `response_subgraph` 生成链路）
- `response_subgraph.py:137-142`：当 `final_response` 为空时才调用 `_h_clarify_response`

**输出**：`final_response`（字符串）

**约束**：
- 不做复杂表达生成
- 应输出结构化 clarify 请求（`reason` + `action_needed` + `retryable`）
- 应被统一 `ResponseContract` 包装

### 路径 3：Fallback（工具失败/兜底）

**输入**：
- `fallback_reason`
- `error_message`
- `response_mode = "fallback"`

**当前处理**：
- `response_subgraph.py:422-491`：`_h_fallback_answer` 按 task_type 分四类：
  - 单店营业状态（第 450-467 行）
  - 单店优惠券（第 468-472 行）
  - 工具失败/熔断/unknown/unsupported（第 473-485 行）
  - 其他：通用"抱歉"（第 423 行）

**输出**：`final_response`（字符串）

**约束**：
- 不应硬凑自然语言结论
- 推荐/对比/探索的 fallback 必须各自有保守模板（不能退化为通用"抱歉"）
- 应输出 `fallback_reason` + `retryable` 结构

### 路径 4：Normal Answer（单店事实）

**输入**：
- `p2_decision_plan`
- `evidence_pack`
- `response_mode = "direct"`（`deterministic_tool_workflow.py:906`）或 `"answer"`

**当前处理**（`response_subgraph.py:154-357`）：
```
_p2_decision_plan + evidence_pack
  → _h_answer_plan_build（第 181-188 行）
  → _h_answer_generate（第 191-265 行）
  → _h_answer_verify（第 290-298 行）
  → rewrite loop（第 154-173 行）
  → _h_final_response（第 345-357 行）
```

**输出**：`draft_response` → `final_response` + `preview_text`

**约束**：
- 尽量少依赖 LLM verbalizer
- 先表达事实，再表达不确定性
- 确定性渲染优先（`_compose_single_shop_response`）

### 路径 5：Complex Answer（推荐/对比/探索）

**输入**：
- `p2_decision_plan`（含 `comparison_matrix_id` / `ranking_snapshot_id` / `exploration_stages`）
- `evidence_pack` / `global_evidence_pack`
- `response_mode = "exploration_plan"` 或 `"answer"` 或无

**当前处理**：
- 与 Path 4 共享 `response_subgraph.py:154-357` 主链路
- `exploration_planning_workflow.py:716-837` 内部自有 `_compose_final_response`（第 716-792 行）+ `_build_success_patch`（第 795-837 行）
- `_rule_based_verbalize()`（`llm_verbalizer.py:231-349`）对 recommendation / comparison / exploration_plan 有保守模板

**输出**：`final_response`（字符串）

**约束**：
- 必须先有 `AnswerPlan`（含 `comparison_matrix` / `ranking_policy` / `exploration_stages`）
- 只表达已允许 claims
- 推荐/对比必须保留 trade-off 和 uncertainty
- 探索必须阶段化表达，明确已完成和未完成

## 当前代码偏差状态

| 要求 | 当前状态 | 证据 |
|---|---|---|
| 独立 `ResponseContract` | ❌ 缺失 | 无此类定义 |
| `ResponseMode` 统一 Enum | ❌ 缺失 | 7+ 个字符串值 |
| `ClaimExtractor` | ❌ 缺失 | `verifier.py` 纯关键词规则 |
| `ClaimVerifier`（claim 级） | ❌ 缺失 | 无 claim 级对齐 |
| `RewriteInstruction` | ❌ 缺失 | `response_subgraph.py:339-342` 只递增计数 |
| `ResponsePolicy` | ❌ 缺失 | `verifier.py:219-232` 硬编码 |
| 6 类 DeterministicComposer | ❌ 缺失 | 只有 `_compose_single_shop_response` |
| unified trace span | ❌ 缺失 | `trace.py:80-198` 无阶段级 span |
| 14 种本地生活 claim 类型 | ❌ 缺失 | `verifier.py:243-346` 只覆盖 5 个 filter |
| `StateUpdatePlan` 统一出口 | ⚠️ 部分存在 | `_routes.py:443-447` 有 mapping |
