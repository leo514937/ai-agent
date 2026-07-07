# 第三层响应管线设计

本文件基于当前仓库真实代码，设计第三层从输入到最终输出的可信表达管线。

## 1. 当前真实入口

第三层当前入口仍然是：

```text
execution_review_subgraph -> response_subgraph
```

`response_subgraph` 负责：

- 读取 `response_mode`
- 分支处理 `direct / clarify / fallback / answer`
- 构造 `answer_plan`
- 调用生成器
- 调用 verifier
- rewrite / fallback
- 写 `final_response`

证据：

- `local_life_agent/engine/subgraphs/response_subgraph.py:128-173`
- `local_life_agent/engine/subgraphs/response_subgraph.py:181-357`

## 2. 目标管线

建议把第三层明确成下面这条管线：

```text
response_subgraph
  -> response_input_normalizer
  -> answer_contract_builder
  -> response_policy_resolver
  -> verbalizer_or_composer
  -> claim_extractor
  -> claim_verifier
  -> rewrite_or_fallback
  -> final_response_builder
  -> state_update_plan
```

### 2.1 `response_input_normalizer`

职责：

- 统一消费 `DecisionPlan`、`FinalDecisionPlan`、`EvidencePack`、`GlobalEvidencePack`、`ClarificationRequest`、`FallbackDirective`
- 把不同来源归一成统一输入结构
- 不引入新事实

### 2.2 `answer_contract_builder`

职责：

- 构建 `AnswerContract` / `AnswerPlan`
- 生成 `allowed_claims`
- 生成 `required_claims`
- 生成 `forbidden_claims`
- 生成 `unknowns`
- 生成 `evidence_refs`
- 生成 `response_sections`

当前实现参考：

- `local_life_agent/answer/answer_plan_builder.py:54-245`
- `local_life_agent/domain/decision.py:120-236`

### 2.3 `response_policy_resolver`

职责：

- 按 `answer_type` / `workflow_kind` / `task_complexity` 选择表达策略
- 决定回答长度
- 决定是否展示 trade-off
- 决定是否必须展示 unknown
- 决定最大推荐数量

### 2.4 `verbalizer_or_composer`

职责：

- 优先 LLM verbalizer
- LLM 不可用或简单事实场景走 deterministic composer
- 不直接做 claim 裁决

当前实现参考：

- `local_life_agent/answer/generator.py:605-700`
- `local_life_agent/answer/llm_verbalizer.py:231-558`

### 2.5 `claim_extractor`

职责：

- 从 `draft_response` 中抽取结构化 `AnswerClaim`
- 为 verifier 提供可对齐单元

### 2.6 `claim_verifier`

职责：

- 将 `AnswerClaim` 与 `EvidencePack` / `GlobalEvidencePack` 对齐
- 判断 `supported / unsupported / contradicted / unknown`
- 生成 `VerifierResult`

当前实现参考：

- `local_life_agent/answer/verifier.py:219-232`
- `local_life_agent/answer/verifier.py:625-664`
- `local_life_agent/answer/b2_mini_verifier.py:362-558`

### 2.7 `rewrite_or_fallback`

职责：

- 基于 `VerifierViolation` 生成 `RewriteInstruction`
- 必要时 deterministic fallback
- 不继续放大不确定 claim

### 2.8 `final_response_builder`

职责：

- 生成统一 `ResponseContract`
- 生成 `final_response`
- 生成 `preview_text`
- 生成 `verifier_result`
- 生成 `response_trace`

当前实现参考：

- `local_life_agent/answer/final_response_builder.py:6-17`
- `local_life_agent/engine/subgraphs/response_subgraph.py:345-357`

## 3. 约束边界

- 第三层不执行远程工具
- 第三层不做目标解析
- 第三层不构建 `EvidencePack`
- 第三层不做推荐排序
- 第三层不写 `SessionState`
- 第三层只负责把第二层已经确定的事实和决策安全表达出来

## 4. 目标输出

```text
ResponseContract
  - answer_text
  - answer_type
  - claims
  - citations
  - uncertainty_notices
  - confidence_band
  - cards
  - clarification
  - fallback_reason
  - safety_notice
  - trace_id
```

## 5. 当前代码偏差

- 现有主链路仍是 `response_subgraph`
- 现有 `generate_answer()` 仍是 LLM verbalizer 主导
- 现有 `build_final_response()` 不是主出口
- 现有 `preview_text` 只是流式预览，不是权威回答合同

## 6. 5 条 Pipeline 路径的入口/出口约束

### Entry Type Matrix

| Pipeline Path | 主入口来源 | 入口 GraphState 字段 | 生产者 |
|---|---|---|---|
| Direct Response | `raw_text` + `response_mode` | `response_mode="direct_response"` | `direct_response_workflow.py:156` |
| Clarify | `pending_clarification` | GraphState 字段 | `execution_review_subgraph` |
| Fallback | `fallback_reason` + `error_message` | GraphState 字段 | `clarification_fallback_workflow` |
| Normal Answer | `p2_decision_plan` + `evidence_pack` | `state["p2_decision_plan"]` + `state["evidence_pack"]` | `planning_subgraph` / `deterministic_tool_workflow` |
| Complex Answer | `p2_decision_plan` + `global_evidence_pack` + `exploration_stages` | `state["global_evidence_pack"]` | `exploration_planning_workflow` |

### Exit Type Matrix

| Pipeline Path | 主输出 | 输出 GraphState 字段 | 消费者 |
|---|---|---|---|
| Direct Response | 自然语言字符串 | `final_response` | `app.py:194-226` → 流式终点 |
| Clarify | 澄清文案 | `final_response` + `response_route="clarify_ready"` | `_routes.py:443-447` |
| Fallback | 保守兜底文案 | `final_response` + `response_route="fallback_ready"` | `_routes.py:443-447` |
| Normal Answer | 事实性自然语言 | `final_response` + `preview_text` | `app.py:120-166` 流式预览 |
| Complex Answer | 推荐/对比/探索文案 | `final_response` + `preview_text` | `app.py:120-166` 流式预览 |

### 出口约束差异

| 约束 | Direct | Clarify | Fallback | Normal | Complex |
|---|---|---|---|---|---|
| 必须被 `ResponseContract` 包装 | ✅ 目标 | ✅ 目标 | ✅ 目标 | ✅ 目标 | ✅ 目标 |
| verifier 必须校验 | ❌ 当前不校验 | ❌ 当前不校验 | ❌ 当前不校验 | ✅ 当前校验（但有空 draft pass 缺陷） | ⚠️ 仅 workflow 内校验 |
| 必须输出 `evidence_ref` | ❌ | ❌ | ❌ | ❌ 无此字段 | ❌ 无此字段 |
| 必须输出 `claim_ref` | ❌ | ❌ | ❌ | ❌ 无此字段 | ❌ 无此字段 |
| `preview_text` 必须等于 `final_response` 的过滤版本 | n/a | n/a | n/a | ⚠️ 当前通过 `_h_final_response` 复制 | ⚠️ 当前通过 `_h_final_response` 复制 |

