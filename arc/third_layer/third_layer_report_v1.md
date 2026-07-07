# 第三层：回答层 — 架构报告

> 分析日期: 2026-07-05
> 范围: `response_subgraph` / `answer/` / `engine/workflows/*_workflow.py`
> 代码行数统计: ~4600 行（含 4 个独立工作流）

---

## 目录

1. [第三层职责边界](#1-第三层职责边界)
2. [模块总参与数据流](#2-模块总参与数据流)
3. [response_subgraph — 回答子图](#3-response_subgraph--回答子图)
4. [回答流水线详解](#4-回答流水线详解)
5. [独立工作流（Phase 6-8）](#5-独立工作流phase-6-8)
6. [回答验证引擎](#6-回答验证引擎)
7. [第三层路由判定总表](#7-第三层路由判定总表)
8. [关键设计决策与注意事项](#8-关键设计决策与注意事项)

---

## 1. 第三层职责边界

第三层（Layer 3）是用户请求在 LangGraph 中的最后一站，负责将第二层产出的证据转化为最终自然语言回答。

**做的事**：
- ✅ 从 DecisionPlan 构建 AnswerPlan（含回答类型、目标店、factual_points）
- ✅ LLM Verbalizer 生成自然语言回答（`answer/generator.py:generate_answer` → `llm_verbalizer.py:verbalize_decision_plan`）
- ✅ LLM 回答的忠实性校验（`answer/verifier.py:verify_answer`）
- ✅ 校验失败的自动重写（最多 `MAX_REWRITE_ATTEMPTS` 次）
- ✅ 确定性降级回答（`_compose_single_shop_response` — 模板方式）
- ✅ 澄清模式回答（`_h_clarify_response` / `clarification_fallback_workflow`）
- ✅ 安全降级回答（`_h_fallback_answer` — trusted_failure_message）
- ✅ 直接回答模式（`direct_response_workflow` — 打招呼/能力询问/拒绝）
- ✅ 确定性工具回答（`deterministic_tool_workflow` — 单店工具流）
- ✅ 探索规划回答（`exploration_planning_workflow` — 多目标行程安排）

**不做的事**：
- ❌ 不执行任何远程工具调用（独立工作流除外）
- ❌ 不规划目标或证据（只读 EvidencePack / DecisionPlan）
- ❌ 不持久化会话状态（那是 state_update_plan 的职责）
- ❌ 不做顶层意图分类或语义解析

---

## 2. 模块总参与数据流

```
                                ┌─ 来自第二层 ──────────────────────────┐
                                │  planning_route / execution_review_route │
                                │  response_mode                          │
                                │  DecisionPlan                           │
                                │  EvidencePack                           │
                                │  pending_clarification (可选)            │
                                └────────────────────┬───────────────────┘
                                                     │
                        ┌────────────────────────────┴────────────────────────────┐
                        │                    response_subgraph                     │
                        │                    h_response_subgraph()                 │
                        │                                                         │
                        │  ┌──────────┐  ┌───────────────┐  ┌──────────────────┐  │
                        │  │ direct / │  │ clarify        │  │ fallback         │  │
                        │  │ reject   │  │ mode           │  │ mode             │  │
                        │  │ 跳过回答  │  │ → clarify_     │  │ → fallback_     │  │
                        │  │ 生成      │  │   response()   │  │   answer()       │  │
                        │  └──────────┘  └───────────────┘  └──────────────────┘  │
                        │                                                         │
                        │  ┌────── 主回答流水线 (answer mode) ──────────────────┐ │
                        │  │                                                     │ │
                        │  │  answer_plan_build                                  │ │
                        │  │  → decision_to_answer_plan()                       │ │
                        │  │    ↓                                                │ │
                        │  │  answer_generate (LLM Verbalizer)                    │ │
                        │  │  → generate_answer() → verbalize_decision_plan()   │ │
                        │  │    ↓                                                │ │
                        │  │  answer_verify                                      │ │
                        │  │  → verify_answer() (规则 + 可选 LLM)                │ │
                        │  │    ↓                                                │ │
                        │  │  ┌──────────┐  ┌───────────┐                       │ │
                        │  │  │ pass →   │  │ fail →    │                       │ │
                        │  │  │ final_   │  │ rewrite() │ (≤ max 次)            │ │
                        │  │  │ response │  │ → 重生成   │                       │ │
                        │  │  └──────────┘  └───────────┘                       │ │
                        │  │    ↓              ↓ (超限)                           │ │
                        │  │  response_route=pass  fallback_answer()             │ │
                        │  └───────────────────────────────────────────────────  │ │
                        └────────────────────────┬────────────────────────────────┘
                                                 │
                          ┌──────────────────────┴──────────────────────┐
                          │              response_route                 │
                          │  pass / fallback_ready / clarify_ready      │
                          └──────────────────────┬──────────────────────┘
                                                 ▼
                                          state_update_plan
                                                 │
                                                END
```

### 独立工作流路径（通过 workflow_runner 进入）

```
workflow_runner 路由判定:
  workflow_callable == "planning_subgraph" → planning_subgraph (主路径)
  其他 → response_subgraph

独立工作流在 response_subgraph 之外独立执行:
  ┌─ direct_response_workflow      (直接回答 — chat/capability/unsafe/out_of_scope)
  ├─ deterministic_tool_workflow   (确定性工具 — shop_coupon/shop_status/shop_distance)
  ├─ clarification_fallback_workflow (澄清降级 — ambiguous/missing/reference_failed)
  └─ exploration_planning_workflow  (探索规划 — date_plan/local_trip_plan/coffee_then_dinner)

所有这些工作流在 handler() 内部生成 final_response 后，
由 workflow_runner 写回 state，然后路由到 response_subgraph，
再经 state_update_plan 持久化。
```

---

## 3. `response_subgraph` — 回答子图

**文件**: `engine/subgraphs/response_subgraph.py`（491 行）

**LangGraph 位置**: `execution_review_subgraph` / `planning_subgraph` / `understanding_subgraph` / `merge_clarification` / `workflow_runner` 都可能进入

### 3.1 `h_response_subgraph` 外层路由（第 128-174 行）

这是第三层的入口函数，根据 `response_mode` 走不同路径：

```python
def h_response_subgraph(state: GraphState) -> dict:
    response_mode = state.get("response_mode", "")

    # 路径 1: 直接/拒绝模式 → 跳过回答生成
    if response_mode in {"direct", "reject", "direct_response", "exploration_plan"}:
        → response_route = "pass"

    # 路径 2: 澄清模式 → 调用 clarify_response
    elif response_mode == "clarify" 或 pending_clarification 非空:
        if final_response 为空: _h_clarify_response()
        → response_route = "clarify_ready"

    # 路径 3: 降级模式 → 调用 fallback_answer
    elif response_mode == "fallback":
        if final_response 为空: _h_fallback_answer()
        → response_route = "fallback_ready"

    # 路径 4: 正常回答模式 (answer mode) → 回答流水线
    else:
        answer_plan_build → LLM 重试循环:
          while True:
            answer_generate → answer_verify
            if verify == "pass":
              final_response → response_route = "pass"
              break
            if rewrite_count >= rewrite_limit:
              fallback_answer → response_route = "fallback_ready"
              break
            rewrite → 继续循环
```

### 3.2 4 种路径的详细路由

| response_mode | 行为 | response_route | 下一节点 |
|---|---|---|---|
| `direct` / `reject` / `direct_response` / `exploration_plan` | 保持现有 final_response 不变，透传 | `pass` | state_update_plan |
| `clarify`（或 pending_clarification 非空）| 若无 final_response 则调用 `_h_clarify_response()` | `clarify_ready` | state_update_plan |
| `fallback` | 若无 final_response 则调用 `_h_fallback_answer()` | `fallback_ready` | state_update_plan |
| 其他（`""` / `"answer"` / `"tool_answer"` / `"comparison"`） | 启动完整回答流水线 | `pass` 或 `fallback_ready` | state_update_plan |

> ⚠️ **response_mode 值域说明**：该字段**没有统一的 Enum 定义**，分散在多个子图和路由函数中。已知出现的值包括：`"answer"`, `"reject"`, `"clarify"`, `"fallback"`, `"direct"`, `"direct_response"`, `"exploration_plan"`, `"tool_answer"`, `"comparison"`。前三层路由判定的跨子图兼容性依赖对这些字符串值的一致处理。

---

## 4. 回答流水线详解

### 4.1 `_h_answer_plan_build` — 回答计划构建（第 181-188 行）

| 项目 | 内容 |
|---|---|
| **输入** | `p2_decision_plan` (DecisionPlan 对象, GraphState 字段名) |
| **核心调用** | `decision_to_answer_plan(p2_dp, evidence_pack)` |
| **输出** | `AnswerPlan` (Pydantic 模型) |
| **写入** | `answer_plan` — 注意：读的字段名是 `p2_decision_plan`（含 `p2_` 前缀），写入的字段名是 `answer_plan`（无前缀） |

**AnswerPlan 核心字段**（`domain/schemas.py`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `answer_type` | str | `general` / `single_shop` / `comparison` / `recommendation` / `exploration_plan` / `clarification` / `error` |
| `target_shop_ids` | list[str] | 目标店铺 ID 列表 |
| `response_sections` | list | 回答分段 |
| `allowed_claims` | list[str] | 允许的声明（verifier 检查） |
| `required_claims` | list[str] | 必需的声明 |
| `must_mention_unknowns` | list[str] | 必须提及的未知项 |
| `forbidden_claims` | list[str] | 禁止的声明 |
| `selected_targets` | list[dict] | 选定目标的详情 |
| `omitted_targets` | list[dict] | 被省略的目标 |
| `overall_ranking` | list[dict] | 总体排名 |
| `best_for` | dict | 各维度优胜方 |
| `factual_points` | list[str] | 事实要点 |
| `uncertainty_notes` | list[str] | 不确定性说明 |
| `tone` | str | 语气（`neutral` / `friendly` / `informative` / `firm` / `helpful`） |

### 4.2 `_h_answer_generate` — 回答生成（第 191-265 行）

| 项目 | 内容 |
|---|---|
| **输入** | `answer_plan`, `evidence_pack`, `rewrite_count`, `previous_violations` |
| **核心调用** | `generate_answer(answer_plan, evidence_pack, metadata_out, rewrite_count, previous_violations, in_graph, conversation_continuity)` |
| **LLM 路径** | `verbalize_decision_plan(plan, llm_client, ...)` → LLM 生成自然语言 |
| **确定性兜底** | 如果 `answer_type == "single_shop"` 且 LLM 输出为空或含通用占位符 → `_compose_single_shop_response()` 模板方式构建 |
| **写入字段** | `draft_response` / `preview_text` / `answer_source` / `template_degraded` / `llm_verbalizer_called` / 各种 verifier 相关字段 |

**LLM Verbalizer 错误处理**（`answer/generator.py:605-700`）：

| 条件 | answer_source | 行为 |
|---|---|---|
| `config.ENABLE_LLM_VERBALIZER == False` | `llm_disabled` | 返回固定字符串"【LLM 服务未启用】" |
| LLM 调用成功 | `llm_verbalizer` / `llm_verbalizer_rewrite` | 返回 LLM 生成的回答 |
| LLM 失败（timeout/error） | 通过 metadata_out 传递错误 | 返回错误信息 |

#### `_compose_single_shop_response` — 确定性单店回答（第 44-125 行）

当 LLM 回答太差时触发的模板式兜底，从 `EvidencePack` 的 `facet_results` 提取各 facet 状态：

| facet | status | 输出文本 |
|---|---|---|
| `coupon` | `ok` + 有 titles | `"有券：{title1}、{title2}"` |
| | `ok` + 无 titles | `"有券"` |
| | `empty` | `"当前暂无可用优惠券"` |
| | other | `"优惠券情况暂时无法确认"` |
| `open_status` | `ok` + `open` | `"目前营业中"` |
| | `ok` + `closed` | `"当前未营业"` |
| | other | `"营业状态暂时无法确认"` |
| `distance` | `ok` + `distance_km` | `"距离为 X 公里，预计时间 Y 分钟"` |
| | other | `"距离暂时无法确认"` |

### 4.3 `_h_answer_verify` — 回答验证（第 268-336 行）

| 项目 | 内容 |
|---|---|
| **输入** | `draft_response`, `evidence_pack`, `task_type` |
| **核心调用** | `verify_answer(draft_response, evidence, task_type)` |
| **输出** | `verify_result` = `"pass"` / `"rewrite_needed"` |
| **写入字段** | 详见下方 |

**校验跳过条件**：
- `answer_source` 为 `template_fallback` / `llm_disabled` → 直接 pass（确定性回答或 LLM 未启用时不校验）
- `answer_source` 为 `trusted_failure_message`（来自 `_h_fallback_answer`）→ 在调用 `_h_answer_verify` 前已被 `h_response_subgraph` 的路由分支拦截，不进入 verify 路径
- `evidence` 为空 或 `draft_response` 为空 → 直接 pass

### 4.4 `_h_rewrite` — 重写（第 339-342 行）

```python
def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1     # 递增重写计数
    txt = state.get("draft_response", "")        # 保留当前草稿
    return {"draft_response": txt, "rewrite_count": rc}
```

重写后循环回到 `_h_answer_generate`，LLM 会收到 `previous_violations` 信息以修正问题。

### 4.5 `_h_final_response` — 最终回答（第 345-357 行）

```python
def _h_final_response(state: GraphState) -> dict:
    txt = state.get("draft_response", "")
    return {
        "final_response": txt,
        "preview_text": txt,
        "preview_policy_result": {"verified": True, "allowed": True, "reason": "verified"},
        ...
    }
```

### 4.6 `_h_clarify_response` — 澄清回答（第 375-419 行）

| 条件 | final_response |
|---|---|
| `pending_check_result` ∈ {expired/invalid/out_of_range} 且已有 final_response | 保留现有 |
| `pending_clarification` 非空 | `format_pending_prompt(pending)` 格式化澄清 |
| `resolve_shop_result.status` ∈ {AMBIGUOUS/LOW_CONFIDENCE} | `"店名有点模糊，请提供完整店名。"` |
| `error_message` 非空 | 直接用 error_message |
| 兜底 | `"请提供完整店名。"` |

### 4.7 `_h_fallback_answer` — 降级回答（第 422-491 行）

多层降级逻辑：

| 条件 | final_response | 场景 |
|---|---|---|
| `task_type` ∈ {single_shop_query, open_status_query} + shop_name + open_status=open | `"{shop_name}当前营业中。"` | 单店营业状态 |
| 同上 + open_status=closed | `"{shop_name}当前未营业。"` | 单店打烊状态 |
| `task_type` ∈ {single_shop_query, coupon_query} + shop_name + 有 coupon | `"{shop_name}有券，当前可用券包括：..."` | 单店优惠券 |
| `tool_result_set` 中 result_status=circuit_open | `"相关服务暂时不可用，请稍后再试。"` | 熔断 |
| result_status=failed | `"查询失败，建议稍后再试。"` | 失败 |
| result_status ∈ {unknown, unsupported} | `"暂时无法确认相关信息，请稍后再试。"` | 未知 |
| 兜底 | `"抱歉，暂时无法处理您的请求，请稍后再试。"` | 通用降级 |

---

## 5. 独立工作流（Phase 6-8）

### 5.1 `direct_response_workflow` — 直接回答工作流

**文件**: `engine/workflows/direct_response_workflow.py`（204 行）

**入口**: `workflow_runner` → `_route_workflow_runner` → `response_subgraph`

**用途**: 处理打招呼（chat）、能力询问（capability）、违规（unsafe）、越界（out_of_scope）、无效（invalid）等不需要工具调用的请求。

**策略表 `_DIRECT_RESPONSE_POLICY`**（第 19-56 行）：

| 策略键 | answer_type | tone | 回答文本示例 |
|---|---|---|---|
| `chat` | general | friendly | "你好，我可以帮你查商家营业状态、距离、优惠券、评价摘要和人均价格。" |
| `capability` | general | informative | "我可以帮你处理本地生活查询，比如营业状态、距离、优惠券、评价摘要和人均价格；暂不支持 RAG、交易、下单、支付、退款和预约。" |
| `unsafe` | error | firm | "出于安全考虑，我不能继续处理这个请求。" |
| `out_of_scope` | error | informative | "这个请求超出我当前可支持的本地生活能力。" |
| `invalid` | clarification | helpful | "我没太理解你的意思，可以换个更具体的说法吗？" |
| `forbidden` | error | firm | "这个请求包含当前不支持或受限的能力，我不能继续处理。" |

**分类函数** `_classify_direct_response`（第 63-85 行）：
1. 检查 workflow_reason 含 `forbidden` → forbidden
2. 检查原始文本含退款/交易/下单等 → forbidden
3. 检查 top_intent / task_type / primary_task → 对应策略
4. 检查"能做什么"类关键词 → capability
5. 检查"你好/嗨/您好" → chat
6. 兜底 → out_of_scope

### 5.2 `deterministic_tool_workflow` — 确定性工具工作流

**文件**: `engine/workflows/deterministic_tool_workflow.py`（~1200 行）

**入口**: `workflow_runner` → 路由到 `response_subgraph`

**用途**: 单店查询特定方面（营业状态、距离、优惠券、评价摘要、价格），在 response_subgraph 外独立完成整个执行周期（解析目标 → 调工具 → 构建证据 → 验证 → 生成回答）。

#### 完整流程

```
_run_deterministic_tool_workflow(state, decision):
  1. _resolve_single_shop_target(state) → 解析单店目标
     ├─ RESOLVED → target dict（shop_id + shop_name）
     ├─ AMBIGUOUS → PendingClarification → clarify 路径
     └─ NOT_FOUND → PendingClarification → clarify 路径

  2. _task_to_tool(task_type, semantic_frame) → 确定调什么工具

  3. _build_execution_plan(...) → 构建 ExecutionPlan
     ├─ 主工具（根据 task_type 映射）
     └─ extra_facets（从 semantic_frame.facets 提取，受预算控制）

  4. ToolBatchExecutor 执行工具调用

  5. build_evidence(...) → EvidencePack

  6. build_answer_plan(...) → AnswerPlan

  7. _tool_result_to_text(...) → 确定性文本回答

  8. verify_answer(answer_text, evidence) → 校验
     ├─ pass → 返回 success_patch
     └─ fail → 返回 clarify/fallback patch
```

**工具映射表 `_TASK_TOOL_MAP`**（第 41-47 行）：

| task_type | tool_name | facet |
|---|---|---|
| `shop_status` | `check_open_status` | `open_status` |
| `shop_distance` | `calculate_distance_km` | `distance` |
| `shop_coupon` | `get_coupon_list` | `coupon` |
| `shop_review_summary` | `get_shop_review_summary` | `review_summary` |
| `shop_price` | `get_shop_detail` | `price` |

**店铺解析** `_resolve_single_shop_target`（第 293-596 行）：
- **最高优先级**：`canonical_shop_entity`（GraphState 字段，由第一层 context_recovery 写入 `resolved_target`，或由 merge_clarification 的 restore 路径写入）——直接使用已解析结果，完全不执行新的店铺查询。
- 其次：`merchant_mentions` + `resolve_shop_entity` → 调用 `resolve_shop()` 执行实体解析。
- 兜底：`target_resolution` → 显式查询 `resolve_shop()` → `resolve_references()` → `current_shop`。
- 每一步的 AMBIGUOUS 状态都会创建 PendingClarification。
- 解析结果同时写入 `resolved_target`（主字段）和 `resolve_shop_result`（冗余兼容字段）。

**预算控制** `_budgeted_extra_facets`（第 759-768 行）：
- 检查 `facet_enrich_budget` 和 `deadline_remaining_ms`
- 限制额外 facet 数量

### 5.3 `clarification_fallback_workflow` — 澄清降级工作流

**文件**: `engine/workflows/clarification_fallback_workflow.py`（283 行）

**入口**: `workflow_runner` → 路由到 `response_subgraph`

**用途**: 当请求模糊、信息不足、置信度低或工具失败时，给出澄清/降级回答。

**策略表 `_CLARIFICATION_POLICY`**（第 20-77 行）：

| 策略键 | response_mode | 回答示例 |
|---|---|---|
| `ambiguous` | clarify | "我找到了多个可能的对象，请你补充更明确的店名或编号。" |
| `reference_failed` | clarify | "我暂时没法确认你指的是哪一家店，请提供完整店名。" |
| `missing_required_slot` | clarify | "还缺少一些关键信息，请补充后我再继续帮你处理。" |
| `low_confidence` | clarify | "我现在把握不够高，可以再补充一点信息吗？" |
| `no_result` | fallback | "暂时没有查到结果，你可以换个说法或补充更多信息再试。" |
| `tool_failure` | fallback | "相关服务暂时不可用，请稍后再试。" |
| `unsupported` | fallback | "这个能力暂时不支持，我可以继续帮你处理本地生活查询类问题。" |
| `forbidden` | fallback | "这个请求包含当前不支持或受限的能力，我不能继续处理。" |

**分类函数** `_classify_fallback`（第 87-109 行）：根据 `task_type`、`workflow_reason` 和 `raw_text` 选择策略。

### 5.4 `exploration_planning_workflow` — 探索规划工作流

**文件**: `engine/workflows/exploration_planning_workflow.py`（1114 行）

**入口**: `workflow_runner` → 路由到 `response_subgraph`

**用途**: 处理多子目标行程/活动规划（如"先喝咖啡再吃饭"、"周末约会安排"）。

#### 完整流程

```
run_exploration_planning_workflow(state, decision):
  1. _build_subgoals(state, decision) → 构建子目标列表
     ├─ 从 semantic_frame.exploration_stages 提取
     ├─ 从 TASK_TEMPLATES 模板提取（coffee_then_dinner / date_plan / family_activity_plan）
     ├─ 从原始文本分句提取（"然后/再/之后"分隔）
     ├─ 从 facet_names 提取
     └─ 兜底: 单子目标

  2. 检查: 子目标 > 3 → too_many_subgoals fallback
  3. 检查: 缺少位置 → missing_location fallback
  4. 检查: 无子目标 → too_many_subgoals fallback

  5. _tool_round_search() → 阶段 1: 对所有子目标并行 search_shops
  6. _tool_round_expand() → 阶段 2: 选第一个候选，调 detail/open_status/distance
     ├─ 受 budget_context 控制（tool_round_budget / facet_enrich_budget / deadline）
     └─ 含评价关键词时额外调 get_shop_review_summary

  7. build_evidence_pack_from_tool_results() → EvidencePack
     ├─ 检查 failed_facets → tool_failure fallback
     └─ 检查 answerable_facets 为空 → no_result fallback

  8. _build_exploration_plan() → ExplorationPlan

  9. build_answer_plan_from_evidence() → AnswerPlan

  10. _compose_final_response() → 确定性文本回答（不是 LLM）

  11. verify_answer_plan() → 校验
      ├─ pass → success_patch
      └─ fail → tool_failure fallback（带 verifier 错误信息）
```

**子目标构建优先级**（第 460-542 行）：

```
1. semantic_frame.exploration_stages（最优先，直接来自 LLM 解析）
2. 模板匹配（coffee_then_dinner / date_plan / family_activity_plan 等）
3. 文本分句（含"然后/再/之后"等时序标记的原始文本）
4. facet 派生
5. task_type 兜底
6. 失败 → too_many_subgoals
```

**子目标上限**：最多 3 个。

---

## 6. 回答验证引擎

### 6.1 `verify_answer()` — 入口

**文件**: `answer/verifier.py:625-664`

```python
def verify_answer(answer: str, evidence: dict, task_type: str) -> dict:
    # 1. 构建 mock AnswerPlan 和 DecisionPlan
    # 2. 运行 heuristic verify（快速规则校验）
    # 3. 判断是否需要 LLM verify
    # 4. 不需要 → _deterministic_verify()（纯规则）
    # 5. 需要 → B2MiniVerifier.verify()（LLM 校验）
    #    6. LLM 失败且 heuristic 通过 → 用 heuristic 结果兜底
```

**LLM 校验触发条件**（`_needs_llm_verification`, 第 219-232 行）：
- answer_type ∈ {comparison, exploration_plan, exploration}
- answer_type == recommendation 且有 comparison_matrix.rows
- selected_targets > 2
- evidence 中 `answer_verify_force_llm` 为 True

### 6.2 `_deterministic_verify()` — 确定性校验（第 498-622 行）

这是回答校验的核心，约 120 行的规则引擎。校验维度包括：

#### Coupon facet 规则

| evidence 状态 | 回答必须 | 违规检测 |
|---|---|---|
| `ok` | 含"有券"/"可用券"/"优惠券" | `coupon_status_missing_positive_claim` |
| `empty` | 不含"有券"/"有可用券"；含"暂无可用券"/"没有券" | `coupon_status_false_positive` / `coupon_status_missing_empty_notice` |
| `unknown` | 不含"有券"/"暂无可用券"/"没有优惠券"；含"暂时无法确认优惠券情况" | `unknown_claimed_as_empty_or_available` / `unsupported_coupon` / `unknown_needs_uncertain_notice` |
| `failed` | 含"获取优惠券信息失败"/"建议稍后再试" | `failed_needs_failure_notice` |
| `circuit_open` | 含"服务暂时不可用"/"稍后再试" | `circuit_open_needs_unavailable_notice` |

#### Open Status facet 规则

| evidence 状态 | 回答必须 | 违规检测 |
|---|---|---|
| `ok` + open | 含"营业中"/"正在营业" | `open_status_missing_open_claim` |
| `ok` + closed | 含"已打烊"/"已关门" | `open_status_missing_closed_claim` |
| `ok` + other | 含"营业状态未知" | `open_status_missing_unknown_notice` |
| `unknown` / `failed` | 不含"营业中"/"已打烊"；含"无法确认营业状态" | `open_status_false_positive` / `open_status_needs_uncertain_notice` |
| `circuit_open` | 含"服务暂时不可用" | `open_status_needs_unavailable_notice` |

#### Distance facet 规则

| evidence 状态 | 回答必须 | 违规检测 |
|---|---|---|
| `ok` + 有 distance_km | 含具体数值；直线距离时加"直线距离"；不含"预计/开车/步行/路线" | `distance_missing_numeric_claim` / `distance_missing_straight_line_claim` / `distance_false_eta_claim` |
| `unknown` / `failed` | 不含"很近"/"几分钟"等；含"无法确认距离" | `distance_false_positive` / `distance_needs_uncertain_notice` |
| `circuit_open` | 含"服务暂时不可用" | `distance_needs_unavailable_notice` |

#### Rating / Avg Price facet 规则

| facet | 条件 | 违规检测 |
|---|---|---|
| rating | evidence 有值且回答提到了评分 | 回答中必须含该数值 → `unsupported_rating` |
| avg_price | evidence 有值且回答提到了价格 | 回答中必须含该数值 → `unsupported_price` |

#### 对比回答校验（`_comparison_issues`, 第 400-474 行）

| 检查项 | 条件 | 违规 |
|---|---|---|
| 店名校验 | 回答中的店名不在 comparison_matrix 中 | `shop_mismatch:{store_name}` |
| 未知维度说更差 | comparison 中有未知维度且回答含"更差/不如/更弱" | `unknown_claimed_as_worse` |
| 未提供维度 winner | 回答提及优惠但 dimension_winners 无 coupon | `unprovided_dimension_winner` |
| 排名改变 | 回答中的顺序与 evidence 不一致 | `ranking_changed_by_llm` |
| unsupported winner | 优胜者不是排名第一 | `unsupported_comparison_winner` |

#### 通用校验

| 检查项 | 条件 | 违规 |
|---|---|---|
| 幻觉店名 | 回答含 evidence 中不存在的店名 | `hallucinated_shop_name` |
| 未知抑制 | 有 unknown_items 但回答声称"所有店都..." | `omitted_targets_violation` |
| 已知事实降级 | 已确认的事实被改写为"暂时无法确认" | `grounded_fact_downgraded_to_unknown` |

---

## 7. 第三层路由判定总表

### 7.1 `response_subgraph` 外层路由

**路由函数**: `_route_response_subgraph(state)` → `state.get("response_route")`

| response_route | 下一节点 |
|---|---|
| `pass`（正常回答、直接回答、探索规划） | **state_update_plan** |
| `fallback_ready`（降级回答） | **state_update_plan** |
| `clarify_ready`（澄清回答） | **state_update_plan** |

所有路径最终都汇聚到 `state_update_plan`。

### 7.2 回答流水线内部路由

| 步骤 | 条件 | 目的地 |
|---|---|---|
| answer_verify | `verify_result == "pass"` | `final_response` → response_route="pass" → state_update_plan |
| answer_verify | `verify_result == "rewrite_needed"` + `rewrite_count < rewrite_limit` | `rewrite` → `answer_generate` |
| answer_verify | `verify_result == "rewrite_needed"` + `rewrite_count >= rewrite_limit` | `fallback_answer` → response_route="fallback_ready" → state_update_plan |

### 7.3 rewrite 循环限值

| 配置项 | 实际值（`config.py:175`） | 说明 |
|---|---|---|
| `MAX_REWRITE_ATTEMPTS` | **2** | 配置的最大重写尝试次数 |
| `_get_rewrite_limit()` | `max(1, 2-1)` = **1** | **实际有效重写次数**（见 `_routes.py:278-279`） |

**生效逻辑**（`response_subgraph.py:156-157`）：
```python
rewrite_limit = max(0, min(int(_GRAPH_REWRITE_LIMIT or 0), int(rewrite_budget)))
```
实际限值 = `min(有效重写次数, 预算剩余)`。超过后不走重写，直接进入 `_h_fallback_answer` → `response_route="fallback_ready"`。

> **含义**：配置 `MAX_REWRITE_ATTEMPTS = 2` 意味着只有 **1 次**实际重写机会（原始生成 + 1 次重试）。如果希望允许更多重试，需要增大此值。

### 7.4 独立工作流 → response_subgraph 路由

| workflow_name | workflow_callable | 实际入口 | 产出 final_response 的方式 |
|---|---|---|---|
| `discovery_decision` | `planning_subgraph` | **planning_subgraph**（主路径） | LLM Verbalizer（第二层 → 第三层回答流水线） |
| `direct_response` | `response_subgraph` | **response_subgraph** | 确定性模板（`direct_response_workflow`） |
| `deterministic_tool` | `response_subgraph` | **response_subgraph** | `_tool_result_to_text()` 确定性生成（`deterministic_tool_workflow`） |
| `clarification_fallback` | `response_subgraph` | **response_subgraph** | `_CLARIFICATION_POLICY` 确定性模板 |
| `exploration_planning` | `response_subgraph` | **response_subgraph** | `_compose_final_response()` 确定性组合（`exploration_planning_workflow`） |

---

## 8. 关键设计决策与注意事项

### 8.1 LLM Verbalizer 是唯一的自然语言生成路径

`generate_answer()` 只用 LLM verbalizer。模板式回答仅作兜底（`_compose_single_shop_response`）。如果 LLM 不可用（`config.ENABLE_LLM_VERBALIZER == False`），返回固定占位符而不降级到模板。

### 8.2 回答验证是两层架构

1. **确定性规则**（`_deterministic_verify`）：覆盖 coupon / open_status / distance / rating / price / comparison / hallucination，约 120 行规则代码
2. **LLM 校验**（`B2MiniVerifier`）：仅用于 comparison 和 exploration_plan 等复杂类型，LLM 失败时用 heuristic 结果兜底

### 8.3 独立工作流是"自包含"的执行单元

`deterministic_tool_workflow` / `exploration_planning_workflow` 不依赖第二层的主路径规划。它们在 `workflow_runner` 调度后自行完成：
- 目标解析 → 工具调用 → 证据构建 → 回答生成 → 校验

这种设计让简单查询（单店营业状态）跳过整个 Plan→Execute→Review 主路径，大幅降低延迟和 token 消耗。

### 8.4 重写循环有预算和次数双重控制

`h_response_subgraph` 中：
```python
rewrite_budget = budget.remaining("rewrite_budget")   # 预算控制
rewrite_limit = max(0, min(rewrite_limit, rewrite_budget))  # 取两者较小值
```

超过限制后走 `fallback_answer`，不会无限循环。

### 8.5 确定性单店回答是 LLM 回答失败的保险

`_compose_single_shop_response()` 在以下条件触发：
- `answer_type == "single_shop"`
- LLM 输出为空或含这 5 个通用占位符之一：
  - "我会优先参考当前结果来回答。"
  - "当前信息还不够完整..."
  - "这项信息我已经按当前查询结果整理好了。"
  - "抱歉，暂时无法处理您的请求..."
  - "当前已知信息还不够完整..."

### 8.6 探索规划有硬编码模板

`_TASK_TEMPLATES` 包含 5 种预定义行程模板，每个模板定义 2-3 个子目标的 `kind`/`query`/`temporal_relation`：

| 模板 | 子目标 |
|---|---|
| `coffee_then_dinner` | 咖啡店 → 餐厅 |
| `date_plan` | 咖啡/甜品 → 约会晚餐 → 公园散步 |
| `family_activity_plan` | 亲子餐厅 → 儿童乐园 → 公园/甜品 |
| `local_trip_plan` | 景点 → 餐厅 → 咖啡店 |
| `eat_and_play_plan` | 餐厅 → 游玩地点 → 咖啡甜品 |

### 8.7 对比回答校验有严格的顺序检查

`_comparison_issues()` 检查：
- 如果用户说"更好/更优/领先"，但提到的第一个店不是排名第一 → `ranking_changed_by_llm`
- 如果用户用了"在前/在后/排在"等顺序词，回答顺序与 evidence 不一致 → `ranking_changed_by_llm`
- 如果用户说"更推荐/更好"，但最近的店名不是排名第一 → `unsupported_comparison_winner`

### 8.8 项目 AGENTS.md 约束对照

| 约束 | 第三层落实情况 |
|---|---|
| 禁止 Mock 数据 | `deterministic_tool_workflow` 和 `response_subgraph` 都基于真实的工具结果和证据；`final_response` 来自 LLM verbalizer 或确定性模板，不做编造 |
| 回答必须基于 EvidencePack | `_h_answer_generate` 只读 `evidence_pack`；`verify_answer` 全职校验回答的每个事实是否在 evidence 中 |
| 不允许 LLM 直接调工具 | 所有工具调用在 `deterministic_tool_workflow` 和 `execution_review_subgraph` 中完成，通过 `dispatch_tool_call`（Gateway），回答层不调工具 |
| 不允许工具层决定最终回答 | 工具层产出 ToolResult，evidence 层产出 EvidencePack，回答层产出自然语言，职责严格分离 |
| 不允许 Mock | `generate_answer` 使用的 LLM verbalizer 和 verifier 都是真实调用；确定性 fallback 基于真实 facet_results |
