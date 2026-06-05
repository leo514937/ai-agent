# Day6：Answer Quality、Depth Policy 与 Repetition Guard

> 目标：解决 AI 回复过短、结构不完整、重复内容、重复推荐理由、重复店铺等问题。  
> 前置：Day3 Clean Evidence Guardrail 与 Day5 RAG Eval 已完成。  
> 核心原则：回答变长必须基于 clean evidence，不能为了变长而编造。

---

## 1. Day6 要解决什么

用户侧问题：

```text
问“这家怎么样”，只返回一句“整体还不错”。
问“适合约会吗”，没有结论、理由、风险和建议。
问“推荐几家”，每家只给一句泛泛理由。
答案中重复出现“整体不错”“环境不错”等低信息表达。
推荐结果中同一家店重复出现。
```

Day6 目标：

```text
在 clean evidence 支撑下，让回答充分、结构化、不重复。
```

---

## 2. 总体链路

```text
AnswerContract
  ↓
Clean Evidence Pack / Tool Results
  ↓
AnswerDepthPolicy
  ↓
AnswerStructureComposer
  ↓
RepetitionGuard
  ↓
AnswerQualityGate
  ↓
final_answer
```

---

## 3. AnswerDepthPolicy

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/answer_depth_policy.py
```

结构：

```python
@dataclass(frozen=True)
class AnswerDepthPolicy:
    depth_level: Literal["short", "normal", "detailed"]
    min_sections: int
    max_sections: int
    min_bullets_per_section: int
    min_chars: int
    require_summary: bool
    require_evidence_reasoning: bool
    require_risk_or_caveat: bool
    require_next_step: bool
    depth_limited_by_evidence: bool
    reason: str
```

---

## 4. answer_style 到 depth 的映射

```text
coupon_only:
  depth = short
  不允许为了变长扩展环境/推荐

open_status_only:
  depth = short
  不允许扩展到评价/推荐

single_shop_review:
  depth = normal 或 detailed
  min_sections = 4

scene_fit:
  depth = normal
  min_sections = 4

facet_multi:
  depth = normal
  每个 facet 至少一段

multi_shop_recommendation:
  depth = detailed
  至少 3 家店，或明确候选不足
  每家至少 2 条有效理由

clarification:
  depth = short
```

---

## 5. clean_evidence_count 约束

```text
clean_evidence_count = 0:
  只允许证据不足降级回答
  禁止为了变长而编造

clean_evidence_count = 1:
  允许简短回答
  必须提示“证据有限”

clean_evidence_count >= 2:
  允许正常展开

clean_evidence_count >= 4:
  允许详细展开
```

---

## 6. AnswerStructureComposer

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/answer_structure_composer.py
```

### 单店综合评价

必须至少输出：

```text
1. 总体结论
2. 核心优点
3. 可能不足
4. 适合场景
5. 到店建议
```

### 适合场景

必须输出：

```text
1. 结论
2. 理由
3. 风险
4. 建议
```

### 多 facet 复合问题

例如：

```text
有券吗，现在营业吗，环境怎么样？
```

必须按 facet 分块：

```text
1. 优惠券
2. 营业状态
3. 环境评价
4. 综合建议
```

### 多店推荐

每家店至少：

```text
推荐理由
适合场景
注意事项
```

每家至少 2 条非重复理由。

---

## 7. RepetitionGuard

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/repetition_guard.py
```

职责：

```text
重复句子去重
重复 bullet 合并
重复推荐理由合并
低信息表达过滤
推荐店铺按 shop_id 去重
```

低信息表达：

```text
整体不错
还可以
比较好
值得考虑
体验不错
口碑还行
```

规则：

```text
每个答案最多出现一次泛评价。
优先保留带具体 evidence 的句子。
```

---

## 8. AnswerQualityGate

新增：

```text
learning-agent-service/src/learning_agent_service/local_life/answer_quality_gate.py
```

检查：

```text
answer_char_count
section_count
bullet_count
duplicate_sentence_count
duplicate_ratio
answer_too_short
answer_too_repetitive
forbidden_facet_leak
unsupported_realtime_claim
evidence_coverage
recommendation_duplicate_shop
```

流程：

```text
draft_answer
  ↓
RepetitionGuard.dedupe
  ↓
QualityGate.check
  ↓
如果太短且有 clean evidence：expand_answer
  ↓
如果重复：dedupe_answer
  ↓
如果无证据：保持降级，不扩写
  ↓
final_answer
```

---

## 9. 需要修改的现有文件

```text
learning-agent-service/src/learning_agent_service/local_life/answer_contract.py
learning-agent-service/src/learning_agent_service/local_life/answer_planner.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
learning-agent-service/src/learning_agent_service/local_life/answer_sanitizer.py
learning-agent-service/src/learning_agent_service/local_life/evidence_pack.py
learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py
learning-agent-service/src/learning_agent_service/application/workflow/services.py
```

---

## 10. Trace 字段

```text
answer_style
answer_depth_level
answer_min_sections
answer_min_chars
clean_evidence_count
strong_evidence_count
medium_evidence_count
answer_char_count
section_count
bullet_count
duplicate_sentence_count
duplicate_ratio
answer_too_short
answer_too_repetitive
depth_limited_by_evidence
expanded_by_quality_gate
deduped_by_repetition_guard
recommendation_duplicate_shop_count
final_answer_char_count
delta_count
```

---

## 11. Harness 测试

新增：

```text
tests/local_life/answer/test_answer_depth_policy.py
tests/local_life/answer/test_answer_structure_composer.py
tests/local_life/answer/test_repetition_guard.py
tests/local_life/answer/test_answer_quality_gate.py
tests/local_life/answer/test_answer_quality_chat_e2e.py
```

必测：

```text
1. “海底捞水晶城店怎么样？”不能只回复一句。
2. “这家适合约会吗？”必须有结论、理由、风险、建议。
3. “附近推荐几家适合约会的餐厅”必须返回多店结构，每店至少两条理由。
4. “有券吗？”保持短答，不能为了变长扩展环境。
5. clean_evidence_count=0 时不能为了变长编造。
6. 重复句子必须被去重。
7. 推荐结果不能重复同一个 shop_id。
8. SSE final_answer_char_count 必须达到可接受阈值。
```

---

## 12. 验收标准

Day6 完成后必须满足：

```text
1. single_shop_review 不再只回复一句。
2. scene_fit 问题有结论、理由、风险、建议。
3. multi_shop_recommendation 按多店结构输出。
4. coupon_only / open_status_only 保持短答，不乱扩展。
5. clean_evidence_count=0 时不为了变长编造。
6. 重复句子、重复 bullet、重复店铺被去重。
7. 最终 answer 有质量 trace。
8. answer_too_short 和 answer_too_repetitive 可观测。
9. 所有关键 E2E 测试从 /internal/v1/chat/stream 触发。
```

---

## 13. 给 Codex 的执行提示词

```text
你是资深 Python / LLM 应用 / Context Engineering / Harness Engineering 工程师。

Day1-Day5 已完成。请执行 Day6：Answer Quality、Depth Policy 与 Repetition Guard。

必须完成：
1. 新增 AnswerDepthPolicy。
2. 根据 AnswerContract.answer_style 设置默认回答深度。
3. 根据 clean_evidence_count 控制展开，禁止为了变长而编造。
4. 新增 AnswerStructureComposer。
5. 新增 RepetitionGuard。
6. 新增 AnswerQualityGate。
7. 修改 answer_planner prompt，传入 answer_depth_policy 和结构要求。
8. 修改 response_builder，使其按结构输出，并经过去重与质量门禁。
9. 增加 trace。
10. 增加 E2E 测试。
11. 检查 max_tokens / max_output_tokens / SSE final 是否截断。
12. 所有关键测试从 /internal/v1/chat/stream 入口触发。
13. 输出修改文件、测试命令、测试结果、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
