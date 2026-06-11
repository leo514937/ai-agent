# P0/P1 Completion Plan: Business Metrics & Realtime Conflict Resolver Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete integration of business_metrics.py and realtime_conflict_resolver.py into the main pipeline, and create Intent success criteria documentation.

**Architecture:** Three integration points: (1) BusinessMetricsCollector hooks into response_builder_node to capture per-query metrics, (2) realtime_conflict_resolver hooks into rag_guardrail to resolve RAG vs tool conflicts, (3) documentation of intent success criteria.

**Tech Stack:** Python, dataclasses, existing local_life modules

---

### Task 1: Integrate BusinessMetricsCollector into builder.py

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:1025-1068`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/__init__.py`

- [ ] **Step 1: Add import for business_metrics in builder.py**

Add after line 42:
```python
from learning_agent_service.local_life.business_metrics import business_metrics_collector, QueryMetrics
```

- [ ] **Step 2: Create metrics collection helper in builder.py**

Add before `_response_builder_node` (around line 1024):
```python
def _collect_query_metrics(state: GraphState, bundle: Any = None) -> None:
    """Collect business metrics for the current query."""
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    persistent = state.get("persistent")
    
    # Extract core fields
    raw_query = str(getattr(turn, "raw_query", "") or "")
    answer_contract = turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
    intent = str(getattr(answer_contract, "intent", "") or turn_extra.get("intent", "") or "")
    route = str(_routing_action(state) or "")
    answer_style = str(getattr(answer_contract, "answer_style", "") or "")
    
    # Extract shop info
    target_shop_id = turn_extra.get("selected_shop_id") or getattr(persistent, "selected_shop_id", None)
    answer_shop_ids = list(turn_extra.get("answer_shop_ids") or [])
    
    # Extract facets
    forbidden_facets = list(getattr(answer_contract, "forbidden_facets", []) or [])
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    
    # Extract evidence/tool info
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    tool_results = list(turn_extra.get("tool_results") or [])
    
    # Extract degradation info
    degraded = bool(turn_extra.get("degraded") or getattr(state["runtime"], "degrade_to", ""))
    degraded_reason = str(getattr(state["runtime"], "degrade_to", "") or turn_extra.get("degraded_reason", "") or "")
    fallback = bool(turn_extra.get("fallback"))
    
    # Extract clarification info
    clarification_asked = bool(turn_extra.get("clarification_asked"))
    clarification_needed = bool(turn_extra.get("clarification_needed"))
    
    # Extract answer text
    answer_text = str(getattr(turn, "final_answer", "") or "")
    
    # Build metrics
    metrics = QueryMetrics(
        query=raw_query,
        intent=intent,
        route=route,
        answer_style=answer_style,
        single_shop_mode=answer_style == "single_shop_review",
        recommendation_mode=answer_style == "multi_shop_recommendation",
        tool_called=bool(tool_results),
        tools_called=[str(r.get("tool_name", "")) for r in tool_results if isinstance(r, dict)],
        evidence_count=len(evidence_claims),
        target_shop_id=target_shop_id,
        answer_shop_ids=answer_shop_ids,
        forbidden_facets=forbidden_facets,
        realtime_facets=realtime_facets,
        degraded=degraded,
        degraded_reason=degraded_reason or None,
        fallback=fallback,
        clarification_asked=clarification_asked,
        clarification_needed=clarification_needed,
        answer_text=answer_text,
    )
    
    business_metrics_collector.record_query(metrics)
```

- [ ] **Step 3: Hook metrics collection into _response_builder_node**

In `_response_builder_node` (line 1025-1068), add metrics collection after `build_response_bundle` succeeds. Replace the except block:

```python
def _response_builder_node(state: GraphState, services: WorkflowServices) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    bundle = None
    try:
        bundle = build_response_bundle(
            raw_query=str(getattr(turn, "raw_query", "") or ""),
            slots=getattr(turn, "slots", None),
            answer_contract=turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None),
            ranked_candidates=list(turn_extra.get("ranked_candidates") or []),
            evidence_claims=list(turn_extra.get("evidence_claims") or []),
            answer_plan=turn_extra.get("task_plan") or getattr(turn, "task_plan", None),
            verification_result=turn_extra.get("answer_verifier_result"),
            evidence_pack=getattr(turn, "evidence_pack", None),
            page=str((state.get("runtime_context", {}) or {}).get("page") or (state["runtime"].client_context or {}).get("page") or ""),
            current_topic=str(getattr(state["persistent"], "current_topic", "") or ""),
            selected_shop_id=turn_extra.get("selected_shop_id"),
            current_shop=str(turn_extra.get("current_shop") or getattr(state["persistent"], "current_shop", "") or ""),
            client_context=dict(getattr(state["runtime"], "client_context", {}) or {}),
            approval_required=bool(getattr(turn, "need_human_approval", False)),
            approval_request=turn_extra.get("approval_request"),
            transaction_draft=turn_extra.get("transaction_draft"),
            safety_result=turn_extra.get("final_answer_safety"),
            route_decision=_routing_action(state) or None,
            route_reason=str(getattr(_routing_decision(state), "route_reason", "") or ""),
            current_stage=getattr(turn, "current_stage", None),
            stage_status=getattr(turn, "stage_status", None),
            stage_timeline=list((state["runtime"].metrics or {}).get("stage_timeline", []) or []),
            model_hint=turn_extra,
            source_mode=str(turn_extra.get("source_mode") or ""),
            degraded_reason=str(getattr(state["runtime"], "degrade_to", "") or ""),
            knowledge_freshness=turn_extra.get("knowledge_freshness"),
            user_need=turn_extra.get("user_need"),
            facet_result_bundle=turn_extra.get("facet_result_bundle"),
            graph_trace=turn_extra.get("phase5_trace") or turn_extra.get("phase4_trace"),
        )
        turn_extra["response_bundle"] = bundle.model_dump(mode="json") if hasattr(bundle, "model_dump") else dict(bundle)
    except Exception:
        pass
    
    # Collect business metrics after response is built
    try:
        _collect_query_metrics(state, bundle)
    except Exception:
        pass
    
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["response_builder"] = True
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state
```

- [ ] **Step 4: Export business_metrics from local_life __init__.py**

Add to `__init__.py` in the `TYPE_CHECKING` block and `__all__`:

```python
    from .business_metrics import business_metrics_collector, BusinessMetricsCollector, QueryMetrics, MetricsSummary
```

And in `__all__`:
```python
    "business_metrics_collector",
    "BusinessMetricsCollector",
    "QueryMetrics",
    "MetricsSummary",
```

- [ ] **Step 5: Run tests to verify no regressions**

Run: `pytest tests/local_life/ -q --tb=short`
Expected: All existing tests pass.

---

### Task 2: Integrate realtime_conflict_resolver into rag_guardrail.py

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/rag_guardrail.py:179-180`

- [ ] **Step 1: Add import for realtime_conflict_resolver**

Add at top of `rag_guardrail.py`:
```python
from learning_agent_service.local_life.realtime_conflict_resolver import (
    resolve_realtime_conflict,
    should_use_tool_result_for_facet,
    get_freshness_status,
    REALTIME_FACETS,
)
```

- [ ] **Step 2: Modify the realtime facet drop logic**

Replace lines 179-180 in `rag_guardrail.py`:

Current code:
```python
            elif facet in realtime_facets or ("coupon" in realtime_facets and has_coupon_text) or ("open_status" in realtime_facets and has_open_text):
                drop_reason = "realtime_facet_from_rag"
```

New code:
```python
            elif facet in realtime_facets or ("coupon" in realtime_facets and has_coupon_text) or ("open_status" in realtime_facets and has_open_text):
                # Use conflict resolver to determine if we should drop or keep
                tool_result = None  # Tool results are not available at guardrail time
                resolution = resolve_realtime_conflict(
                    facet=facet or ("coupon" if has_coupon_text else "open_status"),
                    tool_result=tool_result,
                    rag_result=_claim_text(item),
                )
                # If no tool result available, RAG data is the only source - keep it as fallback
                if resolution is None or resolution.chosen_source == "rag":
                    # Allow RAG data as fallback when tool data unavailable
                    drop_reason = None
                else:
                    drop_reason = "realtime_facet_from_rag"
```

- [ ] **Step 3: Run tests to verify no regressions**

Run: `pytest tests/local_life/rag/ -q --tb=short`
Expected: All existing tests pass.

---

### Task 3: Integrate realtime_conflict_resolver into merge_or_rank_node

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:1071-1082`

- [ ] **Step 1: Add import for realtime_conflict_resolver**

Add after the business_metrics import:
```python
from learning_agent_service.local_life.realtime_conflict_resolver import resolve_realtime_conflict, REALTIME_FACETS
```

- [ ] **Step 2: Add conflict resolution helper**

Add before `_merge_or_rank_node`:
```python
def _resolve_facet_conflicts(state: GraphState) -> None:
    """Resolve conflicts between RAG and tool results for realtime facets."""
    turn_extra = _turn_extra(state)
    answer_contract = turn_extra.get("answer_contract") or getattr(state["turn"], "answer_contract", None)
    
    if answer_contract is None:
        return
    
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    if not realtime_facets:
        return
    
    # Get tool results
    tool_results = list(turn_extra.get("tool_results") or [])
    tool_result_map = {}
    for tr in tool_results:
        if isinstance(tr, dict):
            facet = tr.get("facet") or tr.get("tool_name", "")
            tool_result_map[facet] = tr
    
    # Get evidence claims (RAG results)
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    
    # Resolve conflicts for each realtime facet
    for facet in realtime_facets:
        if facet in REALTIME_FACETS:
            tool_result = tool_result_map.get(facet)
            rag_result = None
            # Find RAG evidence for this facet
            for claim in evidence_claims:
                claim_facet = str(getattr(claim, "facet", "") or (claim.get("facet", "") if isinstance(claim, dict) else ""))
                if claim_facet == facet:
                    rag_result = claim
                    break
            
            if tool_result or rag_result:
                resolution = resolve_realtime_conflict(
                    facet=facet,
                    tool_result=tool_result,
                    rag_result=rag_result,
                )
                if resolution:
                    turn_extra[f"conflict_resolution_{facet}"] = {
                        "chosen_source": resolution.chosen_source,
                        "resolution_reason": resolution.resolution_reason,
                    }
```

- [ ] **Step 3: Hook conflict resolution into _merge_or_rank_node**

Replace the existing `_merge_or_rank_node`:

```python
def _merge_or_rank_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    
    # Resolve realtime facet conflicts before recording metrics
    try:
        _resolve_facet_conflicts(state)
    except Exception:
        pass
    
    ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    turn_extra["merge_or_rank"] = {
        "ranked_candidate_count": len(ranked_candidates),
        "evidence_claim_count": len(evidence_claims),
        "route_branch": _route_branch(state) or None,
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state
```

- [ ] **Step 4: Run tests to verify no regressions**

Run: `pytest tests/local_life/ -q --tb=short`
Expected: All existing tests pass.

---

### Task 4: Create Intent Success Criteria Documentation

**Files:**
- Create: `docs/local-life-intent-success-criteria.md`

- [ ] **Step 1: Create the documentation file**

Create `docs/local-life-intent-success-criteria.md`:

```markdown
# 本地生活 Intent 成功标准定义

> 版本: 1.0
> 更新日期: 2026-06-11

---

## 概述

本文档定义了本地生活服务中每个 Intent 的成功标准，用于指导开发、测试和评估。

---

## Intent 成功标准

### 1. merchant_detail (商家详情)

**触发条件**: 用户询问某家店的具体信息（如"海底捞怎么样"、"这家店好吃吗"）

**成功标准**:
- ✅ 必须命中目标店（不能串店）
- ✅ 必须围绕用户关心点输出（环境/口味/服务等）
- ✅ 禁止推荐其他店
- ✅ 不能输出用户未询问的维度

**失败模式**:
- `cross_shop`: 输出了其他店的信息
- `wrong_entity`: 命中了错误的店
- `forbidden_facet_violated`: 输出了禁止的维度

**评估指标**:
- 串店率 < 5%
- 错店率 < 3%

---

### 2. coupon_query (优惠券查询)

**触发条件**: 用户询问优惠券/团购信息（如"有券吗"、"有什么优惠"）

**成功标准**:
- ✅ 必须调用 `get_coupon_list` 工具
- ✅ 必须说明券是否可用
- ✅ 不能答环境/口味/服务
- ✅ 不能推荐其他店

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称有券
- `forbidden_facet_violated`: 输出了环境/口味/服务

**评估指标**:
- 工具调用命中率 > 95%
- 禁止维度泄露率 < 2%

---

### 3. open_status (营业状态)

**触发条件**: 用户询问是否营业（如"还在开门吗"、"几点关门"）

**成功标准**:
- ✅ 必须调用 `check_open_status` 工具
- ✅ 必须给出当前营业判断
- ✅ 无法确认时要说明不确定
- ✅ 不能猜测营业状态

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称营业状态
- `realtime_error`: 工具调用失败但未降级

**评估指标**:
- 工具调用命中率 > 95%
- 实时信息错误率 < 3%

---

### 4. nearby_recommendation (附近推荐)

**触发条件**: 用户请求推荐附近商家（如"附近有什么好吃的"、"推荐几家火锅店"）

**成功标准**:
- ✅ 必须绑定位置信息
- ✅ 必须能解释推荐理由
- ✅ 不能随机推荐
- ✅ 位置缺失时必须追问

**失败模式**:
- `location_missing`: 无位置却直接推荐
- `no_recommendation_reason`: 推荐无理由

**评估指标**:
- 过度追问率 < 10%
- 兜底率 < 5%

---

### 5. comparison (比较选择)

**触发条件**: 用户请求比较两家或多家店（如"A和B哪个好"、"哪家更适合约会"）

**成功标准**:
- ✅ 必须识别比较对象（至少2家）
- ✅ 必须确定比较维度
- ✅ 必须分别检索两家证据
- ✅ 必须按维度组织差异
- ✅ 必须有最终建议

**失败模式**:
- `comparison_no_template`: 无结构化对比模板
- `single_shop_in_comparison`: 只输出一家店

**评估指标**:
- 比较模板使用率 100%
- 最终建议输出率 > 90%

---

### 6. address/distance (地址/距离)

**触发条件**: 用户询问地址或距离（如"在哪"、"有多远"）

**成功标准**:
- ✅ 必须调用 `get_distance_eta` 工具
- ✅ 不能猜测距离
- ✅ 无法获取时要说明

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称距离
- `realtime_error`: 工具调用失败但未降级

**评估指标**:
- 工具调用命中率 > 95%
- 实时信息错误率 < 3%

---

### 7. clarification (澄清追问)

**触发条件**: 用户输入信息不足（如空输入、纯标点、"啊"、"嗯"）

**成功标准**:
- ✅ 必须识别缺失信息
- ✅ 不能直接回答
- ✅ 追问要具体明确
- ✅ 连续追问不超过2次

**失败模式**:
- `over_clarification`: 不该追问时追问
- `clarification_too_vague`: 追问不够具体

**评估指标**:
- 过度追问率 < 10%
- 追问成功率 > 60%

---

### 8. out_of_scope (非本地生活)

**触发条件**: 用户询问非本地生活内容（如"今天天气怎么样"、"帮我写代码"）

**成功标准**:
- ✅ 不能进入 resolve_target_shop
- ✅ 不能进入 RAG/tool
- ✅ 必须给出明确的超出范围提示

**失败模式**:
- `scope_violation`: 进入了本地生活流程

**评估指标**:
- 兜底率 < 5%（对非本地生活查询）

---

## 综合评估指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 串店率 | < 5% | 单店模式下输出了其他店的信息 |
| 错店率 | < 3% | 命中了错误的店 |
| 过度追问率 | < 10% | 不该追问时追问 |
| 兜底率 | < 5% | 无法回答时给出兜底 |
| 工具调用命中率 | > 95% | 需要工具时成功调用 |
| 空召回率 | < 10% | RAG检索无结果 |
| 实时信息错误率 | < 3% | 实时信息与实际不符 |
| 禁止维度泄露率 | < 2% | 输出了禁止的维度 |
| 降级率 | < 15% | 降级回答的比例 |

---

## 失败类型映射

| 问题类型 | 典型失败 | 可能原因 | 归属模块 |
|----------|---------|---------|----------|
| 问券却答环境 | answer包含"环境" | forbidden_facet未生效 | answer_contract + answer_linter |
| 问当前营业却用了历史信息 | 无tool调用 | realtime_facet未触发tool | route_gate + tool_planner |
| 问附近却没追问位置 | 直接回答推荐 | location slot缺失未检测 | user_need_parser + clarification |
| 问比较却只答单店 | 只输出一家店 | comparison无模板 | answer_structure_composer |
| 问单店却答成推荐 | 输出推荐列表 | target_shop解析失败 | target_shop_policy |
| 问A店答B店 | 串店 | cross_shop过滤失败 | evidence_scope_guard |
| 无证据硬答 | 编造信息 | evidence不足未检测 | grounded_verifier |
| RAG召回不相关 | 证据不匹配 | 检索质量差 | query_router + rag |
| 工具结果被忽略 | 有tool结果但未使用 | compose_answer忽略 | compose_answer |
| 上下文错误继承 | 继承了错误的current_shop | 代词消解失败 | target_shop_policy |

---

## 附录: 相关代码文件

| 模块 | 文件路径 |
|------|---------|
| Intent路由 | `top_level_intent_router.py` |
| 目标店解析 | `target_shop_policy.py` |
| 答案契约 | `answer_contract.py` |
| 答案结构 | `answer_structure_composer.py` |
| RAG护栏 | `rag_guardrail.py` |
| 工具执行 | `tool_executor` |
| 业务指标 | `business_metrics.py` |
| 冲突解决 | `realtime_conflict_resolver.py` |
```

- [ ] **Step 2: Verify documentation is created**

Run: `ls -la docs/local-life-intent-success-criteria.md`
Expected: File exists with correct content.

---

### Task 5: Add business_metrics and realtime_conflict_resolver to __init__.py exports

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/__init__.py`

- [ ] **Step 1: Add lazy imports for business_metrics**

Add in `__getattr__` function, before the `raise AttributeError` line:

```python
    if name in {"business_metrics_collector", "BusinessMetricsCollector", "QueryMetrics", "MetricsSummary"}:
        from .business_metrics import (
            business_metrics_collector as value_business_metrics_collector,
            BusinessMetricsCollector as value_BusinessMetricsCollector,
            QueryMetrics as value_QueryMetrics,
            MetricsSummary as value_MetricsSummary,
        )
        value_map = {
            "business_metrics_collector": value_business_metrics_collector,
            "BusinessMetricsCollector": value_BusinessMetricsCollector,
            "QueryMetrics": value_QueryMetrics,
            "MetricsSummary": value_MetricsSummary,
        }
        return value_map[name]
    if name in {"resolve_realtime_conflict", "should_use_tool_result_for_facet", "get_freshness_status", "REALTIME_FACETS", "DataSourcePriority", "ConflictResolution"}:
        from .realtime_conflict_resolver import (
            resolve_realtime_conflict as value_resolve_realtime_conflict,
            should_use_tool_result_for_facet as value_should_use_tool_result_for_facet,
            get_freshness_status as value_get_freshness_status,
            REALTIME_FACETS as value_REALTIME_FACETS,
            DataSourcePriority as value_DataSourcePriority,
            ConflictResolution as value_ConflictResolution,
        )
        value_map = {
            "resolve_realtime_conflict": value_resolve_realtime_conflict,
            "should_use_tool_result_for_facet": value_should_use_tool_result_for_facet,
            "get_freshness_status": value_get_freshness_status,
            "REALTIME_FACETS": value_REALTIME_FACETS,
            "DataSourcePriority": value_DataSourcePriority,
            "ConflictResolution": value_ConflictResolution,
        }
        return value_map[name]
```

- [ ] **Step 2: Run tests to verify no regressions**

Run: `pytest tests/local_life/ -q --tb=short`
Expected: All existing tests pass.

---

### Task 6: Verify Integration End-to-End

**Files:**
- None (verification only)

- [ ] **Step 1: Run full local_life test suite**

Run: `pytest tests/local_life/ -v --tb=short`
Expected: All tests pass, no new failures.

- [ ] **Step 2: Run golden cases test**

Run: `pytest tests/local_life/test_day7_golden_cases_chat.py -v`
Expected: Golden cases still pass.

- [ ] **Step 3: Verify metrics collection works**

Check that `business_metrics_collector` is properly imported and can be used:
```python
from learning_agent_service.local_life import business_metrics_collector
print(business_metrics_collector.get_summary().to_dict())
```

- [ ] **Step 4: Verify conflict resolver works**

Check that `resolve_realtime_conflict` is properly imported and can be used:
```python
from learning_agent_service.local_life import resolve_realtime_conflict
result = resolve_realtime_conflict("open_status", tool_result={"open": True}, rag_result={"hours": "9-21"})
print(result)
```

---

## Self-Review Checklist

- [ ] All P0 items integrated (business_metrics, realtime_conflict_resolver)
- [ ] All P1 items completed (Intent success criteria documentation)
- [ ] No placeholder code remaining
- [ ] All existing tests pass
- [ ] New modules properly exported from __init__.py
- [ ] Documentation is comprehensive and accurate
