# 全面根除硬编码意图 + 清理冗余字段

## TL;DR

> **核心目标**：让 `facet_planner` 的 LLM 输出真正驱动 RAG 和 ToolCall 执行，消除下游所有基于 intent 字符串的硬编码次路由。
>
> **关键手段**：新增 `RoutingDecision.facet_plan` 字段承载 facet_planner 输出，下游直接读取 FacetPlan 的 `source`/`tool_name`/`name`/`preferred_roles`，不再重新解析 intent。
>
> **预计工作量**：Large（10-12 个任务，分 3 轮实施）

---

## Context

### 当前问题

facet_planner 的 LLM 输出经过 `build_routing_decision_from_facet_planner()` 写入 `RoutingDecision`，但下游的 RAG 和 ToolCall 模块并没有直接读取 facet_plan 来决定行为，而是在自己的代码中**重新解析 intent 字符串**做二次路由。

**具体表现**：

```
facet_planner (LLM) → FacetPlan {name: "coupon", source: "tool", tool_name: "get_coupon_list"}
  → RoutingDecision { intent.name: "local_life", should_call_tool: true }
    → tools/orchestrator_components.py
      → _resolve_planner_intent() 通过 4 张硬编码表重查工具
        _LOCAL_LIFE_CANONICAL_INTENTS  ×
        _LOCAL_LIFE_GENERIC_ACTION_MAP  ×
        _LOCAL_LIFE_TOOL_NAMES          ×
        _LEGACY_INTENT_MAP              ×
      → 匹配失败 → 降级或返回 None
```

同理 RAG 侧：

```
facet_planner (LLM) → FacetPlan {name: "taste", source: "rag", preferred_roles: ["merchant_review_summary"]}
  → rag/retrieval/reranker.py
    → if intent in ("compare", "recommend"):   ← intent 串不匹配
    → elif intent in ("booking", "coupon", ...): ← 也不匹配
    → 走默认权重，facet_planner 的规划被浪费
```

### 摸底结果摘要

**ToolCall 侧硬编码点（4 张表 + 3 层查链）：**

| 位置 | 硬编码内容 | 用途 |
|---|---|---|
| `tools/planner.py:24-51` | `DEFAULT_INTENT_TOOL_MAP` (20+ 映射) | intent→工具名 |
| `tools/orchestrator_components.py:183-206` | `_LOCAL_LIFE_CANONICAL_INTENTS` (20 个意图名集合) | 合法意图白名单 |
| `tools/orchestrator_components.py:208-230` | `_LOCAL_LIFE_GENERIC_ACTION_MAP` (20+ 映射) | 动作→意图规范化 |
| `tools/orchestrator_components.py:247-252` | `_APPROVAL_REQUIRED_TOOLS` (4 个工具名) | 审批白名单 |
| `tools/orchestrator_components.py:261-263` | `_LEGACY_INTENT_MAP` | 遗留兼容 |
| `tools/orchestrator_components.py:293-350` | `_resolve_planner_intent()` | 3 层 intent 查表链 |
| `tools/orchestrator_components.py:704,743,749` | `if resolved_intent in _LOCAL_LIFE_TOOL_NAMES` | 工具选择降级 |
| `tools/planner.py:72-74` | `self._intent_tool_map.get(intent_key)` | 意图→工具映射 |

**RAG 侧硬编码点（5 处独立 intent 分支）：**

| 位置 | 硬编码内容 | 用途 |
|---|---|---|
| `rag/rewrite.py:17-22` | `INTENT_CHUNK_MAP` (4 个 intent→chunk_type) | 决定检索 chunk 类型 |
| `rag/rewrite.py:459-461` | `_preferred_chunk_types()` 查 `INTENT_CHUNK_MAP` | 重写阶段 |
| `rag/rewrite_guard.py:47-53` | `_INTENT_DRIFT_PATTERNS` (5 组关键词) | 检测 intent drift |
| `rag/evidence.py:116-123` | `if intent in ("compare", "recommend")` | 证据治理策略 |
| `rag/retrieval/reranker.py:317-333` | `if intent in ("compare","recommend","follow_up","detail","explain","booking","coupon","navigation")` | 检索权重调整 |
| `rag/heuristics.py:172-179` | `needs_tool = intent in {IntentType.RECOMMEND}` | 旧路径意图决策 |

**RoutingDecision 冗余字段：**

| 字段 | 设置者 | 消费者 | 状态 |
|---|---|---|---|
| `intent.name` | facet_planner → 死值 `"local_life"` | 下游重解析 | 冗余 |
| `intent.confidence` | facet_planner 设 0.85/0.70 | 下游不消费 | 冗余 |
| `intent.allowed_routes` | facet_planner 设 | 少数旧路径消费 | 可精简 |
| `intent.forbidden_routes` | facet_planner 设 | 少数旧路径消费 | 可精简 |
| `intent.required_slots` | facet_planner 未设置 | 旧路径用 | 可精简 |
| `intent.missing_slots` | facet_planner 少设 | 旧路径用 | 可精简 |
| `route_candidate` | facet_planner 设 | 仅调试用 | 可精简 |
| `execution_mode` | facet_planner 设死 `"simple"` | 仅旧路径 | 冗余 |
| `tool_candidates` | facet_planner 设空 | 下游重解析 | 冗余 |
| `preferred_chunk_roles` | facet_planner 设空 | 旧路径用 | 冗余 |
| `extra["required_facets"]` | facet_planner 设 | 旧 phase1 路径 | 冗余（被 FacetPlan 替代） |
| `extra["optional_facets"]` | facet_planner 设 | 旧 path | 冗余 |
| `extra["facet_plan_raw"]` | facet_planner 设 | 仅调试 | 冗余（被 facet_plan 字段替代） |
| `extra["top_level_intent"]` | facet_planner 设 | 无人消费 | 冗余 |

---

## Work Objectives

### Core Objective
让 `facet_planner` 输出的 `FacetPlan` 列表直接驱动 RAG 检索和 ToolCall 执行，消除所有基于 intent 字符串的二次路由硬编码，同时清理不再需要的冗余字段。

### Concrete Deliverables
- `RoutingDecision` 新增 `facet_plan` 字段
- `build_routing_decision_from_facet_planner()` 正确填充 `facet_plan`
- `ToolPlanner` 新增 `plan_from_facets()` 方法，直接消费 FacetPlan
- `ToolOrchestrator.plan()` 新增 `facet_plans` 参数分支
- `synthesize_retrieval_plan()` 从 `routing.facet_plan` 读取 rag 面
- RAG rewrite/evidence/reranker 接受 FacetPlan 替代 intent
- 清理 RoutingDecision 和 extra 中的冗余字段

### Must Have
- 所有改动保持旧路径 100% 向后兼容
- facet_planner 路径不再依赖任何 intent 字符串做路由
- 每个修改有对应的测试覆盖

### Must NOT Have
- 不改动旧路径（phase1_intent / heuristics / FastDecision）的工作方式
- 不改动 FacetPlan 和 FacetPlannerOutput 的 schema
- 不在本次重构中引入新功能或新意图

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: YES (tests-after)
- **Framework**: pytest
- **验证方式**：每个任务后跑现存测试 + 新增针对 facet_plan 路径的测试

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (契约层 - 新增 facet_plan 穿透路径):
├── Task 1: RoutingDecision 新增 facet_plan 字段 + build_routing_decision 填充
├── Task 2: ToolPlanner 新增 plan_from_facets() 方法
├── Task 3: synthesize_retrieval_plan() 读取 facet_plan
├── Task 4: synthesize_tool_selection() 读取 facet_plan
├── Task 5: ToolOrchestrator.plan() 新增 facet_plans 参数分支
├── Task 6: RAG rewrite 接受 FacetPlan 替代 intent

Wave 2 (执行层 - 消除各模块内部硬编码):
├── Task 7: rag/evidence.py 消除 intent 硬编码
├── Task 8: rag/retrieval/reranker.py 消除 intent 硬编码
├── Task 9: rag/rewrite_guard.py 消除 intent 硬编码
├── Task 10: 清理 RoutingDecision 冗余字段
├── Task 11: 清理 build_routing_decision extra 冗余字段

Wave FINAL:
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Run full test suite
├── Task F3: Scope fidelity check
```

---

## TODOs

- [ ] 1. RoutingDecision 新增 facet_plan 字段 + build_routing_decision 填充

  **What to do**:
  - 在 `domain/contracts.py` 的 `RoutingDecision` 类中新增字段：
    ```python
    facet_plan: list[FacetPlan] = Field(default_factory=list)
    ```
  - 在 `application/router/facet_planner.py` 的 `build_routing_decision_from_facet_planner()` 中，将 `output.facets`（即 `list[FacetPlan]`）写入 `RoutingDecision.facet_plan`
  - 当前 `extra["facet_plan_raw"]` 保留兼容，但标记注释为 DEPRECATED

  **Must NOT do**:
  - 不改动 FacetPlan schema
  - 不改动旧路径（load_context 中 facet_planner 路由的终端分支）

  **Parallelization**:
  - Can Run In Parallel: NO（基础契约改动）
  - Blocks: Task 2-11

  **Acceptance Criteria**:
  - RoutingDecision 实例可以正确携带 facet_plan 字段
  - build_routing_decision_from_facet_planner 返回的 RoutingDecision.facet_plan == output.facets

---



- [ ] 2. ToolPlanner 新增 plan_from_facets() 方法

  **What to do**:
  - 在 `tools/planner.py` 的 `ToolPlanner` 类中新增方法：
    ```python
    def plan_from_facets(
        self,
        facet_plans: list[FacetPlan],
        slots: dict[str, object] | None = None,
    ) -> list[ToolSelection]:
        """直接从 FacetPlan 列表生成 ToolSelection，绕过 intent 映射。

        只有当 facet.source == "tool" 且 facet.tool_name 非空时才生成。
        不再依赖 DEFAULT_INTENT_TOOL_MAP。
        """
        selections: list[ToolSelection] = []
        slot_data = dict(slots or {})
        for fp in facet_plans:
            if fp.source != "tool" or not fp.tool_name:
                continue
            input_payload = dict(slot_data)
            input_payload.pop("tool_name", None)
            input_payload.pop("tool_input", None)
            selections.append(ToolSelection(
                tool_name=fp.tool_name,
                should_execute=True,
                input_payload=input_payload,
                reason=f"facet_plan:{fp.name}",
            ))
        return selections
    ```
  - 需要新增 import: `from ..domain.contracts import FacetPlan, ToolSelection`
  - 旧 `plan()` 方法不动，保持向后兼容

  **Must NOT do**:
  - 不改动 DEFAULT_INTENT_TOOL_MAP
  - 不删除旧的 plan() 方法

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 1 (with Task 3, 4, 5, 6)
  - Blocks: Task 5
  - Blocked By: Task 1

---

- [ ] 3. synthesize_retrieval_plan() 读取 facet_plan

  **What to do**:
  - 在 `application/routing_signals/base.py` 的 `synthesize_retrieval_plan()` 中，**在函数开头新增检查**：
    ```python
    # 如果 routing.facet_plan 非空，直接从 facet_plan 推导检索参数
    if routing.facet_plan:
        rag_facets = [fp for fp in routing.facet_plan if fp.source in ("rag", "recommendation")]
        if rag_facets:
            preferred_roles = list(dict.fromkeys(
                role for fp in rag_facets for role in (fp.preferred_roles or [])
            ))
            facet_names = [fp.name for fp in rag_facets if fp.required]
            retrieval_filters = {
                "domain": routing.domain if hasattr(routing, "domain") else "local_life",
                "is_active": True,
                "is_latest": True,
            }
            # 沿用后面 BusinessObjectResolver 的解析逻辑
            # 但 preferred_chunk_roles 和检索参数直接来自 FacetPlan
            ...
            return RetrievalPlan(
                semantic_query=semantic_query,
                keyword_query=semantic_query,
                retrieval_filters=retrieval_filters,
                preferred_chunk_roles=preferred_roles,
                strategy="dense+sparse+metadata->rrf->rerank->evidence",
                source="facet_planner",
            )
    ```
  - 具体实现：当 `routing.facet_plan` 非空且有 `source="rag"` 的 facet 时：
    - `preferred_chunk_roles` 从所有 rag facet 的 `preferred_roles` 合并
    - `retrieval_filters` 从 rag facet 的 `name` 推导（如 "shop_detail" 需要 shop_id 过滤）
    - 后续 BusinessObjectResolver 逻辑保持不变
    - 跳过原有的 intent 推导 preferred_chunk_roles 逻辑

  **Must NOT do**:
  - 不改动旧路径（当 routing.facet_plan 为空时走原有逻辑）

  **Parallelization**:
  - Can Run In Parallel: YES (与 Task 2, 4, 5, 6 并行)
  - Blocked By: Task 1

---

- [ ] 4. synthesize_tool_selection() 读取 facet_plan

  **What to do**:
  - 在 `application/routing_signals/base.py` 中新增函数 `synthesize_tool_selection()`（如果不存在）或增强现有逻辑
  - 当 `routing.facet_plan` 非空时，提取 `source="tool"` 的 FacetPlan，直接生成 `list[ToolSelection]`
  - 此函数的输出直接用于 workflow 中的工具执行阶段

  **Must NOT do**:
  - 不改动旧路径

  **Parallelization**:
  - Can Run In Parallel: YES
  - Blocked By: Task 1

---

- [ ] 5. ToolOrchestrator.plan() 新增 facet_plans 参数分支

  **What to do**:
  - 在 `tools/orchestrator_components.py` 的 `ToolOrchestrator.plan()` 方法中新增可选参数：
    ```python
    def plan(
        self,
        request: ToolPlanningRequest,
        facet_plans: list[FacetPlan] | None = None,
    ) -> ToolSelection:
    ```
  - 当 `facet_plans` 非空时：
    - 调用 `self.planner.plan_from_facets(facet_plans, request.slots)`
    - 如果返回的 selections 非空，取第一个（或合并多个）作为最终 ToolSelection
    - **完全跳过 `_resolve_planner_intent()` 及其全套硬编码映射**
    - 但仍然对返回的 result 应用 approval 规则（`_APPROVAL_REQUIRED_TOOLS`）
  - 当 `facet_plans` 为 None 时，走原逻辑不变

  **注意**：`_APPROVAL_REQUIRED_TOOLS` 是安全相关的审批白名单，即使 facet_plans 路径也不应绕过。所以保留：
    ```python
    approval_required = selection.tool_name in _APPROVAL_REQUIRED_TOOLS
    ```
  但这是安全规则不是路由规则，属于合法保留。

  **Parallelization**:
  - Can Run In Parallel: NO（依赖于 Task 2）
  - Blocked By: Task 2

---

- [ ] 6. RAG rewrite 接受 FacetPlan 替代 intent

  **What to do**:
  - 在 `rag/rewrite.py` 的 `QueryRewriteContext` 中新增可选字段：
    ```python
    facet_plan: list[FacetPlan] | None = None
    ```
  - 修改 `_preferred_chunk_types()` 方法：当 `self.facet_plan` 非空时，不查 `INTENT_CHUNK_MAP`，而是从 rag facet 的 preferred_roles 映射：
    ```python
    def _preferred_chunk_types(self, context: QueryRewriteContext) -> tuple[str, ...]:
        # 新路径：从 facet_plan 推导
        if context.facet_plan:
            rag_facets = [fp for fp in context.facet_plan if fp.source in ("rag", "recommendation")]
            if rag_facets:
                # 从 preferred_roles 映射到 chunk_types
                role_to_chunk = {
                    "merchant_review_summary": "review",
                    "merchant_profile": "profile",
                    "merchant_scene_fit": "scene",
                    "merchant_pitfall_summary": "pitfall",
                    "package_description": "package",
                }
                types = set()
                for fp in rag_facets:
                    for role in (fp.preferred_roles or []):
                        if role in role_to_chunk:
                            types.add(role_to_chunk[role])
                if types:
                    return tuple(types)
        # 旧路径：查 INTENT_CHUNK_MAP
        intent = (context.intent or "").strip().lower()
        return INTENT_CHUNK_MAP.get(intent, INTENT_CHUNK_MAP["explain"])
    ```

  **Import needed**: `from ..domain.contracts import FacetPlan`

  **Parallelization**:
  - Can Run In Parallel: YES (与 Task 2, 3, 4 并行)
  - Blocked By: Task 1

---

- [ ] 7. rag/evidence.py 消除 intent 硬编码

  **What to do**:
  - 在 `rag/evidence.py` 的 `QueryComplexityProfile.profile()` 方法中：
    - 新增参数 `facet_plans: list[FacetPlan] | None = None`
    - 在 `intent in ("compare", "recommend")` 分支之前，新增 facet_plan 检查：
    ```python
    # facet_plan 路径：从面名推导 answer_type
    if facet_plans:
        facet_names = {fp.name for fp in facet_plans if fp.required}
        if "compare" in facet_names or "comparison" in facet_names:
            complexity_level = "complex"
            answer_type = "comparison"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(name in facet_names for name in ("recommendation", "scene_fit")):
            complexity_level = "complex"
            answer_type = "recommendation"
            ...
        # 如果 facet_plan 推导出了结果，直接 return，跳过 intent 分支
    ```
  - 当 `facet_plans` 参数提供且推导出结果时，跳过 `if intent in (...)` 分支
  - 当 `facet_plans` 为 None 时，走原逻辑

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 2
  - Blocked By: Task 1

---

- [ ] 8. rag/retrieval/reranker.py 消除 intent 硬编码

  **What to do**:
  - 在 `rag/retrieval/reranker.py` 的权重调整方法中：
    - 新增参数 `facet_plans: list[FacetPlan] | None = None`
    - 在 `intent in (...)` 检查之前，新增 facet_plan 检查：
    ```python
    def _build_intent_aware_weights(self, route_hits, *, query_intent=None, query_slots=None, facet_plans=None):
        # facet_plan 路径
        if facet_plans:
            facet_names = {fp.name for fp in facet_plans if fp.required}
            if "compare" in facet_names:
                weights["dense"] *= 1.2
                weights["metadata"] *= 0.8
            elif "coupon" in facet_names or "open_status" in facet_names:
                weights["metadata"] *= 1.3
                weights["sparse"] *= 1.1
            elif any(name in facet_names for name in ("taste", "environment", "service", "shop_detail")):
                weights["dense"] *= 1.15
            return weights
        
        # 旧路径
        intent = (query_intent or "").lower()
        ...
    ```
  - 新路径下从 FacetPlan 的 `name` 字段推断检索策略，不再依赖 intent 字符串

  **Parallelization**:
  - Can Run In Parallel: YES
  - Blocked By: Task 1

---

- [ ] 9. rag/rewrite_guard.py 消除 intent 硬编码

  **What to do**:
  - 在 `rag/rewrite_guard.py` 的 `_detect_intent_drift()` 方法中：
    - 新增参数 `facet_plans: list[FacetPlan] | None = None`
    - 当 facet_plans 提供时，改用 facet 的 name 做粗略的意图一致性检查，不依赖 `_INTENT_DRIFT_PATTERNS`
    - 简化：如果 `facet_plans` 非空，跳过意图漂移检测（因为 facet 是 LLM 直接生成的，不需要防漂移）
    ```python
    def _detect_intent_drift(self, original, rewrite, intent=None, *, facet_plans=None):
        if facet_plans:
            # facet_planner 路径：LLM 直接输出 facet，不需要 intent drift 检测
            return False
        # 旧路径
        ...
    ```
  - `validate_rewrite()` 方法新增 `facet_plans` 参数并透传给 `_detect_intent_drift`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Blocked By: Task 1

---

- [ ] 10. 清理 RoutingDecision 冗余字段

  **What to do**:
  - 在 `domain/contracts.py` 中，对 `RoutingDecision` 的以下字段**标记 deprecated 注释**（不删除，保持旧路径兼容）：
    - `execution_mode` — 标记 `# DEPRECATED: facet_planner 路径固定设为 "simple"，仅旧路径使用`
    - `tool_candidates` — 标记 `# DEPRECATED: 由 facet_plan 替代`
    - `preferred_chunk_roles` — 标记 `# DEPRECATED: 由 facet_plan.preferred_roles 替代`
    - `intent.allowed_routes` — 标记 `# DEPRECATED: 由 facet_plan.source 替代`
    - `intent.forbidden_routes` — 标记 `# DEPRECATED: 由 facet_plan 替代`
  - 这些字段的 Pydantic schema 不动，只加注释，避免 break 旧路径的序列化

  **Must NOT do**:
  - 不要删除字段，不要改 model_config
  - 不要改旧路径的 setting 逻辑

  **Parallelization**:
  - Can Run In Parallel: YES
  - Blocked By: Task 1

---

- [ ] 11. 清理 build_routing_decision extra 冗余字段

  **What to do**:
  - 在 `application/router/facet_planner.py` 的 `build_routing_decision_from_facet_planner()` 中删除不再必要的 extra 字段：
    - `extra["top_level_intent"]` — 已无消费者
    - `extra["top_level_intent_reason"]` — 已无消费者
    - `extra["required_facets"]` — 被 `RoutingDecision.facet_plan` 替代
    - `extra["optional_facets"]` — 被 `RoutingDecision.facet_plan` 替代
    - `extra["facet_plan_raw"]` — 被 `RoutingDecision.facet_plan` 替代（如确有调试需要可保留但标记 DEPRECATED）
  - 保留 `extra["context_has_anchor"]` 和 `extra["context_has_candidate_anchor"]`（被其他模块消费）
  - 保留 `extra["target_shop_id"]`、`extra["candidate_shop_ids"]`、`extra["recommendation_mode"]`（被下游消费）

  **Parallelization**:
  - Can Run In Parallel: YES
  - Blocked By: Task 1, 10

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  验证所有 facet_planner 路径是否不再依赖 intent 字符串做路由。检查每个修改点的旧路径是否保持兼容。

- [ ] F2. **Run Full Test Suite** — `unspecified-high`
  ```bash
  python -m pytest learning-agent-service/tests/ -x -q
  ```
  验证所有现有测试通过。验证新增的 facet_plan 测试通过。

- [ ] F3. **Scope Fidelity Check** — `deep`
  确认没有改动旧路径（phase1_intent / heuristics / FastDecision）。确认新增的 `plan_from_facets()` 未影响旧的 `plan()` 方法。

---

## Commit Strategy

- **Task 1**: `feat(contracts): add facet_plan field to RoutingDecision`
- **Task 2**: `feat(tools): add plan_from_facets() to ToolPlanner`
- **Task 3**: `feat(routing): synthesize_retrieval_plan reads facet_plan`
- **Task 4**: `feat(routing): synthesize_tool_selection reads facet_plan`
- **Task 5**: `feat(tools): ToolOrchestrator.plan() accepts facet_plans param`
- **Task 6**: `feat(rag): QueryRewriteContext accepts facet_plan`
- **Task 7**: `refactor(rag): remove intent hardcode in evidence.py`
- **Task 8**: `refactor(rag): remove intent hardcode in reranker.py`
- **Task 9**: `refactor(rag): remove intent hardcode in rewrite_guard.py`
- **Task 10**: `chore(contracts): mark deprecated fields on RoutingDecision`
- **Task 11**: `chore(router): clean up dead extra fields in facet_planner`

---

## Success Criteria

### Verification Commands
```bash
python -m pytest learning-agent-service/tests/ -x -q
```

### Final Checklist
- [ ] facet_planner 路径下，RAG 和 ToolCall 不再读取 `intent.name` 做路由
- [ ] `RoutingDecision.facet_plan` 在所有 facet_planner 路径下正确填充
- [ ] `ToolPlanner.plan_from_facets()` 覆盖所有 tool facet
- [ ] `_resolve_planner_intent()` 在 facet_plans 提供时被跳过
- [ ] `INTENT_CHUNK_MAP` 在 facet_plans 提供时不被查询
- [ ] `evidence.py` 的 `if intent in (...)` 在 facet_plans 提供时被跳过
- [ ] `reranker.py` 的 `if intent in (...)` 在 facet_plans 提供时被跳过
- [ ] `rewrite_guard.py` 的 intent drift 检测在 facet_plans 提供时被跳过
- [ ] 旧路径（facet_plans=None）行为完全不变
- [ ] 所有现有测试通过
