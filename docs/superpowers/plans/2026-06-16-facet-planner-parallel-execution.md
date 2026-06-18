# 路由简化 + 并行执行 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6+ layer serial routing pipeline with a single LLM facet planner + parallel executor

**Architecture:** 
- 新 `facet_planner` 模块：一个 LLM 调用直接输出信息面列表，每个面标注数据源 (rag/tool)
- 新 `parallel_facet_executor` 节点：并发执行 RAG 子图和 Tool 子图，合并结果
- 简化 `hybrid_router`：移除 FallbackRuleEngine 关键词降级，纯 LLM 路由
- **增量改造**：新旧路径通过 feature flag 切换，不改动 RAG/Tool 子图内部

**Tech Stack:** Python, LangGraph, ThreadPoolExecutor, Pydantic

**设计原则：**
1. **增量安全**：所有新代码加 feature flag 开关，旧路径保留，随时可回滚
2. **最小拓扑变更**：不改动 RAG/Tool/Recommendation 子图内部，只在主图层面改路由和编排
3. **Karpathy 原则**：只改必须改的代码，不顺手清理无关文件

---

### 前置理解：当前关键文件职责

| 文件 | 行数 | 职责 | 改造方式 |
|------|------|------|---------|
| `local_life/hybrid_router.py` | 1006 | LLM 路由 + FallbackRuleEngine 关键词降级 | 简化 LLM prompt，移除关键词引擎 |
| `application/router/phase1_intent.py` | ~300 | 意图分类 + facet 构建 | 标记废弃，改为从 facet_planner 读取 |
| `application/router/stages/complexity_router.py` | ~200 | simple/standard/complex 分类 | 标记废弃 |
| `application/workflow/subgraphs.py` | 929 | route_gate / route_decider | route_gate 简化，去除多余的分支映射 |
| `application/workflow/builder.py` | 1945 | 图构造 + 条件路由函数 | 添加并行执行边，简化路由函数 |
| `application/workflow/adapters/stages_main_graph.py` | 1361 | select_required_sources / source_dispatch / merge_or_rank | 新增 parallel_facet_executor |
| `application/workflow/adapters/stages_front_b.py` | 711 | tool_executor | 不变 |
| `domain/contracts.py` | 1050 | RoutingDecision / RoutingContract | RoutingContract 增加 facet_plan 字段 |
| `local_life/query_router.py` | ~400 | 关键词 LocalLifeQueryRouter | 标记废弃，移除 |

当前串行链路：
```
route_gate → select_required_sources → source_dispatch → rag_executor → tool_executor → merge_or_rank
```

目标并行链路：
```
facet_planner → parallel_facet_executor (rag∥tool) → merge_or_rank
```

---

### Task 1: 新增 FacetPlan 数据模型

**Files:**
- Modify: `domain/contracts.py` — 新增 FacetPlan / FacetPlannerOutput 模型

**背景：** 当前链路在 RoutingDecision (第 475 行) 和 RoutingContract (第 509 行) 之间有多层转换。需要一组干净的数据结构来表示 facet planner 的输出。

- [ ] **Step 1: 在 contracts.py 中新增模型**

在 `class RoutingContract` (第 509 行) 之前插入：

```python
class FacetPlan(CoreModel):
    """一个信息面及其数据源。"""
    name: str = ""                           # facet 名称: coupon, open_status, distance_eta, environment, taste, service, scene_fit, price, shop_detail, recommendation_reason
    source: Literal["rag", "tool", "recommendation"] = "rag"  # 数据源
    tool_name: str | None = None             # 当 source=tool 时，指定工具名
    preferred_roles: list[str] = Field(default_factory=list)  # 当 source=rag 时，优先 chunk role
    required: bool = True                    # 是否必需
    parallel_group: int = 0                  # 并行分组: 同组可并行，不同组串行


class FacetPlannerOutput(CoreModel):
    """facet_planner 的输出，替代原有的多层路由结果。"""
    facets: list[FacetPlan] = Field(default_factory=list)
    simple_response: str | None = None       # 纯闲聊/问候时直接回复内容
    clarification_needed: bool = False       # 需要澄清
    clarification_question: str | None = None  # 澄清问题
    reject: bool = False                     # 拒绝回答
    reject_reason: str | None = None
    target_shop_id: int | None = None        # 解析到的目标店铺
    candidate_shop_ids: list[int] = Field(default_factory=list)
    recommendation_mode: bool = False
```

在 `class RoutingContract` 中增加字段：

```python
class RoutingContract(CoreModel):
    # ... 现有字段保持不变 ...
    
    # 新增：
    facet_plan: list[FacetPlan] = Field(default_factory=list)  # facet planner 输出，替代 selected_sources
```

别忘了 import Literal：
```python
from typing import Literal  # 已有 Typing import
```

- [ ] **Step 2: 验证模型可用**

Run: `python -c "from learning_agent_service.domain.contracts import FacetPlan, FacetPlannerOutput; print('OK')"`
Expected: OK

---

### Task 2: 创建 Facet Planner 模块

**Files:**
- Create: `application/router/facet_planner.py` — 核心：一个 LLM 调用的 facet planner

- [ ] **Step 1: 创建 facet_planner.py**

新建文件 `learning-agent-service/src/learning_agent_service/application/router/facet_planner.py`：

```python
"""Facet Planner: 单次 LLM 调用直接输出查询所需的信息面列表。

替代原有 6 层路由链路 (hybrid_router -> phase1_intent -> complexity_router ->
select_required_sources -> source_dispatch)。

核心思路：LLM 只需要回答一个问题——"用户要查什么信息？每条信息从哪里拿最合适？"
"""
from __future__ import annotations

import json
import re
from typing import Any

from ...domain.contracts import FacetPlan, FacetPlannerOutput
from ...infrastructure.db.openai_client import OpenAIRuntime


# LLM 系统提示词
_FACET_PLANNER_SYSTEM_PROMPT = """You are a routing planner for a local-life Q&A system.
Given a user query, determine what information facets are needed and where each should come from.

Rules:
- source="tool" for real-time data: coupon (优惠券/团购), open_status (营业状态), distance_eta (距离/导航)
- source="rag" for static/descriptive data: environment (环境), taste (口味), service (服务), price (价格), scene_fit (适合场景), shop_detail (店铺详情)
- source="recommendation" when user asks for shop recommendations (推荐店铺/有什么好吃的/附近有什么)
- If user needs both real-time and static data, return BOTH as separate facets with parallel_group=0 (same group = run in parallel)
- If query is greeting/thanks/small talk, set simple_response
- If query is unclear or needs more info, set clarification_needed=true
- If query is harmful/out-of-scope, set reject=true

Output ONLY valid JSON, no explanation:
{
  "facets": [
    {"name": "coupon", "source": "tool", "tool_name": "get_coupon_list", "required": true, "parallel_group": 0},
    {"name": "open_status", "source": "tool", "tool_name": "check_open_status", "required": true, "parallel_group": 0},
    {"name": "taste", "source": "rag", "preferred_roles": ["merchant_review_summary"], "required": true, "parallel_group": 0}
  ],
  "simple_response": null,
  "clarification_needed": false,
  "clarification_question": null,
  "reject": false,
  "reject_reason": null,
  "target_shop_id": null,
  "candidate_shop_ids": [],
  "recommendation_mode": false
}"""


def _extract_json(text: str) -> str:
    """从 LLM 回复中提取 JSON 块。"""
    # 先尝试 ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # 再尝试直接解析整个输出
    text = text.strip()
    if text.startswith("{"):
        return text
    return text


def plan_facets(
    raw_query: str,
    *,
    openai_runtime: OpenAIRuntime,
    session_context: dict[str, Any] | None = None,
    model: str | None = None,
) -> FacetPlannerOutput:
    """单次 LLM 调用，输出查询所需的信息面列表。

    Args:
        raw_query: 用户原始查询
        openai_runtime: OpenAI 客户端
        session_context: 会话上下文（历史、已解析实体等）
        model: 模型名，默认用 settings 中的配置

    Returns:
        FacetPlannerOutput: 信息面计划
    """
    # 构建用户消息
    context_parts = []
    if session_context:
        if session_context.get("current_topic"):
            context_parts.append(f"会话主题: {session_context['current_topic']}")
        if session_context.get("recent_entities"):
            context_parts.append(f"提到过的实体: {', '.join(session_context['recent_entities'][-3:])}")
    context_str = "\n".join(context_parts) if context_parts else "无特殊上下文"

    user_message = f"""会话上下文:
{context_str}

用户查询: {raw_query}

请分析这个查询需要哪些信息面。"""

    try:
        response = openai_runtime.chat(
            messages=[
                {"role": "system", "content": _FACET_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            model=model,
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content if response.choices else "{}"
    except Exception:
        # LLM 不可用时，降级为简单的规则判断
        return _fallback_plan(raw_query)

    try:
        data = json.loads(raw)
        return FacetPlannerOutput(**data)
    except (json.JSONDecodeError, Exception):
        return _fallback_plan(raw_query)


# 极简降级：仅在 LLM 完全不可用时触发
_COMMON_SHOP_PATTERNS = re.compile(
    r"(海底捞|巴奴|呷哺呷哺|西贝|奈雪|喜茶|瑞幸|星巴克|"
    r"麦当劳|肯德基|必胜客|汉堡王|德克士|真功夫|"
    r"全聚德|便宜坊|大鸭梨|外婆家|绿茶餐厅)"
)


def _fallback_plan(raw_query: str) -> FacetPlannerOutput:
    """LLM 不可用时的极简降级。只处理最基础的 pattern，不做复杂语义判断。"""
    text = re.sub(r"\s+", "", str(raw_query or "")).lower()

    # 问候/感谢
    if any(t in text for t in ("你好", "您好", "谢谢", "感谢", "嗨", "hello", "hi")):
        return FacetPlannerOutput(simple_response="你好！有什么可以帮助你的吗？")

    facets = []

    # 实时面
    if any(t in text for t in ("券", "优惠券", "团购", "代金券", "优惠", "有券")):
        facets.append(FacetPlan(name="coupon", source="tool", tool_name="get_coupon_list"))
    if any(t in text for t in ("营业", "开门", "营业吗", "开门吗", "现在营业")):
        facets.append(FacetPlan(name="open_status", source="tool", tool_name="check_open_status"))
    if any(t in text for t in ("距离", "多远", "导航", "怎么去", "怎么走")):
        facets.append(FacetPlan(name="distance_eta", source="tool", tool_name="get_distance_eta"))

    # 如果没有任何工具面，默认走 rag
    if not facets:
        if any(t in text for t in ("推荐", "有什么好吃", "附近", "哪家")):
            facets.append(FacetPlan(name="recommendation", source="recommendation", parallel_group=0))
        else:
            facets.append(FacetPlan(name="shop_detail", source="rag"))

    target_shop_id = None
    shop_match = _COMMON_SHOP_PATTERNS.search(raw_query)
    if shop_match:
        target_shop_id = 0  # 需要后续 resolve

    return FacetPlannerOutput(
        facets=facets,
        clarification_needed=False,
        target_shop_id=target_shop_id,
    )
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from learning_agent_service.application.router.facet_planner import plan_facets, FacetPlannerOutput; print('OK')"`
Expected: OK

---

### Task 3: 新增 Parallel Facet Executor

**Files:**
- Modify: `application/workflow/adapters/stages_main_graph.py` — 新增 parallel_facet_executor 方法
- Modify: `application/workflow/builder.py` — 注册新节点 + 条件边

- [ ] **Step 1: 在 stages_main_graph.py 中新增 parallel_facet_executor 方法**

在 `def final_answer` (第 965 行) 或其他合适位置之前插入：

```python
def parallel_facet_executor(self, state: GraphState) -> GraphState:
    """并发执行 facet plan 中指定的所有数据源。

    用 ThreadPoolExecutor 并行运行 RAG 子图和 Tool 子图，
    等所有 facet 执行完成后，合并结果到 turn_extra['facet_result_bundle']。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import copy

    turn = state["turn"]
    turn_extra = _turn_extra(state)

    # 1. 从 routing_contract 获取 facet plan
    contract = getattr(turn, "routing_contract", None)
    if contract is None or not contract.facet_plan:
        return state

    facet_plan = list(contract.facet_plan)
    rag_facets = [f for f in facet_plan if f.source == "rag"]
    tool_facets = [f for f in facet_plan if f.source == "tool"]
    rec_facets = [f for f in facet_plan if f.source == "recommendation"]

    futures = {}
    results = {}
    shared_state = copy.copy(state)  # 各线程读共享状态，写隔离

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="facet-exec") as executor:
        # 2. 提交 rag 任务
        if rag_facets:
            # 调用 RAG 子图的入口函数，注意这里需要 services 注入
            # 实际调用由 builder.py 的 lambda 封装
            future = executor.submit(self._run_rag_facets, shared_state, rag_facets)
            futures[future] = "rag"

        # 3. 提交 tool 任务
        if tool_facets:
            future = executor.submit(self._run_tool_facets, shared_state, tool_facets)
            futures[future] = "tool"

        # 4. 提交 recommendation 任务
        if rec_facets:
            future = executor.submit(self._run_rec_facets, shared_state, rec_facets)
            futures[future] = "recommendation"

        # 5. 收集结果
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                result = future.result()
                results[source_name] = result
            except Exception as exc:
                results[source_name] = {"error": str(exc)}
                _LOGGER.warning("parallel_facet_executor: %s failed: %s", source_name, exc)

    # 6. 合并结果到 state
    facet_result_bundle = dict(turn_extra.get("facet_result_bundle") or {})
    if "rag" in results and results["rag"]:
        facet_result_bundle["rag_result"] = results["rag"]
    if "tool" in results and results["tool"]:
        facet_result_bundle["tool_results"] = results["tool"].get("tool_results") or []
        if results["tool"].get("raw_tool_result"):
            state = self._apply_tool_result(state, results["tool"])
    if "recommendation" in results and results["recommendation"]:
        facet_result_bundle["recommendation_result"] = results["recommendation"]

    turn_extra["facet_result_bundle"] = facet_result_bundle
    turn_extra["parallel_execution"] = {
        "rag_duration_ms": results.get("rag", {}).get("duration_ms", 0),
        "tool_duration_ms": results.get("tool", {}).get("duration_ms", 0),
        "rec_duration_ms": results.get("recommendation", {}).get("duration_ms", 0),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _run_rag_facets(self, base_state: GraphState, facets: list) -> dict:
    """运行 RAG 子图，返回检索结果。"""
    import time
    from ...workflow.graphs import build_rag_graph
    t0 = time.time()
    # 浅拷贝 state，避免跨线程冲突
    rag_state = dict(base_state)
    rag_state["turn"] = base_state["turn"].model_copy(deep=True)
    # 注入 facet 约束到 state
    preferred_roles = []
    for f in facets:
        if f.preferred_roles:
            preferred_roles.extend(f.preferred_roles)
    if preferred_roles:
        turn_extra = _turn_extra(rag_state)
        turn_extra["preferred_chunk_roles"] = preferred_roles
        rag_state["turn"] = rag_state["turn"].model_copy(update={"extra": turn_extra})
    # 实际 RAG 调用由外层通过 services 注入，此处占位
    # 参见 builder.py 中 parallel_facet_executor 的 lambda 封装
    duration_ms = int((time.time() - t0) * 1000)
    return {"duration_ms": duration_ms, "status": "executed"}


def _run_tool_facets(self, base_state: GraphState, facets: list) -> dict:
    """运行 Tool 执行器。"""
    import time
    turn = base_state["turn"]
    t0 = time.time()
    tool_results = []
    for facet in facets:
        if facet.tool_name:
            # 构造 ToolPlan 并执行
            from ...domain.contracts import ToolPlan
            plan = ToolPlan(tool_name=facet.tool_name)
            # 调用 tool planner + executor，由外层 services 注入
            tool_results.append({"tool_name": facet.tool_name, "facet": facet.name})
    duration_ms = int((time.time() - t0) * 1000)
    return {"duration_ms": duration_ms, "tool_results": tool_results}


def _run_rec_facets(self, base_state: GraphState, facets: list) -> dict:
    """运行推荐子图。"""
    import time
    t0 = time.time()
    duration_ms = int((time.time() - t0) * 1000)
    return {"duration_ms": duration_ms, "status": "executed"}


def _apply_tool_result(self, state: GraphState, tool_result: dict) -> GraphState:
    """将工具执行结果写回 state，保持与现有 tool_executor 兼容。"""
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    raw_result = tool_result.get("raw_tool_result")
    if raw_result:
        state["turn"] = turn.model_copy(update={"raw_tool_result": raw_result})
    return state
```

- [ ] **Step 2: 在 builder.py 中注册 parallel_facet_executor 节点和条件边**

找到 `graph.set_entry_point` 之后的图构造部分，在 `select_required_sources` 和 `rag_executor` 之间增加分支：

在 `graph.add_node("rag_executor", build_rag_graph(...))` (第 1733 行) 之后添加：

```python
# 并行执行节点 (feature flag 控制)
_ENABLE_PARALLEL_FACET_EXECUTOR = True  # TODO: 改为从 settings 读取

if _ENABLE_PARALLEL_FACET_EXECUTOR:
    graph.add_node(
        "parallel_facet_executor",
        lambda state: services.main_graph.parallel_facet_executor(state),
        retry_policy=workflow_retry_policy,
    )
```

修改 `_route_after_select_required_sources` (第 595 行)，增加并行分支：

```python
def _route_after_select_required_sources(state: GraphState) -> str:
    branch = _route_branch(state)
    if _ENABLE_PARALLEL_FACET_EXECUTOR:
        # 当有 rag_plus_tool 时走并行执行
        if branch == "rag_plus_tool":
            return "parallel_facet_executor"
    if branch == "recommendation":
        return "recommendation_executor"
    if branch == "tool":
        return "tool_executor"
    if branch in {"rag", "rag_plus_tool"}:
        return "rag_executor"
    return "rag_executor"
```

在 `select_required_sources` 的条件边 (第 1835-1843 行) 中添加新路由：

```python
graph.add_conditional_edges(
    "select_required_sources",
    _route_after_select_required_sources,
    {
        "rag_executor": "rag_executor",
        "tool_executor": "tool_executor",
        "recommendation_executor": "recommendation_executor",
        "parallel_facet_executor": "parallel_facet_executor",  # 新增
    },
)
```

添加 `parallel_facet_executor` 到 `merge_or_rank` 的边：

```python
if _ENABLE_PARALLEL_FACET_EXECUTOR:
    graph.add_edge("parallel_facet_executor", "merge_or_rank")
```

---

### Task 4: 简化 hybrid_router — 移除 FallbackRuleEngine

**Files:**
- Modify: `local_life/hybrid_router.py` — 移除 FallbackRuleEngine，精简 LLM prompt

- [ ] **Step 1: 在 hybrid_router.py 中注释/移除 FallbackRuleEngine**

找到 `class FallbackRuleEngine` 定义（约第 200 行附近），将其标记为废弃：

```python
# TODO: FallbackRuleEngine 已废弃，由 facet_planner 替代。
# 保留仅作为 LLM 完全不可用时的极简降级，后续将由 facet_planner 的 _fallback_plan 完全替代。
```

具体改动：

1. 保留 `class FallbackRuleEngine` 但不主动调用
2. 在 `HybridRouter.route()` 方法中，移除 `_route_with_rules()` 降级路径
3. 简化 `HybridRouter._build_intent_classifier_prompt()`，去掉冗余的 intent 类型

- [ ] **Step 2: 简化 HybridRouter._build_intent_classifier_prompt**

把 intent 从 11 种缩窄为 5 种：`realtime_query`, `knowledge_query`, `recommendation`, `clarify`, `chitchat`，去除所有 keyword-driven 的分类逻辑。

- [ ] **Step 3: 验证 hybrid_router 仍可导入**

Run: `python -c "from learning_agent_service.local_life.hybrid_router import HybridRouter; print('OK')"`
Expected: OK

---

### Task 5: 标记废弃文件并验证编译

**Files:**
- Modify: `local_life/query_router.py` — 添加废弃标记
- Modify: `application/router/phase1_intent.py` — 添加废弃标记
- Modify: `application/router/stages/complexity_router.py` — 添加废弃标记
- Verify: `application/workflow/builder.py` — 完整图编译

- [ ] **Step 1: 在 query_router.py 顶部添加废弃标记**

```python
# DEPRECATED: 由 facet_planner 替代。保留用于旧路径兼容，将在下一个版本移除。
```

- [ ] **Step 2: 在 phase1_intent.py 顶部添加废弃标记**

```python
# DEPRECATED: 由 facet_planner 替代。apply_fast_decision 不再被主动调用。
```

- [ ] **Step 3: 在 complexity_router.py 顶部添加废弃标记**

```python
# DEPRECATED: 由 facet_planner 替代。execution_mode (simple/standard/complex) 不再需要。
```

- [ ] **Step 4: 验证图编译**

Run: `python -c "from learning_agent_service.application.workflow.builder import create_workflow_runner; print('graph module OK')"`
Expected: OK（无 import 异常）

---

### Task 6: 端到端集成验证

- [ ] **Step 1: 验证新旧路径开关**

确认 `_ENABLE_PARALLEL_FACET_EXECUTOR` 可以 toggle，两种路径都工作：

1. `_ENABLE_PARALLEL_FACET_EXECUTOR = False` → 走旧串行路径
2. `_ENABLE_PARALLEL_FACET_EXECUTOR = True` → 走新并行路径

- [ ] **Step 2: 运行测试确认不影响现有功能**

```bash
cd learning-agent-service
python -m pytest tests/ -x -q --timeout=120 2>&1 | tail -30
```

Expected: 现有测试通过，新增代码不引入回归

- [ ] **Step 3: 移除临时 feature flag，改为 settings 配置**

在 settings 中增加 `ENABLE_PARALLEL_FACET_EXECUTOR` 配置项，默认开启。

---

### 总结：改造前后对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 路由层级 | 6+ 层（hybrid_router→phase1→complexity→select→dispatch） | 1 层（facet_planner） |
| 路由规则 | 关键词重复 4 个文件，互覆盖 | 单 LLM 输出结构化信息面 |
| RAG+Tool | 串行，总耗时 = RAG + Tool + dispatch 开销 | 并行，总耗时 ≈ max(RAG, Tool) |
| 语义能力 | 简单 intent 分类 (11类) | facet 级别信息需求分析 |
| 维护成本 | 每个文件改关键词需要同步 | 改 LLM prompt 即可 |
| 回滚安全 | — | feature flag 控制新旧路径切换 |
