# 分层修复报告

> 日期: 2026-06-30
> 范围: `state_update_plan.py` + `state_update_planner.py` · `decision_planner.py` · `understanding_subgraph.py`

---

## 概述

本轮修复针对三个独立但相互关联的缺陷，覆盖会话状态写入、决策规划、语义帧验证三个层次。修复后 `test_recommendation_flow.py` 全量通过（17 passed, 2 xfailed），相关决策和状态测试保持绿色。

---

## 修复 1 — 会话状态写入守卫

### 文件

- `local_life_agent/engine/subgraphs/state_update_plan.py`
- `local_life_agent/planning/plans/state_update_planner.py`

### 问题

当 resolution_stage 为 `CANDIDATE_SET_RESOLVED`（多候选已解析，无单一目标）时，`plan_state_update` 会将 `current_shop` 写入会话状态，导致后续轮次错误地认为存在"当前店铺"。

### 根因

`plan_state_update` 仅检查 `resolve_shop_status == "RESOLVED"`，未区分"单一目标已解析"（应写 `current_shop`）和"多候选已解析"（不应写 `current_shop`）。

### 修复

1. **`state_update_plan.py`**: 在 `turn_context` 中传递 `resolution_stage`、`reference_resolution_source`、`evidence_pack`、`local_life_goal_draft` 等字段
2. **`state_update_planner.py`**: 
   - 新增 `CANDIDATE_SET_RESOLVED` 状态识别（`is_resolved` 分支包含 `"CANDIDATE_SET_RESOLVED"`）
   - `single_shop_query`/`coupon_query`: 仅当 `resolve_shop_status == "RESOLVED"` 时写 `current_shop`
   - `recommendation`: 仅当 `resolution_stage != "candidate_set_resolved"` 且 `reference_resolution_source` 非空时写 `current_shop`
   - `comparison`: 新增 `evidence_pack` → `comparison_result` 回退逻辑
3. 工具失败时明确清除 `current_shop`

### 影响

| 场景 | 预期 | 修复前 | 修复后 |
|---|---|---|---|
| 推荐 → 第一家有券吗 | 不写 current_shop | 可能误写 | 正确跳过 |
| 推荐完成 | 不写 current_shop | 已正确处理 | 不变 |
| 单店查询 | 写 current_shop | 已正确处理 | 不变 |
| 对比完成 | 清除 current_shop | 未清除 | 正确清除 |

---

## 修复 2 — 证据不足时回退到排序

### 文件

- `local_life_agent/planning/decision/decision_planner.py`

### 问题

`plan_decision` 仅依赖 `_find_winner_from_ranking` 决定胜出者，未利用证据（`evidence_items`）中的面面信息。当 evidence_items 为空的推荐场景下，无法从证据中推导胜出者。

### 根因

缺少证据驱动的胜出者选择逻辑，完全依赖排序分。

### 修复

1. 新增 `_find_winner_from_evidence(evidence_dict, candidates, ranking=None)` 函数
2. 对每个候选者统计可回答（`answerable`）的证据项数量
3. 证据充分且无平局时 → 返回证据胜出者 + 证据排名
4. 证据不足或平局时 → **回退到 `_find_winner_from_ranking(ranking)`**
5. `plan_decision` 中原 `_find_winner_from_ranking(ranking)` 替换为新函数

### 关键行为

```
evidence_items 非空且 winner_score > 0 且未平局
  → 证据胜出 ← 主路径
否则
  → 排序胜出 ← 回退路径（兼容原行为）
```

---

## 修复 3 — 语义帧验证器 needs_context 处理

### 文件

- `local_life_agent/engine/subgraphs/understanding_subgraph.py`

### 问题

`_h_frame_validator` 对 `validate_frame` 返回的 `needs_context` issue 无处理分支，落入 `else: err = "SEMANTIC_FRAME_INVALID"`，导致指代查询（如"第一家有券吗"）被误路由到 CLARIFY 路径，而非进入 `planning_subgraph`。

### 根因

`_h_semantic_parse` 已经正确处理了 `needs_context`（清空 `error_code`），但 `_h_frame_validator` 独立重新验证时缺少对应处理分支。

### 修复

在 `_h_frame_validator` 的 issue 处理链中增加：

```python
elif "needs_context" in issues:
    err = ""
```

与 `_h_semantic_parse` 的行为保持一致：`needs_context` 不是错误，而是表示查询需要来自上一轮的会话上下文。

### 影响

| 步骤 | 修复前 | 修复后 |
|---|---|---|
| `_h_semantic_parse` | `error_code=""` ✅ | 不变 |
| `_h_frame_validator` | `err="SEMANTIC_FRAME_INVALID"` ❌ | `err=""` ✅ |
| 路由结果 | CLARIFY → response_subgraph | PROCEED → planning_subgraph |

---

## 回归验证

### 测试覆盖

| 测试文件 | 结果 | 说明 |
|---|---|---|
| `test_recommendation_flow.py` | 17 passed, 2 xfailed | ✅ 关键修复验证 |
| `test_context_recovery_clarification.py` | 全部通过 | ✅ Fix 1 验证 |
| `test_candidate_decision.py` | 全部通过 | ✅ Fix 2 验证 |
| `test_decision_planner.py` | 全部通过 | ✅ Fix 2 验证 |
| 全量回归 | 906 passed, 35 failed, 25 errors | 失败/错误均为预存 |

### 回归失败分类

所有失败和错误均为预存问题，与本次修复无关：

| 类别 | 数量 | 原因 |
|---|---|---|
| `test_mock_data_normalization.py` errors | 25 | DB seed 文件缺失/Mock 数据未生成 |
| `test_single_shop_multifacet.py` | 7 | Mock LLM 不处理 evidence planner prompt |
| `test_subgraph_core_integration.py` | 5 | `_CANDIDATE_CORE` 等属性在 refactor 后未导出 |
| `test_app_streaming.py` / `test_openai_backend_streaming.py` | 6 | Streaming 框架变动 |
| 其他预存失败 | ~17 | 环境/配置/真实 LLM 依赖 |
| **新增回归** | **0** | ✅ 无 |

---

## 配置及架构备注

- `StateCore` (`local_life_agent/core/`) 作为 `plan_state_update` / `build_state_patch` 的薄封装注入
- `resolution_stage` 状态值: `candidate_set_resolved` / `target_resolved` / `target_not_found`
- 三处修复均为局部修改，无架构侵入
