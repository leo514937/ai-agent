# Day3–Day7 重新规划总览：补入 Day2.5 RAG 脏数据治理

> 背景：Day1–Day2 已完成，但 Day2.5「RAG 脏数据治理」尚未完成。  
> 结论：不能把 Day2.5 藏进 Day4 的大 RAG 方案里，必须提前作为新的 Day3 单独完成。  
> 本目录共 7 个 Markdown：总览 + Day3–Day7 五天计划 + 验收手册。

---

## 1. 为什么要重排

上一版规划把 Day2.5 合并进了 Day4：

```text
Day4：RAG Clean Evidence、父子检索、混合检索与脏数据治理
```

这个安排在“Day2.5 已完成”的前提下可以接受。但现在 Day2.5 还没做，所以必须调整。

原因：

```text
1. RAG 脏数据治理是 P0，不应该被放到父子检索和混合检索后面。
2. 如果没有 Clean Evidence Pack，后面的回答质量增强会把脏内容放大。
3. 如果没有 RAG Guardrail，父子检索 sibling 补全可能进一步扩大污染。
4. Tool、RAG、Answer、Graph、Harness 都依赖“进入 LLM 的证据是干净的”。
```

---

## 2. 新顺序

```text
Day3：RAG Dirty Data Guardrail 与 Clean Evidence Pack
Day4：Tool Harness 与实时信息契约
Day5：RAG 父子检索、混合检索与 RAG Eval
Day6：Answer Quality、Depth Policy 与 Repetition Guard
Day7：GraphState、Memory Arbitration、Harness、Cutover 与生产硬化
```

额外文档：

```text
00_day3_day7_replan_overview_with_day25.md
08_day3_day7_acceptance_playbook_with_day25.md
```

---

## 3. 为什么 Day3 先做 RAG Dirty Guardrail

Day2 已完成 AnswerContract，已经知道：

```text
用户问什么 facet
哪些 facet 允许
哪些 facet 禁止
哪些信息必须实时工具
```

所以 Day3 可以马上做：

```text
EvidenceJudgement
LocalLifeRagGuardrail
drop_cross_shop_evidence
drop_forbidden_facet_evidence
drop_low_relevance_evidence
Clean Evidence Pack
低质证据降级
```

这一步必须在父子检索深度改造之前完成。

---

## 4. 五天依赖关系

### Day3 → Day4

Day3 提供：

```text
clean_evidence_pack
rag_quality_status
forbidden_facet_drop
realtime_facet_from_rag_drop
```

Day4 Tool Harness 会基于这些规则明确：

```text
coupon / open_status 不能靠 RAG，必须走 Tool
```

---

### Day4 → Day5

Day4 建立工具实时边界后，Day5 才能做 RAG 父子和混合检索，避免：

```text
把实时信息错误地纳入 RAG 主结论
```

---

### Day5 → Day6

Day5 提供结构化、可评测的 evidence：

```text
RAG eval
BM25 + dense + metadata
parent/child/sibling
group_by_shop
```

Day6 基于 clean evidence 做回答质量：

```text
回答变长
结构化
不重复
不编造
```

---

### Day6 → Day7

Day7 将所有中间结果纳入：

```text
GraphState
Memory Arbitration
Golden Cases
Trace
Error Taxonomy
Cutover
Production Hardening
```

---

## 5. 最终链路

```text
/chat/stream
  ↓
latest_turn_message
  ↓
understand_query
  ↓
AnswerContract
  ↓
Day3 RAG Guardrail / Clean Evidence
  ↓
Day4 Tool Realtime Contract
  ↓
Day5 Parent-Child Hybrid RAG
  ↓
Day6 Answer Quality Gate
  ↓
Day7 GraphState + Memory + Harness + Cutover
```

更准确地说，运行时不是线性执行 Day3–Day7，而是这些能力共同组成最终主链路：

```text
load_context
  ↓
understand_query(latest_turn_message first)
  ↓
memory_arbitration
  ↓
resolve_target
  ↓
build_answer_contract
  ↓
route_gate
  ├── tool_subgraph
  ├── rag_subgraph + rag_guardrail
  ├── rag_plus_tool
  └── recommendation_subgraph
  ↓
answer_depth_policy
  ↓
answer_structure_composer
  ↓
repetition_guard
  ↓
answer_quality_gate
  ↓
persist_session
  ↓
emit_final
```

---

## 6. 新文档列表

```text
00_day3_day7_replan_overview_with_day25.md
03_day3_rag_dirty_data_guardrail.md
04_day4_tool_realtime_contract.md
05_day5_rag_parent_child_hybrid_eval.md
06_day6_answer_quality_depth_repetition.md
07_day7_graph_memory_harness_cutover.md
08_day3_day7_acceptance_playbook_with_day25.md
```

---

## 7. 建议仓库路径

```text
todo/local_life_day3_day7_replanned_with_day25/
```

---

## 8. 总验收原则

```text
1. Day3 必须先完成，不允许跳过。
2. 所有关键测试必须从 /internal/v1/chat/stream 触发。
3. RAG dropped evidence 不允许进入 final prompt / final_answer。
4. coupon / open_status 不允许由 RAG 猜。
5. 回答变长必须基于 clean evidence，不能编造。
6. latest_turn_message 必须高于 history_summary。
7. recommendation 不能被上一轮 single_shop current_shop 污染。
8. Day7 后生产运行时只保留 LangGraph 主链路。
```
