# Python 服务旧链路清理白名单

这份文档的目标不是“凭文件名删除整包代码”，而是把当前仓库里的 Python 服务链路分清楚：

- 哪些旧文件名已经不存在
- 哪些当前模块仍然在主链路中被使用
- 哪些符号或残留可以安全删除
- 哪些地方看起来像“旧链路”，但实际上已经是当前实现的一部分

先给结论：

- 文档里提到的很多“旧文件名”在当前仓库中已经不存在，不能再删一次。
- `application/router/`、`application/workflow/`、`local_life/subgraph/`、`local_life/response_builder/`、`local_life/query_router.py`、`tools/orchestrator.py`、`domain/contracts.py`、`api/contracts.py` 都是当前链路的一部分，不能按“旧链路”整包删除。
- 当前已经确认并处理掉的 Python 旧残留，主要是 `application/routing_signals/base.py` 里的 `LLMIntentRouterOutput`，以及 `application/routing_primitives.py` 里的 `_route_decision_from_semantic_route`。

---

## 1. 意图路由与分发机制

### 1.1 现状判断

| 领域 | 文档中的旧链路 | 当前仓库状态 | 是否可删 | 说明 |
|---|---|---|---|---|
| 核心路由机制 | `application/router/core.py` (`QueryRouter`)<br>`application/router/stages/llm_routing.py`<br>`application/router/stages/rule_match.py`<br>`application/router/rules.py` | 这些旧文件名已不存在；当前仍在用的是 `application/router/` 包本身，以及 `application/workflow/builder.py` 里的路由节点 | 不可整包删 | 当前 workflow builder 仍直接调用 `route_top_level_intent`、`check_query_safety`、`route_execution_mode`、`build_response_bundle` 等路由相关能力。 |
| 路由输入/输出结构 | `application/routing_signals/base.py` 中的 `LLMIntentRouterOutput` | 已删除 | 可删，且已处理 | 代码图里没有 callers，属于可直接清理的旧残留。 |

### 1.2 当前实际依赖

当前主链路并不是“把路由丢给一个单独的老 `QueryRouter` 类”，而是：

- `application/workflow/builder.py` 负责编译和装配主图
- `application/workflow/runner.py` 负责执行主图
- `application/router/` 提供阶段化路由能力
- `application/routing_primitives.py` 继续消费 `routing_signals`
- `local_life/query_router.py` 负责本地生活场景路由决策

### 1.3 可执行建议

1. 不要删除 `application/router/` 整个目录。
2. 不要删除 `application/workflow/builder.py` 或 `application/workflow/runner.py`。
3. 可以删除的，只应是没有调用方的单个符号，而不是“看起来老”的目录。

---

## 2. 全局编排与图执行

### 2.1 现状判断

| 领域 | 文档中的旧链路 | 当前仓库状态 | 是否可删 | 说明 |
|---|---|---|---|---|
| 主控编排器 | `application/orchestrator.py` (`LLMOrchestrator`) | 这个旧文件名已不存在；当前编排入口是 `application/workflow/runner.py` 和 `application/workflow/builder.py` | 不可删 | 当前主流程已经迁移到 workflow 体系，不能再按文档里的旧文件名去删。 |
| 工具调度器 | `application/tools/orchestrator.py` (`ToolOrchestrator`) | 旧路径不存在；当前实际使用的是 `tools/orchestrator.py`，并由 `dependencies_impl.py` 注入 | 不可删 | 当前代码仍通过 `AnswerComposer`、`Finalizer`、`ToolExecutor`、`ToolPlanner`、`ToolResultNormalizer` 这些类使用它。 |

### 2.2 当前实际依赖

- `application/workflow/builder.py` 仍是主图装配核心
- `application/workflow/runner.py` 仍是执行核心
- `application/dependencies_impl.py` 仍在构建运行时依赖，并把工具链和本地生活路由器挂到 runtime 上
- `tools/orchestrator.py` 仍属于活跃实现，不是可直接删除的遗留文件

### 2.3 可执行建议

1. 旧文件名层面：不用再删 `application/orchestrator.py`、`application/tools/orchestrator.py`，因为它们已经不存在。
2. 实现层面：保留 `application/workflow/` 和 `tools/orchestrator.py`。
3. 如果后续还要继续清理，只按“调用图无引用”筛，不按“目录名像旧链路”筛。

---

## 3. 本地生活子图与响应构造

### 3.1 现状判断

| 领域 | 文档中的旧链路 | 当前仓库状态 | 是否可删 | 说明 |
|---|---|---|---|---|
| 子图控制流 | `local_life/subgraph.py` (单体大文件) | 旧文件名不存在；原有的 `local_life/subgraph/` 目录已被彻底删除。 | 已删除 | 随着 LangGraph 节点（`adapters/stages_*.py`）完全接管本地生活链路，该生成器模式的控制流代码已作废并被清理。 |
| 结果构造流 | `local_life/response_builder.py` (单体文件) | 旧文件名不存在；当前是 `local_life/response_builder/` 目录，包含 `answers.py`、`bundle.py`、`helpers.py`、`presentation.py` 等 | 不可删 | `build_response_bundle` 仍被 workflow builder 和 subgraph 直接调用。 |

### 3.2 当前实际依赖

- `application/workflow/builder.py` 直接调用 `build_response_bundle`
- `local_life/subgraph/stream_compose.py` 也调用 `build_response_bundle`
- `local_life/debug_retrieve.py` 仍通过 `LocalLifeQueryRouter` 做本地生活调试

### 3.3 可执行建议

1. `local_life/subgraph/` 已被安全删除。
2. 不要删除 `local_life/response_builder/`。
3. 如果是想精简，只能继续看目录里的单个函数或单个类有没有调用方，而不是删整个包。

---

## 4. 跨模块信号与数据传输契约

### 4.1 现状判断

| 领域 | 文档中的旧链路 | 当前仓库状态 | 是否可删 | 说明 |
|---|---|---|---|---|
| 信号载体 | `application/routing_signals/base.py` 中的 `LLMIntentRouterOutput` | 已删除 | 可删，且已处理 | 这是真正确认无调用方的旧残留。 |
| 契约中心 | `domain/contracts.py` 中的 `FinalPayload` 等模型 | 当前仍在使用 | 不可删 | API 事件映射仍依赖这些契约模型。 |
| API 事件映射 | `api/contracts.py` 中的事件 payload models | 当前仍在使用 | 不可删 | `EventType.FINAL` 仍映射到 `FinalPayload`。 |

### 4.2 关键事实

- `application/routing_signals/` 包本身不能删，因为 `application/routing_primitives.py` 仍在 import 它
- `FinalPayload` 不是“文档中的概念”，而是当前事件 payload 的真实模型
- Java 侧 `AiRemoteStreamParser` 解析的是 payload 字段键值，而不是 Python 类型名

### 4.3 可执行建议

1. 可以删的是 `LLMIntentRouterOutput` 这种无 callers 的旧符号。
2. 不要删除 `routing_signals/` 整个包。
3. 不要删除 `domain/contracts.py` 或 `api/contracts.py`。

---

## 5. 文档里提到、但当前仓库里不存在的旧文件

这些条目不需要再删一次，因为仓库里已经没有这些文件了：

- `learning_agent_service/src/learning_agent_service/application/orchestrator.py`
- `learning_agent_service/src/learning_agent_service/application/tools/orchestrator.py`
- `learning_agent_service/src/learning_agent_service/local_life/subgraph.py`
- `learning_agent_service/src/learning_agent_service/local_life/response_builder.py`
- `learning_agent_service/src/learning_agent_service/application/router/core.py`
- `learning_agent_service/src/learning_agent_service/application/router/stages/llm_routing.py`
- `learning_agent_service/src/learning_agent_service/application/router/stages/rule_match.py`
- `learning_agent_service/src/learning_agent_service/application/router/rules.py`

---

## 6. 真实可删白名单

当前确认可以直接删除的 Python 旧残留有两项：

| 目标 | 状态 | 备注 |
|---|---|---|
| `learning_agent_service/src/learning_agent_service/application/routing_signals/base.py` 中的 `LLMIntentRouterOutput` | 已删除 | 没有任何 callers，已从代码中移除。 |
| `learning_agent_service/src/learning_agent_service/application/routing_primitives.py` 中的 `_route_decision_from_semantic_route` | 已删除 | 没有任何 callers，属于旧的语义路由转换壳。 |

如果后面还要继续清理，原则应该是：

1. 先确认有没有 callers
2. 再确认是不是当前 runtime 依赖
3. 最后才决定删除

---

## 7. 当前不可删白名单

以下模块在当前链路中仍然生效，不能按“旧链路”删除：

- `learning_agent_service/src/learning_agent_service/application/workflow/builder.py`
- `learning_agent_service/src/learning_agent_service/application/workflow/runner.py`
- `learning_agent_service/src/learning_agent_service/application/router/`
- `learning_agent_service/src/learning_agent_service/application/routing_signals/`
- `learning_agent_service/src/learning_agent_service/local_life/query_router.py`
- `learning_agent_service/src/learning_agent_service/local_life/subgraph/`
- `learning_agent_service/src/learning_agent_service/local_life/response_builder/`
- `learning_agent_service/src/learning_agent_service/tools/orchestrator.py`
- `learning_agent_service/src/learning_agent_service/domain/contracts.py`
- `learning_agent_service/src/learning_agent_service/api/contracts.py`

---

## 8. 建议的执行顺序

1. 先删已经确认无调用方的单个符号，避免误删目录
2. 再保留所有当前 workflow / local life / contracts / api 的活跃模块
3. 最后只处理“确实不存在的旧文件名”的文档清理，不再把它们当成待删对象

---

## 9. 验证标准

- `pytest` 中与 workflow、local life、routing 相关的测试继续通过
- Python 服务启动时不再导入任何不存在的旧文件路径
- `LLMIntentRouterOutput` 和 `_route_decision_from_semantic_route` 不再出现在代码里
- `application/router/`、`local_life/subgraph/`、`local_life/response_builder/`、`tools/orchestrator.py` 仍能正常被当前链路导入
