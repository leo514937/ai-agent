# 候选/目标/胜者解析管线架构差距审计

> 审计日期: 2026-06-30
> 审计范围: `local_life_agent/` 的 candidate→target→winner 解析、状态语义、证据构建、回答生成与验证全链路
> 方法: 代码读取(14个核心文件) + 静态搜索(6种模式) + 动态测试(5个测试套件) + 行业范式比对

---

## 1. 当前实现链路图

```
User Input
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ context_recovery.py                                                  │
│   ├─ task_type == "comparison" → resolve_comparison_targets()        │
│   │      → reference_resolver.py: resolve_comparison_targets()      │
│   │      → returns {"targets": [...], "status": "...", ...}         │
│   │                                                                  │
│   └─ 其他 → resolve_references() → ResolveShopResult{status,shop}    │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ comparison_targets / resolved_target
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ planning_subgraph.py: _h_target_resolve_candidate_set()               │
│   ├─ pre_resolved_target short-circuit (~352-387)                    │
│   ├─ 否则: build CandidateSet via CandidateResolver                  │
│   │   → candidate_resolver.py  (resolve/mixed/discovery 等方法)      │
│   │   → 返回 CandidateSet{status, candidates:[ResolvedCandidate]}     │
│   │                                                                  │
│   ├─ *** 关键回归 *** line ~355: `if len(candidates) == 1`           │
│   │   本应为 `if candidates:` — 多候选场景被提前截断为 NOT_FOUND      │
│   │                                                                  │
│   └─ 输出: candidate_set, effective_candidate_set,                   │
│            reference_resolution_source, target_resolution_status      │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ candidate_set
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ evidence_planner.py: plan_evidence()                                  │
│   ├─ 从 CandidateSet + Goal 生成 ExecutionPlan (tool_calls)          │
│   ├─ 逐候选店生成 facet 级别的工具调用                                │
│   ├─ 区分 required_facets / optional_facets                           │
│   └─ 输出: ExecutionPlan{plan_id, task_type, tool_calls}              │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ execution_plan
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ToolCallGateway → 执行工具 → 返回 tool_results                       │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ tool_results
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ evidence_builder.py: build_evidence()                                 │
│   ├─ task_type == "comparison" → _build_comparison_evidence()        │
│   │     → 构建 ComparisonMatrix{rows, cells, dimension_winners}      │
│   │     → 输出 ranking_snapshot{ranked_shops}                        │
│   │                                                                  │
│   ├─ task_type == "recommendation" → _build_recommendation_evidence()│
│   │     → rank_candidates() → ranked_snapshot                        │
│   │     → 输出 ranking_snapshot{ranked} + last_recommendation_list   │
│   │                                                                  │
│   └─ 单店 → build 单店 evidence                                      │
│      → 输出 ranking_snapshot{shop_id, coupon_count, open_status...}  │
│                                                                      │
│   ⚠ 输出格式不统一:                                                  │
│   - 比较: ranking_snapshot = {snapshot_id, status, ranked_shops}     │
│   - 推荐: ranking_snapshot = {snapshot_id, status, ranked,           │
│            ranked_shops, query_terms, scene_terms, candidate_count}  │
│   - 单店: ranking_snapshot = {status, shop_id, shop_name,            │
│            coupon_count, coupon_titles, open_status, ...}            │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ evidence_pack
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ answer_plan_builder.py: build_answer_plan()                           │
│   ├─ 从 evidence 推 answer_type + fallback_template_type             │
│   └─ 输出: answer_type, target_shop_ids, response_sections           │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ answer_plan
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ answer/generator.py: generate_answer() → _build_decision_plan()       │
│   ├─ 决策类型分流:                                                    │
│   │   ├─ comparison/recommendation → CandidateEvidenceCollector       │
│   │   │     + CandidateEvaluator + build_candidate_decision_plan     │
│   │   │     → CandidateDecisionPlan → 映射为 DecisionPlan            │
│   │   │                                                              │
│   │   └─ 单店 → 直接构建 DecisionPlan 含 factual_points              │
│   │                                                                  │
│   ├─ decision_context 含 raw_comparison_rows + raw_ranking_rows      │
│   └─ 输出: DecisionPlan(供 LLM verbalizer 消费)                      │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ DecisionPlan
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ llm_verbalizer.py: verbalize_decision_plan()                          │
│   ├─ LLM → 自然语言回答 → B2MiniVerifier 校验                        │
│   ├─ 校验不通过 → rewrite (最多3次) → fallback → rule_based_         │
│   └─ 输出: 最终回答文本                                              │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ final_answer
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ state_update_plan.py: state_update → persist → emit                   │
│   ├─ 通过 StateCore.plan_state_update → SessionWriteDirective        │
│   ├─ 持久化: current_shop, last_recommendation_list,                 │
│   │           comparison_targets, comparison_result,                  │
│   │           pending_clarification, active_constraints               │
│   └─ 输出: 最终 AgentResponse                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 状态语义审计

### 2.1 当前使用的状态标签

| 状态值 | 定义位置 | 语义含义 | 使用场景 |
|--------|----------|----------|----------|
| `CandidateStatus.RESOLVED` = `"resolved"` | `domain/candidate.py:25` | 候选集已解析 | 单店、多店候选集均使用 |
| `ResolveShopResult.status = "RESOLVED"` | `domain/schemas.py:549,566` | 店铺已解析 | 单店 resolve 操作 |
| `target_resolution_status = "RESOLVED"` | `planning_subgraph.py:370` | 目标已解析 | 整个目标解析阶段输出 |
| `context_resolution.status = "resolved"` | `context_recovery.py:83` | 上下文恢复 | 多轮上下文恢复 |
| `comparison_target_resolution.status` | `reference_resolver.py` | 比较目标解析 | 比较场景专用 |
| `CandidateStatus.NOT_FOUND` | `domain/candidate.py` | 未找到候选 | 搜索无结果 |
| `CandidateStatus.AMBIGUOUS` | `domain/candidate.py` | 候选歧义 | 需澄清 |

### 2.2 关键问题: 状态语义压缩

**"RESOLVED" 被重载为 4+ 种不同含义:**

```
"RESOLVED" 的含义:
  1. 单店查询: 用户想查的店铺已确定 → resolved_shop 不为空
  2. 多候选集: 搜索/推荐返回 ≥1 家候选店 → candidates ≠ []
  3. 比较场景: 用户想比较的店铺列表已确定 → comparison_targets ≠ []
  4. 比较结果: 每家店的 facet 数据已获取 → comparison_matrix.rows ≠ []
```

**问题:**
- 当 `target_resolution_status == "RESOLVED"` 时，下游无法区分是"找到了1家店"还是"找到了5家候选店"
- `candidate_set.status == "resolved"` 可能表示 1 家店或 20 家候选店 — 下游只能通过 `len(candidates)` 推测
- 没有一个状态表示"赢家已决策"(winner decided) — 比较场景中"哪家更好"的判断结果没有独立状态
- `comparison_matrix.dimension_winners` 是赢家信息的载体，但没有对应的状态码

### 2.3 对比: 行业状态范式

| 范式 | 候选集状态 | 目标状态 | 胜者状态 | 备注 |
|------|-----------|---------|---------|------|
| Google Schema-Guided | ONTOLOGY_MATCHED | SLOT_FILLED | N/A | 槽位级置信度 |
| Alexa Conversations | RESOLVED | CONFIRMED | SELECTED | 三层分离 |
| Microsoft Dataflow | CANDIDATE_SET | SELECTED | WINNER | 明确 winnowing |
| Rasa | intent_ranked | entity_extracted | slot_filled | 每步独立 |
| **本项目(当前)** | **RESOLVED(重载)** | **RESOLVED(重载)** | **无** | |

---

## 3. 高风险混合点

### 3.1 `planning_subgraph.py` ~L354: 候选数守卫 (回归根因)

```python
# 当前 (问题代码):
if len(candidates) == 1:  # ← BUG: 仅单候选通过, ≥2 候选走向 NOT_FOUND
    # ... 构建 CandidateSet ...

# 应为:
if candidates:  # 或 if len(candidates) >= 1
    # ... 构建 CandidateSet ...
```

**影响:**
- 所有多候选场景(比较、推荐、推荐追问)均被截断
- 导致 `test_discovery_hotpot_resolves_to_finish` 期望 `RESOLVED` 但得到 `NOT_FOUND`
- 导致比较流中 `comparison_targets` 为空 (因为没有候选集就没有后续比较构建)

### 3.2 `context_recovery.py` L67-78: 比较上下文恢复的孤立路径

```python
if str(task_type_value or "") == "comparison":
    comparison_resolution = resolve_comparison_targets(source_text, session_state, frame)
    return {
        "comparison_target_resolution": comparison_resolution,
        "comparison_targets": comparison_resolution.get("targets", []),
        ...
    }
```

**问题:**
- 此路径返回 `comparison_targets` 但**未触发** `CandidateResolver` 解析流程
- 下游 `planning_subgraph._h_target_resolve_candidate_set` 期望 `candidate_set` 存在，但此处仅设置 `comparison_targets`
- 两个路径在状态图中以不同方式被消费，形成了**并行但未对齐的管线**

### 3.3 `evidence_builder.py` L642-668: 证据层面的 task_type 分流

```python
def build_evidence(...):
    task_type = str(plan_dict.get("task_type", ""))
    if task_type == "comparison":
        return _build_comparison_evidence(...)  # 比较证据路径
    # ...
    if str(plan_dict.get("task_type", "")) == "recommendation":
        return _build_recommendation_evidence(...)  # 推荐证据路径
    # ...
    return { ... }  # 单店证据路径
```

**问题:**
- `_build_comparison_evidence` 的 `comparison_targets` 输入来自 `planning_subgraph` 的输出
- 如果 `planning_subgraph` 因为 `len(candidates) == 1` bug 未正确设置候选集，则 `comparison_targets` 为空
- 证据层的3条路径输出格式不同，但下游(`generator.py`)试图用统一接口消费

### 3.4 `generator.py` L132-199: 推荐和比较共用决策管道

```python
if decision_type in ("recommendation", "comparison"):
    # 完全相同的候选收集+评估+决策路径
    collector = CandidateEvidenceCollector()
    evidences = collector.collect(shop_ids, tool_results)
    evaluator = CandidateEvaluator()
    evaluations = evaluator.evaluate(evidences, decision_type, preferences)
    candidate_plan = build_candidate_decision_plan(...)
    plan = map_candidate_decision_plan_to_decision_plan(candidate_plan)
```

**问题:**
- 推荐和比较使用完全相同的 `CandidateEvidenceCollector` 和 `CandidateEvaluator`
- 但比较场景需要维度级胜者判定，推荐不需要
- 当前代码在比较路径中额外构建 `dimension_winners`，但维度数据被塞入 `decision_context.raw_comparison_rows`，传递方式脆弱

### 3.5 `generator.py` L210-261: 比较场景的两种并行实现

```python
# 路径A (L133-199): CandidateDecisionPlan 路径 — 新架构
if decision_type in ("recommendation", "comparison"):
    # ... 使用 CandidateDecisionPlan ...

# 路径B (L210-261): 旧比较路径 — 遗留代码
if answer_type == "comparison" or (comparison_matrix and ...):
    # 直接解析 comparison_matrix.rows → selected_targets + factual_points
```

**问题:**
- 路径A 和 路径B 会在某些输入下**同时执行** (当 `decision_type == "comparison"` 且 `comparison_matrix` 非空时)
- 路径A 退出 `return plan`，路径B 永远不会到达 — 但两段代码共存增加维护陷阱
- 路径B 中 `selected_targets`, `overall_ranking`, `factual_points`, `best_for` 的构建重复了路径A 的工作

### 3.6 `llm_verbalizer.py` L396-427: 验证失败后处理逻辑

```python
if not verification_result["passed"]:
    if in_graph and rewrite_count < _GRAPH_REWRITE_LIMIT and recoverable:
        return natural_text  # 让验证器失败触发 rewrite
    return natural_text + error_note  # 验证失败但无法 rewrite
```

**问题:**
- rewrite 逻辑依赖于 `natural_text` 的正确性 — 如果 LLM 输出了虚假内容，rewrite 只是重新提示
- rewrite 的重试计数器在 `llm_verbalizer.py` 内部管理，但实际 rewrite 触发在上层 graph 中
- 没有跨 rewrite 尝试的"历史记忆" — 每次 rewrite 都是独立提示，无法学习之前的错误

---

## 4. 测试失败归因

### 4.1 动态测试结果汇总

| 测试套件 | 通过 | 失败 | 关键失败 |
|----------|------|------|----------|
| `test_comparison_flow.py` | 16 | **8** | 比较流核心回归 |
| `test_target_resolve_candidate_set.py` | 8 | **1** | discovery_hotpot NOT_FOUND |
| `test_recommendation_flow.py` | 15 | **2** | 推荐追问/引用失败 |
| `test_subgraph_core_integration.py` | 5 | 0 | — |
| `test_phase1_acceptance.py` | 6 | 0 | — |
| `test_candidate_schema.py` | 36 | 0 | — |

### 4.2 失败链因果关系

```
Root Cause: planning_subgraph.py L355 `if len(candidates) == 1` (本应为 `if candidates:`)
    │
    ├─→ discovery hotpot 多候选 → NOT_FOUND (而不是 RESOLVED)
    │     → test_target_resolve_candidate_set.py 失败
    │
    ├─→ comparison_targets 为空(因为候选集未正确构建)
    │     → test_comparison_flow.py 中6个测试失败
    │         ├─ test_compare_three_from_last_recommendation_list
    │         ├─ test_compare_first_item_and_explicit_shop
    │         ├─ test_compare_this_shop_without_current_shop_must_clarify
    │         ├─ test_ambiguous_explicit_shop_goes_to_pending_clarification
    │         ├─ test_pending_reply_restores_comparison_task
    │         ├─ test_comparison_success_writes_comparison_result_not_overwrite_recommendation_list
    │         ├─ test_after_comparison_second_item_reference_still_works
    │         └─ test_comparison_flow_does_not_enter_single_shop_flow
    │
    └─→ 推荐场景引用的 last_recommendation_list 不正确
          → test_recommendation_flow.py 中2个测试失败
              ├─ test_recommendation_success_updates_last_recommendation_list_not_current_shop
              └─ test_after_recommendation_first_item_reference_works
```

### 4.3 测试本身的质量问题

- `test_comparison_flow.py` 的 8 个失败中有 6 个断言 `comparison_targets` 存在 — 这是正确的断言，但根本原因是上游 bug
- 缺少对"候选集正确构建"的独立单元测试 — 现有测试覆盖的是集成级别行为
- 比较流的 trace 测试 (`test_semantic_llm_main_path.py`) 通过了，表明 flow 的路由未被破坏，只是数据载荷为空

---

## 5. `ranking_snapshot` 消费审计

### 5.1 读取点

| 文件 | 行 | 用途 | 风险等级 |
|------|-----|------|---------|
| `generator.py:37-38` | `_build_shop_name_map` | 从 `ranking_snapshot.get("ranked")` 提取 shop_id→shop_name 映射 | 低 (仅名称映射) |
| `generator.py:108` | `_shop_display_name` | 从 `ranking_snapshot.get("shop_name")` 获取单店显示名 | 低 (仅展示) |
| `generator.py:193,463` | `decision_context` | 存入 `raw_ranking_rows` 供 LLM 背景参考 | 中 (LLM 可读到排序信息) |
| `verifier.py:254-265` | `_extract_ranked_shop_names` | 从 `ranking_snapshot` 提取店名用于排序校验 | 中 (验证器依赖) |
| `verifier.py:108` | `_collect_allowed_shop_names` | 遍历 `ranking_snapshot` 收集允许店名 | 低 |
| `answer_plan_builder.py:24` | `build_answer_plan` | 读取 `ranking_snapshot` 状态 | 低 (仅状态读取) |
| `domain/decision.py:107` | `decision_to_answer_plan` | 读取 `ranking_snapshot` | 低 |
| `observability/trace.py:380-384` | `candidate_count_from_evidence` | 从 `ranking_snapshot` 提取候选数 | 低 (仅可观测性) |

### 5.2 评估

- ✅ 所有非观测性读取均通过 `decision_context` 间接传递 — 不直接用于决策逻辑
- ✅ `generator.py` 中的读取已改为通过 `_build_decision_plan` → `CandidateDecisionPlan` 路径
- ⚠️ 但 `decision_context: {raw_ranking_rows, raw_comparison_rows}` 作为 LLM 的 JSON 输入包含排序信息 — LLM 可能据此改写排序
- ⚠️ `verifier.py` 的 `_extract_ranked_shop_names` + `_comparison_overall_ranked_names` 确实依赖 `ranking_snapshot/ranking_comparison_matrix` 验证排序一致性 — 这是必要的校验，但若 `ranking_snapshot` 格式在不同路径间不统一可能产生误报

### 5.3 建议

`ranking_snapshot` 已基本从决策逻辑中剥离，但：
1. 统一三种 evidence 路径的 `ranking_snapshot` 输出格式（当前推荐/比较/单店输出不同 keyset）
2. 将 `decision_context` 中对 `raw_ranking_rows` 的引用改为使用 `overall_ranking` + `selected_targets`（已有结构化表示）
3. 消除 `verifier.py` 对 `ranking_snapshot` 的依赖 — 改用 `DecisionPlan.overall_ranking`

---

## 6. 行业范式基准

### 6.1 对话状态追踪 (DST) 范式对比

| 维度 | 本项目当前 | Google Schema-Guided | Alexa Conversations | Microsoft Dataflow |
|------|-----------|---------------------|-------------------|-------------------|
| 状态分离度 | 1级 (RESOLVED) | 3级 (ONTOLOGY→SLOT→FILL) | 3级 (RESOLVED→CONFIRMED→SELECTED) | 3级 (CANDIDATE→SELECTED→WINNER) |
| 置信度跟踪 | 无 | 每槽位置信度 | 每实体置信度 | 每候选置信度+分数 |
| 歧义处理 | AMBIGUOUS→澄清 | ONTOLOGY_MATCHES_MULTIPLE→澄清 | RESOLVED_MULTIPLE→澄清 | CANDIDATE_SET→消歧 |
| 证据追溯 | evidence_items | N/A (本体驱动) | 无 | 有 (provenance chain) |
| 状态持久化 | SessionState 全量 | 对话状态表 | Session Attributes | 显式状态机 |

### 6.2 核心差距

1. **状态粒度**: 行业标准使用 3 级状态（候选→目标→胜者），本项目只有 1 级
2. **置信度**: 行业标准在每层级跟踪置信度，本项目仅在 `ResolvedCandidate.confidence` 有初始置信度，下游不再传递
3. **消歧机制**: 行业标准有专门的消歧工作流（如候选集展示+用户确认），本项目靠 `pending_clarification` 手动处理
4. **证据链**: 行业标准有完整的 provence chain 追溯数据来源，本项目 `evidence_items` 仅部分实现
5. **状态机**: 行业标准常用显式状态机驱动对话策略，本项目使用 LangGraph 条件边隐式路由

### 6.3 LangGraph 特有的差距

LangGraph 的节点式编排相较传统 DSL 状态机：
- 优势: 灵活、可嵌套子图、条件边表达力强
- 劣势: 状态隐式编码在 `SessionState` 字典中，没有编译期状态约束
- **建议**: 在 `SessionState` 中增加 `candidate_resolution_stage: str` 枚举字段而非仅靠 `status: str` 来传达语义

---

## 7. 最小修复建议

### 7.1 P0 — 阻止测试回归 (1行改动)

**`planning_subgraph.py` ~L355:**
```python
# 当前:
if len(candidates) == 1:
# 修复:
if candidates:
```

**效果:** 恢复 11 个测试 (8 个比较流 + 1 个候选集 + 2 个推荐流)

### 7.2 P1 — 状态分离 (3个独立改动)

**(a) 新增枚举:**

```python
# domain/candidate.py
class ResolutionStage(str, Enum):
    CANDIDATE_SET_RESOLVED = "candidate_set_resolved"  # 候选集已找到
    TARGET_SELECTED = "target_selected"                 # 单一目标已确认
    WINNER_DECIDED = "winner_decided"                   # 多候选胜者已决策
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
```

**(b) `planning_subgraph.py` 输出 `resolution_stage` 替代纯 `target_resolution_status`**

**(c) `decision.py` 和 `answer/generator.py` 按 `resolution_stage` 分流决策**

### 7.3 P2 — 消除并行比较路径

**`generator.py` L130-260:**
- 删除路径B (L210-261 的旧比较矩阵解析)
- 统一到路径A (CandidateDecisionPlan 范式)
- `decision_type == "comparison"` 和 `decision_type == "recommendation"` 分拆为独立 handler

### 7.4 P2 — 统一 `ranking_snapshot` 格式

在 `evidence_builder.py` 的三个证据构造函数的末尾，输出一致结构的 `ranking_snapshot`：
```python
ranking_snapshot = {
    "snapshot_id": str,
    "status": str,           # ok | empty | unknown
    "candidate_count": int,
    "items": list[dict],      # 统一字段名，替代 ranked/ranked_shops/rows
}
```

### 7.5 P3 — `verifier.py` 从 `ranking_snapshot` 解耦

以 `DecisionPlan.overall_ranking` 替代 `ranking_snapshot` 作为排名信息源。

---

## 8. 推荐状态协议草案

```python
# domain/candidate.py — 新增
class ResolutionStage(str, Enum):
    """对话中候选/目标/胜者解析的三阶段状态。"""
    # --- 阶段1: 候选集 ---
    CANDIDATE_SET_PENDING = "candidate_set_pending"       # 搜索中
    CANDIDATE_SET_RESOLVED = "candidate_set_resolved"     # 搜索完成, 有候选
    CANDIDATE_SET_EMPTY = "candidate_set_empty"           # 搜索完成, 无候选
    
    # --- 阶段2: 目标选择 ---
    TARGET_SELECTED = "target_selected"                    # 单店目标已选择
    TARGET_AMBIGUOUS = "target_ambiguous"                  # 需用户澄清
    
    # --- 阶段3: 胜者决策 ---
    WINNER_DECIDED = "winner_decided"                     # 比较/推荐已决策
    WINNER_PENDING = "winner_pending"                     # 需要更多证据
    WINNER_NOT_DECIDABLE = "winner_not_decidable"         # 无法决策
```

```python
# 新增状态持久化到 SessionState
class SessionState(BaseModel):
    # ...现有字段...
    resolution_stage: ResolutionStage = ResolutionStage.CANDIDATE_SET_PENDING
    candidate_set: CandidateSet | None = None       # 当前候选集
    selected_target: ResolvedCandidate | None = None # 已选目标
    winner: ResolvedCandidate | None = None          # 胜者(比较/推荐)
    resolution_confidence: float = 0.0               # 总体置信度
```

---

## 9. 观测性缺口

| 缺口 | 位置 | 影响 |
|------|------|------|
| 无 `candidate_set` 过小告警 | `planning_subgraph.py` | 候选集为 1 时未记录日志说明 why |
| 无候选数直方图指标 | `observability/metrics.py` | 无法监控"多少场景候选数异常" |
| 无证据完备性评分 | `evidence_builder.py` | 无法量化"信息填充率" |
| 无维度级延迟指标 | 全链路 | 不知道哪个 facet 工具最慢 |
| 无 rewrite 成功率 | `llm_verbalizer.py` | 不知道 rewrite 是否有效 |
| `comparison_targets` 生命周期不透明 | `session_write.py:130` | 不清楚何时创建/何时消费 |

---

## 10. Phase 4 门控条件

### 必须满足 (HARD GATES)

- [x] **P0 修复**: `planning_subgraph.py` 的 `len(candidates) == 1` → `candidates` 守卫已修复
- [ ] **比较流回归测试全绿**: `test_comparison_flow.py` 24/24 通过
- [ ] **推荐流回归测试全绿**: `test_recommendation_flow.py` 17/17 通过
- [ ] **候选集解析测试全绿**: `test_target_resolve_candidate_set.py` 9/9 通过
- [ ] **`ranking_snapshot` 格式统一**: 三种证据路径输出一致 keyset

### 建议满足 (SOFT GATES)

- [ ] 状态分离: `ResolutionStage` 枚举引入且至少 CANDIDATE_SET / TARGET / WINNER 三级
- [ ] `generator.py` 中路径B 的旧比较矩阵解析已删除
- [ ] `verifier.py` 不再直接依赖 `ranking_snapshot`
- [ ] 观测性: 候选数直方图 + 证据完备性评分

### 未覆盖 (PHASE 4+)

- 置信度跟踪 (每候选、每维度)
- 结构化消歧工作流 (代替 `pending_clarification` 字符串)
- 完整的 provence chain (数据来源追溯)
- 显式状态机 (当前 LangGraph 隐式路由更灵活，暂不需要)

---

## 附录 A: 搜索模式结果摘要

| 搜索模式 | 匹配数 | 关键发现 |
|----------|--------|----------|
| `RESOLVED` (状态) | 20+ 匹配 | 4种语义重载，无区分 |
| `ranking_snapshot` (消费) | 38 匹配 | 分布在7个文件中，已基本从决策逻辑剥离 |
| `task_type == "comparison"` (分支) | 16 匹配 | 分布在7个文件中，4个是高危分支点 |
| `if len(candidates)` (守卫) | 2 匹配 | 1 个是回归根因 (planning_subgraph.py) |
| `open_status closed` (关店过滤) | 10 匹配 | 推荐过滤已实现，比较场景未过滤关店 |
| `CandidateStatus.RESOLVED` | 8 匹配 | 单定义+7消费点 |

## 附录 B: 测试运行详细日志

参见 `todo/phase0_3_acceptance_report.md` 的附录(2026-06-30 补充)。

## 附录 C: 代码注释引用的 PR 编号

| PR | 主题 | 状态 |
|----|------|------|
| P1 | 状态分离 + 证据协议 | 设计完成 |
| P2 | 候选人 + 评价器 | 已合并 |
| P3 | 验证器 + review | 部分合并 |
