# Phase 3 实施报告: LLM Semantic Capability Enablement - Router Semantic Policy Guard

## 结论

Phase 3 已完成。当前路由层已经从“关键词优先”收敛为“结构化语义优先、关键词弱信号、可观测可验证”的策略边界；顶层路由仍然保持既有的 Direct Answer / Safety / Local Life Agent 入口分层，没有引入新的平行执行链路。

## 范围

本阶段仅处理 `LLM Semantic Capability Enablement` 的 Phase 3，聚焦路由规则层与工作流边界收敛，不进入 Phase 4 的 planner / evidence / answer 生成增强。

## Files Changed

- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/engine/_routes.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflows/deterministic_tool_workflow.py`
- `local_life_agent/engine/workflows/exploration_planning_workflow.py`
- `local_life_agent/engine/workflows/clarification_fallback_workflow.py`
- `local_life_agent/engine/workflows/direct_response_workflow.py`
- `local_life_agent/domain/schemas.py`
- `local_life_agent/domain/graph_state.py`
- `local_life_agent/domain/graph_state_model.py`
- `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`
- `local_life_agent/tests/test_router_rule_policy_guard.py`
- `local_life_agent/tests/test_orchestration_router.py`
- `local_life_agent/tests/test_workflow_registry.py`
- `local_life_agent/tests/test_workflow_runner.py`
- `local_life_agent/tests/test_semantic_router_policy_alignment.py`

## Actual Router Entry Points

当前实际路由入口链路是：

1. `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`
2. `local_life_agent/planning/orchestration_router.py`
3. `local_life_agent/engine/workflow_runner.py`
4. `local_life_agent/engine/workflow_registry.py`

其中 shadow 层负责镜像与观测，`orchestration_router.py` 负责语义决策，runner / registry 负责工作流分发与落地。

## Router Policy Contract

本阶段把路由协议从“看词面”收敛为“看结构化语义 + 低置信度兜底 + 明确缺槽澄清”三层：

- 顶层安全与拒答仍然优先。
- Local Life Agent 内部路由不再依赖单纯关键词抢占。
- `semantic_parse_source`、`grounding_status`、`missing_slot_type`、`comparison_structure`、`exploration_stages` 等字段进入路由判断。
- 路由结果同时输出可观测 trace 信息，便于审计和回归。

## SemanticFrame Fields Consumed

本阶段路由显式消费的语义字段包括：

- `intent`
- `comparison_intent`
- `comparison_structure`
- `comparison_targets`
- `exploration_stages`
- `preference_signals`
- `filter_signals`
- `location_reference`
- `shop_reference`
- `ordinal_reference`
- `deictic_reference`
- `parse_source`
- `semantic_parse_source`
- `grounding_status`
- `discourse_marker`
- `constraint_update`
- `new_task_override`
- `cancel_intent`
- `missing_slot_type`

## Keyword / Rule Signal Demotion

本阶段没有删除规则信号，但把它们降级为弱信号和 trace 观测：

- 比较、探索、推荐、营业、优惠券等关键词不再单独决定路由。
- 关键词只在结构化语义不足时作为辅助信息。
- `RouterRuleSignal` 仍然保留，用于解释和调试，不作为主决策依据。
- `rule_pattern_signals` 被写入状态，方便定位“为什么会这样路由”。

## Workflow Preconditions

工作流的前置条件现在更明确：

- `direct_response` 只负责明确可直接答复的场景。
- `clarification_fallback` 负责确实缺槽、需要澄清的场景。
- `deterministic_tool_workflow` 只接收经过验证的工具型意图，不再被纯关键词误触发。
- `exploration_planning_workflow` 只在结构化探索阶段或明确多步探索意图成立时进入。

## Comparison Routing Findings

比较路由已改为结构化优先：

- 只有明确的 `comparison_intent` / `comparison_structure` / 比较目标集合才会进入比较语义。
- 单纯出现“比一下”“比较”“哪个更好”之类词面，不再自动等于可执行比较。
- 当比较意图存在但缺少结构化目标时，优先进入澄清，而不是硬走比较工作流。
- 这能避免把模糊比较误路由成错误的工具执行。

## Deterministic Tool Routing Findings

确定性工具路由保持保守：

- 仍然要求明确目标锚点或足够强的单店事实查询信号。
- 不能因为出现“券”“营业”“地址”“距离”等词就提前判定一定是单店确定性执行。
- 如果目标实体不稳，宁可进入澄清或发现流程，也不直接伪装成确定性工具调用。

## Discovery / Facet Routing Findings

发现型与 facet 型意图现在更清晰：

- `优惠券`、`团购`、`营业状态`、`距离`、`价格` 等 facet 可以存在，但不会自动覆盖掉更强的探索或比较语义。
- discovery 不再被词面中的局部 facet 直接抢占。
- 仅当整体语义仍然是单店信息检索时，facet 才作为工具选择辅助。

## Exploration Routing Findings

探索路由由结构化探索阶段驱动：

- `exploration_stages` 成为核心信号。
- 明确的多步安排、先后顺序、阶段化目标才进入探索规划。
- 纯粹的“先去看看”“再推荐几个”不再作为唯一触发依据。
- 当探索目标不明确时，优先澄清，不硬凑成探索工作流。

## Clarification Fallback Findings

澄清回退现在更像“语义缺口修复”而不是万能兜底：

- `missing_slot_type` 会显式区分缺的是位置、店铺、比较目标、探索位置还是类别。
- `grounding_status` 为 `ungrounded` 或 `partially_grounded` 时，更容易进入澄清。
- `new_task_override` 可以突破旧的待澄清状态，避免用户改口后继续卡死在旧上下文。
- `cancel_intent` 可以直接短路，不再继续追问。

## Registry / Runner Findings

工作流注册与运行层补齐了可观测字段透传：

- `workflow_candidate_reason` 贯穿 router、registry、runner、workflow patch。
- `router_policy_decision` 和 `router_policy_conflicts` 进入状态，便于复盘。
- 工作流不再只返回最终路由，还能带出“为什么选它”。
- 这使得路由错误可以在测试里被稳定断言，而不是靠人工看日志猜。

## Safety Guard Findings

安全与拒答边界没有被弱化：

- 顶层 safety / reject 依然优先。
- cancel intent 被显式识别并短路。
- 本阶段没有把安全判断让渡给工具层或工作流层。
- 没有引入会绕过验证器的快速路径。

## Test Coverage

本阶段补充和调整了这些测试：

- `local_life_agent/tests/test_router_rule_policy_guard.py`
- `local_life_agent/tests/test_orchestration_router.py`
- `local_life_agent/tests/test_workflow_registry.py`
- `local_life_agent/tests/test_workflow_runner.py`
- `local_life_agent/tests/test_semantic_router_policy_alignment.py`

覆盖点包括：

- 探索缺位置时回退到澄清
- 取消意图短路到 direct response
- 新任务覆盖可以退出 pending clarification
- 路由 reason 带出 semantic parse metadata
- workflow candidate reason 在 registry / runner / patch 间透传
- shadow patch 使用可序列化模型字段

## Regression Commands Run

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_semantic_router_policy_alignment.py -q`
- `pytest local_life_agent/tests/test_semantic_parser.py -q`
- `pytest local_life_agent/tests/test_llm_semantic_capability_usage_audit.py -q`
- `pytest local_life_agent/tests/test_p2_router_priority.py -q`
- `pytest local_life_agent/tests/test_domain_schemas.py -q`

## Known Remaining Issues

- 这一阶段仍然保留了规则信号和语义信号并存的状态，后续如果继续收敛，可以再考虑进一步压缩解释层的噪音。
- 部分历史测试与旧行为并存，但本阶段没有扩大改动面去做全仓库重写。
- 当前仍以语义边界收敛为目标，没有进入最终 answer / evidence 生成重构。

## Final Gate

Phase 3 的门槛已满足：

- 路由语义边界已经从词面判断升级到结构化语义判断。
- 工作流分发链路的观测信息已补齐。
- 关键回归测试已通过。
- 未越界进入 Phase 4。

