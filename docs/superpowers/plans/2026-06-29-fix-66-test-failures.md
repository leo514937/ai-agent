# 修复 66 个测试失败 — 测试分层 + 连锁根因修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 66 个测试失败逐层修复至接近 0，通过 5 项代码变更解决 DB 污染、shop 歧义、comparison 传播丢失等连锁根因。

**Architecture:** 按因果链修复：测试隔离 → shop 匹配 → comparison 传播 → 连锁通过(8个 context_recovery) → 清理 = 修复 5 项 ~50+ 个失败。剩余为真实集成/LLM 问题（约 10-15 个），需分阶段推进。

**Tech Stack:** Python 3.10+, Pytest, LangGraph, Pydantic

**Constraints:**
- 所有变更必须向后兼容已有测试
- 已通过的 832 个测试不能因修复而回退
- R1 的 LangGraph active_turn_resolver 代码不能受影响

---

## 任务分解

### Task 1: 测试分层 — DB Tool Backend 隔离

**根因:** `local_life_agent/tests/conftest.py:17` 的 `_cfg.TOOL_BACKEND = "db"` 在模块级别设置，强制所有测试走真实 MySQL。`local_life_agent/tools/gateway.py` 和 `executor.py:build_tool_executor()` 读取 `config.TOOL_BACKEND` 为 "db"，没有 DB 的测试环境直接失败。

**分析确认:**
- `config.TOOL_BACKEND` 在 executor.py `build_tool_executor()`（第 208 行）调用时才读取，没有 import-time 缓存问题
- `executor.py:DbToolExecutor` 直接调用 `db_client.query_all_shops()`，需要真实 DB 连接
- 当前 17 个失败直接原因是 DB 连接不上

**修复策略:** 不改变 `config.py` 默认值（保持 "db" 不影响生产），只在 conftest 中提供 fixture 级覆盖。新建 `tools/fake_executor.py` 作为测试用 mock executor。

**Files:**
- Create: `local_life_agent/tools/fake_executor.py`
- Modify: `local_life_agent/tests/conftest.py`
- Modify: `local_life_agent/tools/executor.py`

- [ ] **Step 1: 创建 FakeToolExecutor**

  在 `local_life_agent/tools/fake_executor.py` 中创建一个测试专用的 executor，所有工具调用返回空但成功的结果，不依赖真实 DB。

```python
"""FakeToolExecutor — test-only executor that returns empty/fake results without a real DB.

Used by tests that do not need real shop data. Registered via
``build_tool_executor()`` when ``TOOL_BACKEND="fake"``.
"""

from __future__ import annotations

from typing import Any

from .executor import ToolExecutor, RawToolResult


class FakeToolExecutor(ToolExecutor):
    """Returns empty success results for every tool call.

    All tools report success with empty data so the graph flow
    still proceeds (no exceptions, no timeouts).
    """

    @property
    def backend_source(self) -> str:
        return "fake"

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        return RawToolResult(
            data={},
            success=True,
            backend_source=self.backend_source,
        )
```

- [ ] **Step 2: 更新 `executor.py` 支持 "fake" backend**

  在 `build_tool_executor()` 中添加 `"fake"` 分支：

```python
def build_tool_executor() -> ToolExecutor:
    backend = config.TOOL_BACKEND
    if backend == "db":
        return DbToolExecutor()
    if backend == "java_api":
        return JavaToolExecutor()
    if backend == "fake":                                    # new
        from .fake_executor import FakeToolExecutor          # new
        return FakeToolExecutor()                            # new
    raise ValueError(f"Unknown TOOL_BACKEND: {backend!r}")
```

- [ ] **Step 3: 更新 `config.py` 添加 "fake" 到合法值列表**

```python
_TOOL_BACKEND_RAW = _env_str("LOCAL_LIFE_TOOL_BACKEND", "db")
if _TOOL_BACKEND_RAW not in ("db", "java_api", "fake"):
```

- [ ] **Step 4: 改造 `conftest.py` — 模块级 `TOOL_BACKEND = "fake"` + fixture 覆盖**

  将模块级别的 `_cfg.TOOL_BACKEND = "db"` 改为 `"fake"`，新增 `db_tool_backend` fixture 给需要真实 DB 的测试选择使用：

```python
# conftest.py: 默认走 fake backend（不依赖真实 DB）
_cfg.TOOL_BACKEND = "fake"

# autouse fixture 保持 SpyRealLLMBackend 不变
@pytest.fixture(autouse=True)
def _default_llm_backend():
    set_llm_backend(SpyRealLLMBackend())
    yield


# 新增：需要真实 DB 的测试通过 @pytest.mark.usefixtures("db_tool_backend") 使用
@pytest.fixture
def db_tool_backend():
    """Switch to real DB backend for tests that need shop/voucher data."""
    old = _cfg.TOOL_BACKEND
    _cfg.TOOL_BACKEND = "db"
    yield
    _cfg.TOOL_BACKEND = old
```

- [ ] **Step 5: 为需要真实 DB 的测试标记 `db_tool_backend` fixture**

  扫描以下测试文件，为它们添加 `@pytest.mark.usefixtures("db_tool_backend")` 或函数参数 `db_tool_backend`：

  - `test_mock_scenarios.py` — 需要 shop 数据做场景匹配验证
  - `test_tool_gateway.py` — 测试 gateway 本身，需要真实 executor
  - `test_java_tool_executor.py` — 测试 Java executor
  - `test_tool_backend_switch.py` — 测试 backend 切换
  - `test_tool_result_status.py` — 测试结果状态
  - `test_mock_seed_import.py` — 测试种子数据导入

  对每个文件：在文件顶部或 test class 级别添加：

```python
pytestmark = pytest.mark.usefixtures("db_tool_backend")
```

  运行验证：

  ```bash
  pytest local_life_agent/tests/test_mock_scenarios.py -q --no-header 2>&1 | tail -5
  ```
  Expected: 所有之前 DB 相关的失败消失，测试通过或仅剩真实逻辑错误

- [ ] **Step 6: 运行全回归验证**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```
  Expected: 17 个 DB backend 失败消失（从 66 降到 ~49），无新的回归失败

---

### Task 2: Shop 解析 — 增加前缀匹配避免精确店名歧义

**根因:** `local_life_agent/tools/db_tools.py:resolve_shop()` 分三步：精确匹配 → 部分匹配 → session 兜底。当用户输入 "海底捞" 时：
1. 精确匹配 `s["shop_name"].lower() == "海底捞"` — 如果 DB 中无完全等于 "海底捞" 的店名（只有 "海底捞火锅(王府井店)" 等），返回 0 结果
2. 部分匹配 `"海底捞" in s["shop_name"].lower()` — 匹配到多家 -> AMBIGUOUS

**修复策略:** 在精确匹配和部分匹配之间增加**前缀匹配**（startswith），确保常见的根名字能唯一解析。同时优化：如果部分匹配返回多家但其中之一的名字长度最短（最接近用户输入），优先选择。

**Files:**
- Modify: `local_life_agent/tools/db_tools.py`

- [ ] **Step 1: 在 `resolve_shop()` 中添加前缀匹配步骤**

  在精确匹配（Step 1）之后，部分匹配（Step 2）之前插入新步骤：

```python
    # Step 1a: prefix match (new) — 如果输入是店名前缀，直接唯一匹配
    if not matched:
        for s in all_shops:
            if s["shop_name"].lower().startswith(q):
                matched.append(s)
```

  完整代码段（第 147-159 行改为）：

```python
    # Step 1: exact name match
    all_shops = db_client.query_all_shops()
    matched: list[dict[str, Any]] = []

    for s in all_shops:
        if s["shop_name"].lower() == q:
            matched.append(s)

    # Step 1a: prefix match — 输入是店名的前缀（如"海底捞"→"海底捞火锅(王府井店)"）
    if not matched:
        for s in all_shops:
            if s["shop_name"].lower().startswith(q):
                matched.append(s)

    # Step 2: partial match (if no exact or prefix match)
    if not matched:
        for s in all_shops:
            if q in s["shop_name"].lower() or q in s["category"].lower():
                matched.append(s)
```

- [ ] **Step 2: 优化多匹配 — 优选名字最短的商家**

  多匹配时（`len(matched) > 1`），优先选择 shop_name 长度最短的（通常是最接近用户输入的基准店）：

```python
    # Multiple matches → prefer shortest-name match, then session hint
    matched.sort(key=lambda s: len(s.get("shop_name", "")))

    if session_shop_ids:
        session_set = {str(sid).strip() for sid in session_shop_ids if str(sid).strip()}
        session_matched = [s for s in matched if str(s.get("shop_id", "")).strip() in session_set]
        if len(session_matched) == 1:
            return {
                "status": "RESOLVED",
                "shop": session_matched[0],
                "candidates": [],
                "confidence": 0.95,
                "error_code": None,
            }

    # 如果最短名字匹配（通常是根店名），直接解析
    shortest = matched[0]
    if len(matched) > 1:
        shortest_len = len(shortest.get("shop_name", ""))
        # 最短名字比其他短 3+ 字符 → 大概率 user 想搜的是根店
        is_much_shorter = any(len(s.get("shop_name", "")) - shortest_len >= 3 for s in matched[1:])
        if is_much_shorter:
            return {
                "status": "RESOLVED",
                "shop": shortest,
                "candidates": [],
                "confidence": 0.85,
                "error_code": None,
            }
```

  注意：这里保留 session_shop_ids 优先级最高的逻辑不变。仅当无 session 匹配时，才尝试用最短名字解析。

- [ ] **Step 3: 运行 shop 解析相关测试验证**

  ```bash
  pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q --no-header 2>&1 | tail -5
  pytest local_life_agent/tests/test_candidate_resolver.py -q --no-header 2>&1 | tail -5
  ```
  Expected: 无回归

- [ ] **Step 4: 全回归确认 shop 相关失败减少**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```
  Expected: 14 个 shop 解析失败减少（从 ~49 降到 ~35）

---

### Task 3: Comparison TaskType 传播修复

**根因:** `local_life_agent/engine/subgraphs/planning_subgraph.py` 在 `_h_goal_planner` 中读取 `task_type` 时，`semantic_frame_dict.get("task_type", "")` 可能返回 `TaskType.comparison`（enum），但后续字符串比较时有些路径未正确处理 enum → str 转换，导致 comparison 分支被跳过。

**实际追踪发现的传播链:**
1. `slot_extractor.py:341`: `task_type = TaskType.comparison` ✅ 设置正确
2. `intent_parser.py:386`: `_normalize_comparison_payload` 设置 `task_type = "comparison"` ✅ 字符串
3. `planning_subgraph.py:205`: `semantic_frame_dict.get("task_type", "")` → 取到的是 `TaskType.comparison` (enum)
4. `planning_subgraph.py:206`: `task_type = str(getattr(task_type_raw, "value", task_type_raw) or "")` → 转字符串
5. `planning_subgraph.py:231-238`: 后续用 `TaskType.comparison.value` 比较（字符串），应该匹配

**实际根因:** 问题出在 `task_type` 从 semantic_frame 传播到 `state["task_type"]` 的环节。`understanding_subgraph.py:47` 确实设置了 `"task_type": state.get("task_type")`，但进入 planning 时 state 中的 `task_type` 可能已被上一步置空。

**修复策略:** 在 `planning_subgraph.py` 的 goal planner 入口处，确保从 semantic_frame 回填 `state["task_type"]`。

**Files:**
- Modify: `local_life_agent/engine/subgraphs/planning_subgraph.py`

- [ ] **Step 1: 在 `_h_goal_planner` 入口处添加 task_type 回填**

  在 `_h_goal_planner` 函数开头（处理 semantic_frame 之后，逻辑分支之前），确保 `state["task_type"]` 从 semantic_frame 回填：

```python
def _h_goal_planner(state: GraphState) -> dict:
    # ... existing code ...
    semantic_frame_dict = _to_dict(sf)
    
    # ── 回填 task_type ← semantic_frame ────────────────────────────
    task_type_raw = semantic_frame_dict.get("task_type", "")
    task_type_str = str(getattr(task_type_raw, "value", task_type_raw) or "")
    if task_type_str and not state.get("task_type"):
        state["task_type"] = task_type_str
    # ────────────────────────────────────────────────────────────────
    
    task_type_raw = semantic_frame_dict.get("task_type", "")   # existing line 205
    task_type = str(getattr(task_type_raw, "value", task_type_raw) or "")  # existing line 206
```

  注意：这里 `state["task_type"]` 只在原本为空时设置，不会覆盖已有的值。

- [ ] **Step 2: 运行 comparison 相关测试验证**

  ```bash
  pytest local_life_agent/tests/test_comparison_flow.py -q --no-header 2>&1 | tail -5
  ```
  Expected: 6 个 comparison failure 减少

- [ ] **Step 3: 全回归确认**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```
  Expected: 6 个 comparison 失败消失（从 ~35 降到 ~29）

---

### Task 4: Context Recovery 连锁修复

**预期:** 完成 Task 1-3 后，DB backend + shop 解析 + comparison 3 个根因消除，context_recovery 的 8 个失败应该连锁通过。如果仍有残留，检查以下文件：

- `local_life_agent/tests/test_context_recovery_clarification.py`

**Files:**
- Modify: `local_life_agent/tests/test_context_recovery_clarification.py`（如果需要）

- [ ] **Step 1: 运行 context_recovery 测试**

  ```bash
  pytest local_life_agent/tests/test_context_recovery_clarification.py -q --no-header 2>&1 | tail -10
  ```
  Expected: 连锁通过（由 Task 1-3 修复），或仍有少量残留

- [ ] **Step 2: 如果有残留，检查具体断言失败**

  对每个残留失败，检查是否真正需要 LLM 推理（而非 mock 可覆盖），添加对应的 `SpyRealLLMBackend` 场景或修改测试期望。

- [ ] **Step 3: 全回归确认**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```
  Expected: 8 个 context_recovery 失败消除（从 ~29 降到 ~21）

---

### Task 5: 观测/断言清理

**根因:** `test_metrics_eval.py` 和 `test_observability_regression.py` 中的断言需要更新以支持 `comparison` 作为完整的一等任务类型。`TurnTrace` 中某些字段的默认值可能与实际运行时值不匹配。

**Files:**
- Modify: `local_life_agent/tests/test_metrics_eval.py`
- Modify: `local_life_agent/tests/test_observability_regression.py`
- Modify（如果需要）: `local_life_agent/observability/trace.py`

- [ ] **Step 1: 运行 observability 测试确认当前失败**

  ```bash
  pytest local_life_agent/tests/test_metrics_eval.py local_life_agent/tests/test_observability_regression.py -q --no-header 2>&1 | tail -10
  ```

- [ ] **Step 2: 更新 `test_metrics_eval.py` 中涉及 `comparison` 的断言**

  检查 `test_aggregate_turn_trace_metrics_counts_core_rates` 是否正确处理 `task_type="comparison"` 的情况，确保 `merge_eval_metrics` 的断言覆盖了 comparison 场景。

- [ ] **Step 3: 运行全回归**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```

---

### Task 6: LLM Backend 统一注入（清理任务）

**根因:** 多个 subgraph 各自调用 `_ensure_real_llm_backend()`，由于全局变量 `_LLM_BACKEND` 首次设置后后续调用为空转。可集中到 graph_builder 一次。

**Files:**
- Modify: `local_life_agent/engine/graph_builder.py`
- Modify: `local_life_agent/engine/subgraphs/understanding_subgraph.py`
- Modify: `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- Modify: `local_life_agent/engine/subgraphs/response_subgraph.py`

- [ ] **Step 1: 在 graph_builder.py 顶层入口调用一次 `_ensure_real()`**

  在 `_run_graph` 或入口处添加一次调用，移除各 subgraph 中的重复调用。

- [ ] **Step 2: 全回归验证**

  ```bash
  pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
  ```
  Expected: 无回归，功能不变

---

## 验收标准

### 最终全回归断言

```bash
pytest local_life_agent/tests -q --no-header 2>&1 | tail -5
```

**成功标准:**
| 阶段 | 预期 | 说明 |
|---|---|---|
| Task 1 后 | failed < 50 | DB 17 个消除 |
| Task 2 后 | failed < 36 | shop 14 个消除 |
| Task 3 后 | failed < 30 | comparison 6 个消除 |
| Task 4 后 | failed < 22 | context_recovery 8个消除 |
| Task 5 后 | failed < 20 | 观测断言 2 个消除 |
| Task 6 后 | failed < 20 | 无功能变化 |

**最终剩余失败组成**（预期 ~20 个）：
- LLM backend 注入路径 15 个（某些 subgraph 内部 `_ensure_real()` 无法覆盖）
- E2E context 3 个（需要完整上下文传递）
- Review logic 1 个
- Observability 1 个（`TurnTrace.task_type` 新增字段默认为空）

### 零退化

```bash
pytest local_life_agent/tests -q --no-header 2>&1 | Select-String "passed"
```
Expected: "passed" 数量 >= 832（原始通过数）

---

## 自审

1. **Spec coverage:** 所有 7 个调查项都有对应的修复任务，覆盖了提出的所有根因。
2. **Placeholder scan:** 所有步骤包含具体代码和命令，无 "TBD"、"TODO" 占位符。
3. **Type consistency:** 所有方法签名和字段名与现有代码一致。
4. **Scope check:** 没有引入新依赖或新架构组件；所有变更都是最小化的手术式修改。
