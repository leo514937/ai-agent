# Architecture Phase 4 State / DTO Contract Convergence Report

## 1. 结论

PARTIAL PASS

Phase 4 的核心目标是把状态层、业务 DTO、观测元数据和会话写回边界分开，并且把重复的序列化与 DTO 定义收敛到可验证的权威点。当前仓库已经完成了关键收敛：`GraphState` / `SessionState` / domain DTO / observability-trace 的职责边界已经可说明、可测试、可追踪；会话写回也已经收束到单一路径；并且引入了统一的 `to_plain_dict` / `to_plain_list` 工具，减少了多处手写转换逻辑。

但本阶段仍保留两类有意未完全清理的残余：

- `domain/schemas.py` 里仍有历史 DTO 兼容定义，尚未在本阶段一次性删净
- `slot_extractor` 仍保留 `task_type` / `workflow_hint` 这类兼容性输出，虽然它已经不输出 `shop_id`，也没有扩张成业务决策器，但这部分是否要继续收缩，需要在后续阶段单独决策

因此本阶段结论是 `PARTIAL PASS`，而不是 `PASS`。

## 2. 本阶段范围

本阶段只收敛 state / DTO 契约，不改路由权威层、不改工具注册体系、不改 DB 边界，也不新增平行 DTO 模块。

本阶段关注的是：

- `domain/graph_state.py`
- `domain/graph_state_model.py`
- `domain/state.py`
- `domain/session_context_summary.py`
- `domain/state_validation.py`
- `domain/schemas.py`
- `domain/decision.py`
- `domain/evidence.py`
- `domain/shop_entity.py`
- `domain/facets.py`
- `semantic/slot_extractor.py`
- `observability/trace.py`
- `observability/metrics.py`

本阶段不做：

- 不新增第二套状态模型
- 不新增平行 DTO 包
- 不把 observability metadata 塞回业务 DTO
- 不让多个节点分散写 `SessionState`
- 不改 `planning/orchestration_router.py` 的路由权威逻辑

## 3. 四层边界定义

本阶段确认并固定以下四层：

```text
GraphState = 单 turn 图执行态
SessionState = 跨 turn 业务记忆
Domain DTO = 业务事实对象
Observability / Trace = 执行过程元数据
```

### 3.1 GraphState

GraphState 承载的是一次图执行中的上下文、临时中间结果、review / budget / rewrite / fallback 信息，以及 session 快照。

当前仓库中，GraphState 仍包含这些典型执行态字段：

- `review_results`
- `budget_context`
- `rewrite_count`
- `fallback_reason`
- `answer_verify_passed`
- `state_update_plan`
- `session_state_before`
- `session_state_after`

这些字段属于执行态或 trace 辅助信息，不是 domain DTO。

### 3.2 SessionState

SessionState 是跨 turn 的业务记忆层，适合保存当前店铺、上一次推荐列表、待澄清内容、比较对象、复用的约束信息等。

当前仓库中的典型 SessionState 字段包括：

- `current_shop`
- `current_shop_meta`
- `last_recommendation_list`
- `pending_clarification`
- `comparison_targets`
- `review_results`
- `replan_counters`

这些字段属于可持久化记忆，不应散落在多个节点里各自写回。

### 3.3 Domain DTO

Domain DTO 只负责表达业务事实，不负责编排状态，也不负责 trace 元数据。

当前仓库里已经具备明确的 canonical DTO 所有者：

- `DecisionPlan` -> `domain/decision.py`
- `EvidenceReviewResult` -> `domain/evidence.py`
- `ShopCandidate` / `ShopResolutionResult` -> `domain/shop_entity.py`
- `TargetResolutionResult` -> `domain/facets.py`

`domain/schemas.py` 中仍保留若干历史 DTO 兼容定义，这部分是本阶段的残余，不再被视为新的权威来源。

### 3.4 Observability / Trace

Observability / Trace 只负责描述过程，不负责定义业务事实。

这类字段包括：

- review 触发与结果
- budget 消耗
- retry / rewrite / replan 次数
- loop 过程记录
- fallback 原因
- answer verify 的执行结果

这些信息应该留在 trace、metrics、GraphState 或执行态 envelope 中，而不是迁移到 domain DTO。

## 4. 当前实现事实

### 4.1 `domain/graph_state_model.py` 与 `domain/state_validation.py`

`GraphStateModel` 继续承担 GraphState 的校验与兼容检查职责；`state_validation.py` 则提供可序列化的 contract snapshot，便于测试和文档直接读取字段归属。

当前字段归属里，关键 owner 已经可见：

- `tool_results` -> `execution_review_subgraph`
- `target_resolution` -> `planning_subgraph`
- `session_state` -> `state_update_plan`
- `orchestration_decision` -> `orchestration_router`
- `evidence_pack` -> `execution_review_subgraph`

这说明 GraphState 的关键字段边界已经不是模糊混放，而是可以明确追踪 owner。

### 4.2 `domain/state.py`

`StateUpdatePlan` 仍然是会话写回的权威计划对象，`SessionWriteDirective` 保留为 backward-compatible 别名。

本阶段确认：

- `set_fields` / `clear_fields` 仍是唯一写回载体
- `clone()` / `normalize()` 保持单对象语义
- `to_plain_dict` 被用于把各种 dataclass / pydantic / dict 输入归一成 plain dict

### 4.3 `engine/subgraphs/state_update_plan.py`

会话写回仍然集中在这里执行，未扩散到多个节点。

这意味着：

- 只有一个地方真正 `setattr(session_state, ...)`
- `StateUpdatePlan` 负责表达意图
- `state_update_plan` 节点负责把计划落成 `SessionState`

这满足了 Phase 4 对“不要让多个节点分散写 SessionState”的约束。

### 4.4 `planning/plans/state_update_planner.py`

状态更新规划器仍然根据当前 turn 的语义、比较、推荐、澄清等场景构造写回计划。

本阶段对它的处理不是重写逻辑，而是把输入转换逻辑收敛到统一的 `to_plain_dict`，减少手写序列化分支。

### 4.5 `semantic/slot_extractor.py`

slot extractor 目前已经体现出“锚点与候选”导向：

- 会输出 `merchant_mentions`
- 会输出 `comparison_targets`
- 会输出 `preference_signals`
- 不输出 `shop_id`

但它仍保留 `task_type` / `workflow_hint` 这类兼容性字段，因此它还没有完全退回到纯锚点提取器的最小形态。

这就是本阶段未打满 `PASS` 的主要原因之一。

## 5. 本阶段修改

本阶段实际修改文件：

- [`local_life_agent/domain/serialization.py`](../local_life_agent/domain/serialization.py)
- [`local_life_agent/domain/graph_state_model.py`](../local_life_agent/domain/graph_state_model.py)
- [`local_life_agent/domain/state.py`](../local_life_agent/domain/state.py)
- [`local_life_agent/planning/plans/state_update_planner.py`](../local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/tests/test_phase4_state_dto_contracts.py`](../local_life_agent/tests/test_phase4_state_dto_contracts.py)
- [`todo/architecture_phase4_state_dto_contract_convergence_report.md`](./architecture_phase4_state_dto_contract_convergence_report.md)
- [`todo/architecture_overlap_analysis.md`](./architecture_overlap_analysis.md)

修改原因：

- 提供统一的序列化工具，减少分散的 `_to_dict` / `_as_dict` 风格实现
- 把 GraphState / SessionState / DTO / Trace 的边界写成可测试事实
- 用 boundary test 冻结 session writeback 的唯一入口
- 用 boundary test 确认 slot extractor 没有扩张到 `shop_id` 决策

未修改的关键实现文件及原因：

- `local_life_agent/domain/schemas.py`：仍保留历史兼容 DTO，等待后续阶段按真实调用方逐步收缩
- `local_life_agent/semantic/slot_extractor.py`：保留 `task_type` / `workflow_hint` 兼容输出，后续可单独决策是否进一步收缩
- `local_life_agent/observability/trace.py`：当前已有清晰 trace 语义，本阶段不强行重写

## 6. 收敛结果

### 6.1 状态层

- GraphState 的执行态字段与 session 快照字段已经可以明确识别
- SessionState 的写回入口已经集中
- `StateUpdatePlan` / `SessionWriteDirective` 维持计划层边界，不直接充当业务事实对象

### 6.2 DTO 层

- canonical DTO 的归属已经明确
- 新的统一序列化工具已经上线
- 旧的兼容 DTO 仍在 `domain/schemas.py`，但不再是唯一权威来源

### 6.3 Trace 层

- review / budget / rewrite / fallback 元数据继续留在执行态与 observability 侧
- 没有把 trace 信息回灌成业务 DTO

### 6.4 slot extractor 层

- `slot_extractor` 不再输出 `shop_id`
- 它仍可输出比较、偏好与文本锚点信息
- 仍保留部分兼容性字段，因此本阶段将其视为 `NEEDS_DECISION` 而非彻底收口完成

## 7. 测试与回归结果

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase4_state_dto_contracts.py -q`
- `pytest local_life_agent/tests/test_p13_state_schema_convergence.py -q`
- `pytest local_life_agent/tests/test_domain_schemas.py -q`
- `pytest local_life_agent/tests/test_phase_e_state_contracts.py -q`
- `pytest local_life_agent/tests/test_slot_extractor_boundaries.py -q`
- `pytest local_life_agent/tests/test_p5_session_state_writeback.py -q`
- `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
- `pytest local_life_agent/tests/test_target_resolution_contract.py -q`

测试结论：

- State / DTO boundary tests 已通过
- Session writeback 仍然只有一个真实执行入口
- Serialization helper 对常见 Python / dataclass / pydantic 形态可用
- slot extractor 仍保持 anchor / candidate 导向，没有退化成 `shop_id` 决策器

## 8. 残余风险

- `domain/schemas.py` 的旧 DTO 兼容定义仍然存在，后续需要按真实调用方继续收缩
- `slot_extractor` 的 `task_type` / `workflow_hint` 输出仍是兼容性痕迹，是否继续收缩需要单独决策
- 其他模块里还存在少量手写序列化辅助逻辑，虽不影响本阶段边界判断，但后续可以继续逐步替换成统一工具

## 9. Phase 5 准入判断

可以进入 Phase 5，但应带着一个明确的 `NEEDS_DECISION` 前提：

- `slot_extractor` 是否需要完全移除 `task_type` / `workflow_hint` 兼容输出
- `domain/schemas.py` 中哪些历史 DTO 可以在下一阶段开始按真实调用方删除

这两个点不影响当前状态契约验证通过，但会影响后续工具边界与 DTO 清理的具体顺序。
