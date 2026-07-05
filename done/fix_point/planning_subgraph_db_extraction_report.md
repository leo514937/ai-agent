# Planning Subgraph DB Extraction 报告

方案：A

## 目标

把 `planning_subgraph` 中隐藏的 DB / tool 调用剥离出去，让 planning 保持“只做意图、目标、计划编排，不直接碰业务工具”的边界，同时保留单店、对比、推荐三类主路径的可执行性。

## 已完成内容

### 1. Planning 层去除直接候选检索

- `planning_subgraph` 不再直接做 candidate retrieval。
- 推荐类 query 在缺少显式 grounding hint 时，直接走 plan-only 路径，不再触发 `resolve_shop_entity`。
- 目标解析只保留“基于已解析 target / canonical entity 的收敛”，不再在 planning 内做额外搜索。

### 2. 显式店名解析恢复为本地优先

- `shop_resolver` 改为本地精确匹配优先，再考虑 legacy 兜底。
- 去掉了 explicit resolve 向 discovery 的错误回退，避免“查店名却跑到搜索候选”。
- 修复了 `task_type` / `status` 的枚举字符串归一化问题，避免 `TaskType.xxx` / `ShopResolutionStatus.xxx` 这种值误判为未解析。

### 3. ExecutionPlan 协议补齐

- 在 `ExecutionPlan` 中补了：
  - `optional_facets`
  - `dependencies`
  - `timeout_policy`
  - `degradation_policy`
- `evidence_planner`、`execution_plan_builder`、`deterministic_tool_workflow` 都已同步产出这些字段。

### 4. 观测字段补齐

- `graph_state` / `graph_state_model` 增加了规划/执行边界观测字段：
  - `planning_started`
  - `planning_finished`
  - `execution_started`
  - `execution_finished`
  - `planning_tool_calls_count`
  - `execution_tool_calls_count`

### 5. Workflow runner 修复

- 修复了 `deterministic_tool_workflow` 中的 `TOOL_DEFAULT_TIMEOUT_MS` 兜底常量引用。
- 修复了工作流里对 `semantic_frame` 的裸 `.get()` 访问，统一先转 dict。
- 这样单店距离 / 多工具链路不会因为工作流 runner 硬错误提前 fallback。

## 验证结果

已通过：

- `python -m compileall local_life_agent`
- `python -m pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_trace_observability.py -q`
- `python -m pytest local_life_agent/tests/test_phase8_chat_e2e_gate.py -q`

## 备注

- 当前工作区里还有不少与本次任务无关的既有改动，我没有回滚它们。
- 本次抽离的核心结果是：planning 不再直接触达 DB/tool 搜索，候选解析被前移到可控的 target / workflow 路径中。
