# Day1 进展 - P0 意图路由底座与信号层改造完成

> 日期：2026-06-05

## 当前状态：✅ **全部完成**

---

## 本日完成事项

### 1. 核心底座整合与清理
- **移除 Legacy 路由文件**：物理删除了过期的 [routing.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/routing.py) 路由垫片，并在 `tests/` 下更新了 11 个关联测试文件，将所有的 `application.routing` 导入重定向至新的强类型 `learning_agent_service.application.router` 统一导出路径。
- **整合 8段式 意图路由管线的前 4 段**：在 [phase0_quality.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/router/phase0_quality.py) 的 `build_initial_routing_decision` 逻辑中，完整接入了以下模块：
  1. **Stage 1 (Hard Guard)**：通过 `check_hard_guard` 对空输入、纯标点、低信息量等输入质量执行零 IO 拦截，成功保障基础拦截能力。
  2. **Stage 2 (Signal Policy)**：通过 `check_signal_policy` 执行关键词、指代词和商家名的规则级模式匹配，生成初始匹配候选。
  3. **Stage 3 (LLM Semantic Parser)**：通过 `parse_query_with_llm` 执行基于大模型的复杂意图分类与槽位解析，并在大模型不可用时优雅退避至 `route_semantic_query` 的规则 fallback 逻辑。
  4. **Stage 4 (Target Resolution)**：通过 `resolve_target_merchant` 对实体与多轮指代关系进行消解，得到明确的目标商家对象。

### 2. 物理修复 downstream 路由回归问题 (100% 成功)
- **修复 Resolved References 多轮继承 Bug**：
  - **现象**：当多轮 follow-up reference 查询（如 "这家店推荐菜"）输入时，由于 target resolution 产出的 `resolved_references` 已填充了 query 中的原始指代串，导致 `if context_shop and not resolved_references` 分支在 context 继承时被误跳过，无法继承 context 中的 `"山城一锅"`。
  - **修复**：修改 [phase0_quality.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/router/phase0_quality.py)，在 `is_follow_up_ref` 状态下，只要上下文存在 shop 实体，便强行覆盖并继承 context shop，确保多轮会话实体消解正确。
- **修复 unserviceable location 早期中断导致 pending context 丢失 Bug**：
  - **现象**：在输入 "北极" 等不在服务区的地址时，unserviceable location 会过早地通过 direct return 退出，绕过了下方的多轮澄清/保存等 helper 过滤链，导致 `extra` 中丢失了 `"pending_clarification_restore"` 数据载荷，使 `test_case_4_arctic_returns_location_unavailable_and_keeps_pending_context` 挂起报错。
  - **修复**：将 unserviceable location 的安全降级重写逻辑，向后移动至多轮澄清与会话续接等 primitives helper 执行之后；并重构为以 `route.model_copy(update={...})` 方式应用 override，完美保留并合并了 `extra` 属性字典内的全部还原属性。

---

## 自动化测试验证结果

1. **路由分类决策矩阵测试**：
   - 执行 `python -m pytest tests/test_routing_decision_matrix.py tests/test_router_package_exports.py`
   - **38 个测试用例 100% 全部通过**。
2. **多轮上下文与核心重演测试**：
   - 执行 `python -m pytest tests/test_phase1_routing.py tests/test_phase0_core_replay.py`
   - **13 个关联测试用例 100% 全部通过**，彻底解决了所有路由回归异常！

---

## 下一步建议

1. **推进 P1-Day2 (Remove Plan/Execute & Route Gate)**：
   - 彻底移除 `plan_execute` 冗余控制节点。
   - 实现简化版本的 `route_gate` 流程分发。
2. **推进 P1-Day3 (Replay Interrupt/Retry)**：
   - 针对长流程支持会话中断和自动重试策略。
