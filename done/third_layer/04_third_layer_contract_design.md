# 第三层契约设计

本文件设计第三层的核心契约对象，并说明它们属于 GraphState、Domain DTO、Trace 还是 Response DTO。

## 1. 契约总览

| 契约 | 类型建议 | 归属建议 | 说明 |
|---|---|---|---|
| `ResponseMode` | Domain DTO | `GraphState` 中间态 | 统一第三层模式枚举，不再散落字符串 |
| `ResponseContract` | Response DTO | 第三层对外输出 | 第三层权威输出合同 |
| `AnswerPlan` | Domain DTO | `GraphState` 中间态 | 现有回答结构计划，继续作为输入 |
| `DecisionPlan` | Domain DTO | 第二层输出 / 第三层输入 | 已有决策计划 |
| `FinalDecisionPlan` | Domain DTO | 第二层输出 / 第三层输入 | 复杂场景最终决策 |
| `GlobalEvidencePack` | Domain DTO | 第二层输出 / 第三层输入 | 多 workflow 合并证据 |
| `VerifierResult` | Domain DTO | `GraphState` 中间态 | 验证结果与失败原因 |
| `RewriteInstruction` | Domain DTO | `GraphState` 中间态 | 结构化重写指令 |
| `ClaimExtractorResult` | Domain DTO | `GraphState` 中间态 | claim 抽取结果 |
| `AnswerClaim` | Domain DTO | `ResponseContract` 输入 | 可验证最小回答单元 |
| `EvidenceCitation` | Domain DTO | `ResponseContract` 输入 | claim 证据引用 |
| `SourceSpan` | Domain DTO | `ResponseContract` 输入 | 来源片段位置 |
| `ConfidenceBand` | Domain DTO | `ResponseContract` 输入 | 置信度表达 |
| `UncertaintyNotice` | Domain DTO | `ResponseContract` 输入 | 不确定性提示 |
| `ResponsePolicy` | Domain DTO | `GraphState` 中间态 / 策略层 | 控制长度、风格、unknown、trade-off |
| `ResponseTrace` | Trace | 运行时 trace | 记录回答生成到最终输出全过程 |

## 2. `ResponseMode`

### 目标

统一第三层模式，不再依赖散落字符串。

### 建议枚举

```python
ResponseMode:
    "direct"
    "reject"
    "clarify"
    "fallback"
    "answer"
    "tool_answer"
    "comparison"
    "exploration_plan"
```

### 当前现状

- 当前实现主要使用字符串
- `response_subgraph`、`response_route`、`workflow_runner`、`TurnTrace` 都在消费这些字符串

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:128-173`
- `local_life_agent/observability/trace.py:386-573`

## 3. `ResponseContract`

### 目标

第三层权威输出合同。

### ⚠️ 拆分原则：V1（最小版本）→ 增强版

一次性引入全部 12+ 字段会让改造面过大。因此拆为两阶段：

| 版本 | 阶段 | 字段数 | 用途 |
|---|---|---|---|
| `ResponseContractV1` | Phase C | 7 个 | 所有出口路径统一输出基础字段 |
| `ResponseContract`（增强版） | Phase K | 13 个 | V1 + claims/citations/cards/confidence_band/response_policy |

### V1 最小字段集（Phase C 引入）

```python
ResponseContractV1:
    answer_text: str                        # 回答文本（必填）
    answer_type: str                        # 回答类型（必填）
    response_mode: ResponseMode              # 回答模式枚举（必填）
    trace_id: str | None                     # 追踪 ID
    verifier_result: VerifierResult | None   # 校验结果
    fallback_reason: str | None              # 兜底原因
    uncertainty_notices: list[UncertaintyNotice] = []  # 不确定性说明
```

### 增强版字段（Phase K 在 V1 基础上增加）

```python
# V1 已有字段（全部保留）
# Phase K 新增：
    claims: list[AnswerClaim]               # 结构化 claims（ClaimExtractor L3 输出）
    citations: list[EvidenceCitation]       # claim → evidence 绑定
    cards: list[ClaimCard]                  # 面向 UI 的事实卡片
    confidence_band: ConfidenceBand | None   # 整体置信度
    response_policy: ResponsePolicy | None   # 表达策略记录
    clarification: str | None                # 结构化澄清文本
    safety_notice: str | None                # 安全拒答说明
```

### 迁移路径

```text
Phase C（V1）：
  → 所有回答路径输出 ResponseContractV1
  → 旧字段 final_response / preview_text 保留为兼容层
  → V1 仅用于 trace 和基础一致性验证

Phase K（增强版）：
  → V1 升级为增强版，成为唯一权威出口
  → final_response 标记 deprecated，从 answer_text 派生
  → 所有路径统一写 ResponseContract
```

### 归属

- `Response DTO`

## 4. `VerifierResult`

### 目标

统一第三层验证结果。

建议字段：

```python
VerifierResult:
    passed: bool
    issues: list[str]
    recoverable: bool
    verifier_mode: Literal["deterministic", "llm"]
    suggested_fix: str | None
    unsupported_claims: list[str]
    unknown_claims: list[str]
    contradicted_claims: list[str]
```

### 归属

- `Domain DTO`
- `GraphState` 中间态

## 5. `RewriteInstruction`

### 目标

重写不只是计数递增，而是结构化修复指令。

建议字段：

```python
RewriteInstruction:
    instruction_id: str
    target_claim_ids: list[str]
    remove_claim_ids: list[str]
    strengthen_claim_ids: list[str]
    add_uncertainty_notices: list[str]
    preserve_tradeoff: bool
    fallback_mode: Literal["rewrite", "deterministic_fallback", "clarify", "fail"]
```

### 归属

- `Domain DTO`
- `GraphState` 中间态

## 6. `ResponsePolicy`

### 目标

控制不同回答类型的表达策略。

建议字段：

- `max_length`
- `max_recommendations`
- `must_show_unknown`
- `show_tradeoff`
- `style`
- `tone`
- `allow_llm_verbalizer`
- `allow_deterministic_composer`

### 归属

- `Domain DTO`
- 策略层

## 7. 对当前实现的映射建议

### GraphState

- `response_mode`
- `answer_plan`
- `draft_response`
- `final_response`
- `preview_text`
- `verifier_result`
- `rewrite_instruction`
- `response_policy`
- `response_trace`

### Domain DTO

- `ResponseMode`
- `ResponseContract`
- `VerifierResult`
- `RewriteInstruction`
- `ResponsePolicy`
- `AnswerClaim`
- `EvidenceCitation`
- `SourceSpan`
- `ConfidenceBand`
- `UncertaintyNotice`

### Trace

- `ResponseTrace`

### Response DTO

- `ResponseContract`

## 8. 兼容字段原则

以下字段可继续保留过渡期兼容，但不应作为唯一权威：

- `final_response`
- `draft_response`
- `preview_text`
- `answer_source`
- `template_degraded`
- `fallback_used`
- `template_fallback_used`
- `rewrite_count`
- `answer_verify_passed`
- `answer_verify_violations`
- `verifier_result`
- `verifier_failure_code`
- `verifier_unknown_fields`
- `verifier_unsupported_claims`
- `verifier_false_fields`

## 9. 补充：13 个缺失 DTO 设计

以下 DTO 在"规范管线"中有定义但当前文档中没有覆盖。

### DTO-1：`AnswerClaim`

**用途**：最小可验证回答单元。verifier 从最终文本中抽取的结构化 claim。

**建议字段**：
```python
AnswerClaim:
    claim_id: str                    # 唯一标识，如 "open_status_shop123_0"
    facet: str                       # 领域 facet 名（如 coupon/open_status/distance/rating）
    value: str | dict                # 结构化值
    evidence_ids: list[str]          # 绑定的证据 ID 列表
    confidence: float                # 置信度 [0.0, 1.0]
    allow_verbalization: bool        # 是否允许 verbalizer 自由表达
    must_mention: bool               # 是否必须在回答中提及
```

**归属**：Domain DTO | `ResponseContract` 输入

**代码证据**：
- `schemas.py:1304-1354`：`AnswerPlan` 有 `allowed_claims: list[str]`，但无结构化 `AnswerClaim`
- `answer_plan_builder.py:54-245`：构建 `allowed_claims` 时只做字符串列表

### DTO-2：`EvidenceCitation`

**用途**：将 claim 与证据绑定，回答可追溯。

**建议字段**：
```python
EvidenceCitation:
    citation_id: str                 # 唯一引用 ID
    claim_id: str                    # 对应的 claim ID
    source_id: str                   # 证据源 ID（如 ToolResult ID）
    source_type: str                 # 证据源类型（"tool_result" / "comparison_matrix" / "ranking_policy"）
    source_span: SourceSpan | None   # 来源片段位置
    excerpt: str | None              # 证据摘要
    freshness: str | None            # 证据新鲜度
```

**归属**：Domain DTO | `ResponseContract` 的一部分

**代码证据**：
- `app.py:194-226`：final payload 有 `cards: list[dict]`，但无结构化 citation

### DTO-3：`SourceSpan`

**用途**：表示一段文本/日志在原始来源中的位置。

**建议字段**：
```python
SourceSpan:
    source_name: str                 # 来源名称
    offset_start: int | None         # 起始偏移
    offset_end: int | None           # 结束偏移
    line_start: int | None           # 起始行号
    line_end: int | None             # 结束行号
```

**归属**：Domain DTO | `EvidenceCitation` 的一部分

**代码证据**：
- 当前无此结构。`trace.py:80-198` 的 `Span` 没有 `source_span` 字段。

### DTO-4：`ConfidenceBand`

**用途**：回答整体置信度表达。

**建议字段**：
```python
ConfidenceBand:
    label: Literal["high", "medium", "low", "unknown"]  # 置信度标签
    score: float                     # 置信度分数 [0.0, 1.0]
    reason: str                      # 原因说明
```

**归属**：Domain DTO | `ResponseContract` 的一部分

**代码证据**：
- `schemas.py:1304-1354`：`AnswerPlan` 有 `unknown_facets` / `failed_facets` / `must_mention_unknowns`，但无整体置信度

### DTO-5：`UncertaintyNotice`

**用途**：显式的不确定性说明，不被模糊语气替代。

**建议字段**：
```python
UncertaintyNotice:
    facet: str                       # 哪个 facet 不确定
    reason: str                      # 不确定原因
    severity: Literal["info", "warning", "error"]  # 严重程度
```

**归属**：Domain DTO | `ResponseContract` 的一部分

**代码证据**：
- `llm_verbalizer.py:231-349`：`_rule_based_verbalize()` 在缺失 facet 时输出保守文案，但无结构化 `UncertaintyNotice`
- `schemas.py:1304-1354`：`AnswerPlan` 有 `required_disclaimers: list[str]`，接近但无结构化

### DTO-6：`ClarificationRequest`

**用途**：结构化澄清请求。

**建议字段**：
```python
ClarificationRequest:
    reason: str                      # 为什么需要澄清
    missing_info: list[str]          # 缺少的信息
    suggested_actions: list[str]     # 用户可执行的操作
    retryable: bool                  # 用户补充信息后是否可重试
```

**归属**：Domain DTO | `GraphState` 中间态 | `ResponseContract` 中可选

**代码证据**：
- `response_subgraph.py:375-419`（`_h_clarify_response`）：当前输出纯文本文案
- `schemas.py` 中 `PendingClarification` 接近但不等同

### DTO-7：`FallbackDirective`

**用途**：结构化 fallback 指令。

**建议字段**：
```python
FallbackDirective:
    reason: str                      # fallback 原因
    fallback_type: Literal["single_shop", "recommendation", "comparison", "exploration", "general"]
    action_needed: str | None        # 下一步建议
    retryable: bool                  # 是否可重试
```

**归属**：Domain DTO | `GraphState` 中间态

**代码证据**：
- `response_subgraph.py:422-491`（`_h_fallback_answer`）：当前按 task_type 分支但无结构化指令

### DTO-8：`NormalizedResponseInput`

**用途**：第三层统一输入合同。将所有散落输入源归一。

**建议字段**：
```python
NormalizedResponseInput:
    answer_type: str                 # 从 AnswerPlan 派生
    structured_claims: list[AnswerClaim]  # 从 DecisionPlan.allowed_claims 派生
    evidence_items: list              # 从 EvidencePack 派生
    clarification_request: ClarificationRequest | None
    fallback_directive: FallbackDirective | None
```

**归属**：Domain DTO | `GraphState` 入口中间态

**代码证据**：
- 当前无此结构。`response_subgraph.py:181-357` 直接从 GraphState 散落字段消费

### DTO-9：`ResponseTraceSpan`

**用途**：阶段级 trace span，用于拆解回答生成全流程耗时。

**建议字段**：
```python
ResponseTraceSpan:
    span_id: str                     # span ID
    stage: str                       # 阶段名称
    start_time: float                # 开始时间戳
    end_time: float                  # 结束时间戳
    duration_ms: float               # 耗时（毫秒）
    decision: str                    # 关键决策
    reason: str                      # 决策原因
    llm_calls: int                   # LLM 调用次数
    degraded: bool                   # 是否降级
    error: str | None                # 异常信息
```

**归属**：Trace | `TurnTrace` 的一部分

**代码证据**：
- `trace.py:80-198`：`TurnTrace` 类当前无阶段级 span

### DTO-10：`VerifierViolation`

**用途**：细粒度校验违规，每条对应一个具体问题。

**建议字段**：
```python
VerifierViolation:
    code: str                        # 违规编码（如 "UNSUPPORTED_CLAIM"）
    message: str                     # 描述
    claim_id: str | None             # 对应的 claim ID
    severity: Literal["info", "warning", "error"]
    recoverable: bool                # 是否可修复
```

**归属**：Domain DTO | `VerifierResult` 的一部分

**代码证据**：
- `verifier.py:625-664`：当前返回 `issues: list[str]`——纯字符串列表

### DTO-11：`PreviewPolicyResult`

**用途**：预览层结构化结果。

**建议字段**：
```python
PreviewPolicyResult:
    allowed: bool                    # 是否允许展示
    verified: bool                   # 是否已验证
    reason: str                      # 决策原因
```

**归属**：Domain DTO | `GraphState` 中间态

**代码证据**：
- `preview_policy.py:29-43`：`can_emit_preview(text, verified=False)` 返回 `tuple[bool, str]`

### DTO-12：`DeterministicComposerDirective`

**用途**：指示 deterministic composer 如何渲染。

**建议字段**：
```python
DeterministicComposerDirective:
    answer_type: str                 # 回答类型
    shop_ids: list[str]              # 目标店 ID
    facets: list[str]                # 需要渲染的 facet
    compose_mode: Literal["coupon", "open_status", "distance", "rating", "price", "comparison", "recommendation", "exploration"]
```

**归属**：Domain DTO | `response_subgraph` 内部

**代码证据**：
- `response_subgraph.py:44-125`：`_compose_single_shop_response()` 当前只处理 coupon / open_status / distance

### DTO-13：`ClaimCard`

**用途**：面向 UI 的事实卡片。

**建议字段**：
```python
ClaimCard:
    card_id: str                     # 卡片 ID
    shop_name: str                   # 店铺名
    facet: str                       # facet 名称
    value: str                       # facet 值
    evidence_summary: str | None     # 证据摘要
    uncertainty_note: str | None     # 不确定性说明
```

**归属**：Domain DTO | `ResponseContract` 的 `cards` 字段

**代码证据**：
- `app.py:194-226`：`cards: list[dict]` 当前无结构化 schema

## 10. DTO 分配矩阵

| DTO | 类型类别 | 写入者 | 消费者 |
|---|---|---|---|
| `ResponseMode` | Domain DTO Enum | workflow | `response_subgraph` |
| `ResponseContract` | Response DTO | `_h_final_response` | API / streaming 终点 |
| `AnswerPlan` | Domain DTO | `_h_answer_plan_build` | renderer / verifier |
| `VerifierResult` | Domain DTO | `_h_answer_verify` | rewrite / trace |
| `RewriteInstruction` | Domain DTO | rewrite 节点 | generator / composer |
| `ResponsePolicy` | Domain DTO | `response_policy_resolver` | renderer / composer |
| `AnswerClaim` | Domain DTO | claim extractor | verifier / ResponseContract |
| `EvidenceCitation` | Domain DTO | ResponseContract 构建者 | frontend |
| `SourceSpan` | Domain DTO | EvidenceCitation | trace |
| `ConfidenceBand` | Domain DTO | ResponseContract 构建者 | frontend |
| `UncertaintyNotice` | Domain DTO | ResponseContract 构建者 | frontend |
| `ClarificationRequest` | Domain DTO | `_h_clarify_response` | ResponseContract |
| `FallbackDirective` | Domain DTO | `_h_fallback_answer` | ResponseContract |
| `NormalizedResponseInput` | Domain DTO | `response_input_normalizer` | `response_subgraph` |
| `ResponseTraceSpan` | Trace | 各阶段节点 | `TurnTrace` |
| `VerifierViolation` | Domain DTO | verifier | VerifierResult |
| `PreviewPolicyResult` | Domain DTO | `sanitize_preview_text` | streaming |
| `DeterministicComposerDirective` | Domain DTO | `response_policy_resolver` | composer |
| `ClaimCard` | Domain DTO | ResponseContract 构建者 | frontend UI |

