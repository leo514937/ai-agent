# 第三层：回答层 — 架构报告（更新版）

> 当前范围：`engine/subgraphs/response_subgraph.py`、`answer/`、`domain/enums.py`、`engine/workflows/*`、`engine/workflow_runner.py` 的回答出口部分
>
> 目标：把“回答生成、忠实性校验、重写、降级、最终出口”收敛到统一 response contract。

---

## 1. 第三层职责边界

第三层负责把第二层产出的 `DecisionPlan` / `EvidencePack` 变成用户可读回答，并保证回答不越证据边界。

**负责**
- `ResponseMode` 归一化
- `ResponseDirective` 统一出口对象
- `ResponseContractV2` 当前权威合同
- LLM verbalizer 生成回答
- verifier 校验与重写
- deterministic composer 降级
- 直接回答 / 澄清 / 兜底 / 探索计划出口

**不负责**
- 目标规划
- 工具调用
- 会话存储
- 输入理解与引用解析

---

## 2. 第三层数据流

```text
DecisionPlan / EvidencePack
  → response_subgraph
      → response_mode normalize
      → direct / clarify / fallback / answer 分支
      → answer_plan_builder
      → generator / llm_verbalizer
      → verifier
      → rewrite_instruction（必要时）
      → deterministic composers（必要时）
      → ResponseDirective
      → ResponseContractV2
      → state_update_plan
```

---

## 3. ResponseMode 与响应分支

文件：[`domain/enums.py`](../local_life_agent/domain/enums.py)

当前枚举：
- `DIRECT`
- `DIRECT_RESPONSE`
- `REJECT`
- `CLARIFY`
- `FALLBACK`
- `ANSWER`
- `TOOL_ANSWER`
- `COMPARISON`
- `EXPLORATION_PLAN`

`response_subgraph` 会先 normalize，再决定走哪条路径。

---

## 4. 统一出口：`ResponseDirective` / `ResponseContractV2`

### `ResponseDirective`

它是最小回答出口对象，负责承载：
- `answer_text`
- `answer_type`
- `response_mode`
- `fallback_reason`
- `trace_id`

### `ResponseContractV2`

它是当前更完整的权威合同，承载：
- `claims`
- `citations`
- `cards`
- `confidence_band`
- `response_policy`
- `clarification`
- `safety_notice`
- `trace_summary`

第三层的原则是：
- 业务回答从 directive/contract 派生
- 不再让多个节点各自直写最终文本
- `final_response` 是派生字段，不是多头写入点

---

## 5. 回答生成流水线

文件：[`answer/generator.py`](../local_life_agent/answer/generator.py)
文件：[`answer/llm_verbalizer.py`](../local_life_agent/answer/llm_verbalizer.py)

主路径：
1. `answer_plan_builder`
2. `generate_answer`
3. `verbalize_decision_plan`
4. `verify_answer`
5. `rewrite_instruction`
6. 重新 verbalize 或退回 deterministic composer

常见降级：
- LLM 禁用 / 超时 / 空输出
- verifier 判定不忠实
- 复杂回答超过重写次数上限

---

## 6. Deterministic composers

文件：[`answer/composers/deterministic.py`](../local_life_agent/answer/composers/deterministic.py)

现有 composer 覆盖：
- `DirectResponseComposer`
- `ClarificationComposer`
- `SystemFallbackComposer`
- `SingleShopFactComposer`
- `RecommendationComposer`
- `ComparisonComposer`
- `ExplorationPlanComposer`

它们的作用是：
- 在 LLM 不可用或不可信时产出稳定可读文本
- 保持语义一致，不靠占位符字符串

---

## 7. Verifier / RewriteInstruction

文件：[`answer/verifier.py`](../local_life_agent/answer/verifier.py)
文件：[`answer/rewrite_instruction.py`](../local_life_agent/answer/rewrite_instruction.py)

当前方向：
- verifier 先判断回答是否忠实于 evidence / decision
- 违规时产出结构化 `RewriteInstruction`
- rewrite 循环消费指令，而不是只看计数器

核心原则：
- 空 evidence / 空 draft 不应伪装成通过
- unsupported / contradicted claim 要显式进入 rewrite 指令
- 超限后进入 deterministic fallback

---

## 8. response_subgraph 的外层路由

文件：[`engine/subgraphs/response_subgraph.py`](../local_life_agent/engine/subgraphs/response_subgraph.py)

它大致分为四类：
- `direct` / `reject`：直接透传
- `clarify`：输出澄清
- `fallback`：输出可信兜底
- `answer`：走完整回答生成与校验

补充规则：
- 比较任务遇到指代不清时，会提前转澄清
- 直接回答/拒绝/探索计划通常不进入完整 LLM 生成链

---

## 9. 相关工作流

当前第三层相关 workflow 包括：
- `direct_response`
- `single_shop_fact_workflow` / `deterministic_tool`
- `clarification_fallback`
- `exploration_planning`
- `recommendation_decision_workflow`
- `comparison_decision_workflow`
- `complex_orchestrator_workflow`

这些 workflow 的最终出口都应该回到统一 response contract，而不是各自拼最终字符串。

---

## 10. 结论

第三层现在的核心不是“写一句话”，而是：

**把回答做成可验证、可重写、可降级、可追踪的统一出口。**
