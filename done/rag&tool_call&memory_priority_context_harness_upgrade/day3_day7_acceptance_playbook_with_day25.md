# 验收手册：Day3–Day7 重新规划版（含 Day2.5）

> 前提：Day1 Context Boundary 与 Day2 AnswerContract 已完成；Day2.5 未完成并已调整为新 Day3。  
> 范围：Day3 RAG Dirty Guardrail、Day4 Tool、Day5 RAG Parent/Hybrid、Day6 Answer Quality、Day7 Graph/Memory/Harness/Cutover。  
> 原则：只看最终答案不够，必须同时验收 trace、路由、状态、证据、工具、回答质量和生产切流。

---

## 1. 全局必断言字段

每个 E2E case 都必须断言：

```text
runner_kind = langgraph
runner_backend = langgraph
graph_runtime = langgraph
final_answer 非空
无 Traceback
无 None 泄露
无 debug 字段泄露
latest_turn_priority = true
```

Day7 后：

```text
生产运行时没有 legacy fallback 分支
```

---

## 2. Day3 RAG Dirty Guardrail 验收

### Case R0：问 A 店召回 B 店必须 drop

输入：

```text
海底捞水晶城店适合约会吗？
```

模拟 evidence：

```text
shop_id = 巴奴
facet = environment
```

期望：

```text
dropped_by_shop_count > 0
final_clean_evidence_count = 0 或只保留目标店 evidence
final_answer 不引用 B 店 evidence
```

---

### Case R1：问环境不能注入券 evidence

输入：

```text
海底捞水晶城店环境怎么样？
```

期望：

```text
allowed_rag_facets 包含 environment / scene_fit
forbidden_rag_facets 包含 coupon / open_status
coupon evidence 被 drop
final prompt / final_answer 不包含 dropped coupon evidence
```

---

### Case R2：全部弱证据时降级

输入：

```text
这家适合约会吗？
```

模拟：

```text
所有 evidence support_level = weak / irrelevant
```

期望：

```text
rag_quality_status = weak 或 empty
final_answer 说明证据不足
不能强行断言适合约会
```

---

### Case R3：sibling 补全不能污染 context

命中 child：

```text
facet = environment
```

sibling：

```text
facet = coupon
```

期望：

```text
sibling coupon 被 drop
dropped_by_sibling_count > 0
```

---

## 3. Day4 Tool 验收

### Case T1：问券必须走 Tool

输入：

```text
海底捞水晶城店有券吗？
```

期望：

```text
route = tool
tool_plan.required_tools 包含 coupon
answer 中券数量必须来自 tool_result
不能从 RAG 猜券
```

---

### Case T2：营业状态必须走 Tool

输入：

```text
海底捞水晶城店现在营业吗？
```

期望：

```text
route = tool
tool_plan.required_tools 包含 open_status
实时声明必须由 tool_result 支撑
```

---

### Case T3：工具失败不编造

模拟：

```text
coupon tool timeout
```

期望：

```text
answer 说明暂时无法确认实时券信息
不能编造券数量
error_type = TOOL_TIMEOUT
```

---

## 4. Day5 RAG Parent/Hybrid/Eval 验收

### Case P1：single_shop_rag 不串店

输入：

```text
海底捞水晶城店适合约会吗？
```

期望：

```text
rag_mode = single_shop_rag
evidence_shop_ids 全部等于 target_shop_id
```

---

### Case P2：recommendation_rag 按 shop_id 分组

输入：

```text
附近有没有适合约会的餐厅？推荐几家。
```

期望：

```text
route = recommendation
rag_mode = recommendation_rag
grouped_by_shop 不为空
返回多个不同 shop_id
同一家店不能重复占多个推荐位
```

---

### Case P3：推荐不被上一轮单店污染

输入：

```text
第 1 轮：海底捞水晶城店怎么样？
第 2 轮：附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。
```

期望：

```text
第 2 轮 route = recommendation
single_shop_mode = false
single_shop_anchor_dropped = true
不只回答海底捞
```

---

### Case P4：RAG Eval 输出指标

命令：

```bash
python -m learning_agent_service.local_life.eval.run_rag_eval \
  --cases eval/local_life/rag_eval_cases.jsonl
```

期望输出：

```text
recall@5
mrr@10
ndcg@10
cross_shop_rate
facet_hit_rate
dirty_context_rate
```

---

## 5. Day6 Answer Quality 验收

### Case A1：单店综合评价不能只答一句

输入：

```text
海底捞水晶城店怎么样？
```

期望：

```text
answer_style = single_shop_review
answer_depth_level in [normal, detailed]
section_count >= 4
包含：总体结论、核心优点、可能不足、适合场景、建议
```

---

### Case A2：适合约会必须有结构

输入：

```text
这家适合约会吗？
```

期望：

```text
包含结论
包含至少 2 条理由
包含风险或注意事项
包含建议
```

---

### Case A3：推荐多店不重复

输入：

```text
附近推荐几家适合约会的餐厅
```

期望：

```text
至少 3 家店或明确候选不足
shop_id 不重复
每家至少 2 条非重复推荐理由
```

---

### Case A4：问券保持短答

输入：

```text
海底捞水晶城店有券吗？
```

期望：

```text
answer_style = coupon_only
answer_depth_level = short
不扩展环境
不推荐其他店
```

---

## 6. Day7 Graph / Memory / Harness / Cutover 验收

### Case G1：latest_turn_message 第一输入

输入：

```text
第 1 轮：海底捞水晶城店环境怎么样？
第 2 轮：这家有券吗？
```

期望：

```text
understand_query 读取第 2 轮 latest_turn_message
current_intent = coupon
history_summary 只作为弱辅助
```

---

### Case G2：显式换店覆盖 session

输入：

```text
第 1 轮：海底捞水晶城店怎么样？
第 2 轮：巴奴毛肚火锅有券吗？
```

期望：

```text
第 2 轮 target_shop = 巴奴毛肚火锅
winning_source = current_turn_perception
suppressed_source 包含 session.current_shop: 海底捞水晶城店
```

---

### Case G3：临时偏好不写长期

输入：

```text
长期偏好：喜欢辣
当前输入：今天不要辣
```

期望：

```text
effective_context.spicy = no_spicy
promotion_candidates 为空
long_term_profile 不变
```

---

### Case H1：Golden Cases 全量回归

命令：

```bash
python -m learning_agent_service.local_life.eval.run_golden_cases \
  --cases eval/local_life/golden_cases.jsonl \
  --output reports/local_life_golden_report.json
```

期望：

```text
golden pass rate >= 95%
失败 case 有 error_type
```

---

### Case H2：生产只走 LangGraph

期望：

```text
graph_runtime = langgraph
生产代码无 legacy fallback 运行时分支
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY 已删除或废弃
```

---

## 7. Error Taxonomy

```text
LOW_INFO_QUERY
TARGET_SHOP_MISSING
TARGET_SHOP_AMBIGUOUS
TARGET_SHOP_WRONG
ROUTE_MISMATCH
CONTRACT_VIOLATION
FACET_LEAK
RAG_EMPTY
RAG_CROSS_SHOP
RAG_LOW_CONFIDENCE
RAG_DIRTY_CONTEXT
TOOL_TIMEOUT
TOOL_ERROR
TOOL_BAD_RESULT
UNSUPPORTED_REALTIME_CLAIM
ANSWER_TOO_SHORT
ANSWER_REPETITIVE
RECOMMENDATION_DUPLICATE_SHOP
MEMORY_ARBITRATION_ERROR
GRAPH_NODE_ERROR
GRAPH_ILLEGAL_STATE_MUTATION
COMPOSE_ERROR
```

---

## 8. 最终通过标准

```text
1. 所有 Day3–Day7 关键 case 从 /internal/v1/chat/stream 通过。
2. golden_cases 通过率 >= 95%。
3. graph_runtime = langgraph。
4. 生产运行时无 legacy fallback。
5. cross_shop_rate = 0。
6. facet_leak_rate = 0。
7. dirty_context_rate = 0。
8. unsupported_realtime_claim_rate = 0。
9. answer_too_short_rate 在核心场景为 0。
10. answer_repetitive_rate 在核心场景为 0。
11. latest_turn_priority_failure_rate = 0。
12. recommendation 不被 single_shop anchor 污染。
13. 工具失败不编造。
14. RAG 空召回不编造。
15. Memory Arbitration 有 trace 可解释。
```

---

## 9. 验收报告模板

```markdown
# Local Life Agent Day3–Day7 验收报告

## 总览
- 总 case 数：
- 通过：
- 失败：
- 通过率：
- graph_runtime：
- legacy fallback：
- p95 latency：

## 指标
- cross_shop_rate：
- facet_leak_rate：
- dirty_context_rate：
- unsupported_realtime_claim_rate：
- answer_too_short_rate：
- answer_repetitive_rate：
- latest_turn_priority_failure_rate：

## 失败类型分布
- ROUTE_MISMATCH：
- RAG_DIRTY_CONTEXT：
- TOOL_TIMEOUT：
- ANSWER_TOO_SHORT：
- ANSWER_REPETITIVE：
- MEMORY_ARBITRATION_ERROR：
- GRAPH_ILLEGAL_STATE_MUTATION：

## 是否允许进入上线阶段
- [ ] 是
- [ ] 否

## 剩余风险
1. ...
2. ...
```
