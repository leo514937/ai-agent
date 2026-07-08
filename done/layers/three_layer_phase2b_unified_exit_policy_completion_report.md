# Phase 2-B 统一出口与策略最小闭环补完报告

## 结论

PARTIAL PASS。

本批次已经把第三层回答出口收口到 `response_subgraph`，并把单店事实 workflow 的主名收敛为 `single_shop_fact_workflow`，`deterministic_tool` 保留为兼容别名。`ResponseDirective`、`RewriteInstruction`、`ResponseMode` 继续复用，没有新增重复 DTO。

仍然保留的失败主要集中在 recommendation / e2e 主链路的旧问题，不属于本批次的强改范围。

## 修改前真实代码调研结论

1. `response_subgraph.py` 之前已经是第三层最终入口，但 `direct / clarify / fallback` 分支仍存在“workflow 已写 final_response，subgraph 只 pass-through”的情况。
2. `direct_response_workflow.py`、`clarification_fallback_workflow.py`、`deterministic_tool_workflow.py`、`exploration_planning_workflow.py` 之前都直接写 `final_response`，导致最终回答出口分散。
3. `deterministic_tool_workflow` 是真实单店事实执行体，`deterministic_tool` 更像历史名；本批次将其主名收敛为 `single_shop_fact_workflow`，同时保留兼容别名。
4. `ResponseDirective` 已存在，适合承载最小回答中间结构。
5. `RewriteInstruction` 已存在，但之前只是在定义层，没有真正参与 rewrite loop。本批次补了最小接入。
6. `BudgetContext` 和 `review_policy` 已经存在，可作为后续策略层继续使用，本批次没有重做。

## 复用的已有对象

1. `ResponseMode`
2. `ResponseDirective`
3. `RewriteInstruction`
4. 既有 deterministic composer / fallback composer 路径
5. `BudgetContext`
6. 既有 verifier

## 本批次完成的收口

### 1. `final_response` 统一出口

- `response_subgraph._h_final_response` 现在负责把 `draft_response` / `response_directive` 统一落成 `final_response`。
- `direct_response_workflow`、`clarification_fallback_workflow`、`deterministic_tool_workflow`、`exploration_planning_workflow` 已改为输出 `draft_response` + `response_directive`，不再自己写 `final_response`。
- `response_subgraph` 的 direct / clarify / fallback 路由在 `final_response` 缺失时会补齐最终答案，不再依赖 workflow 自己提前落盘。

### 2. `RewriteInstruction` 最小接入

- `response_subgraph._h_answer_verify` 在空证据 / 空草稿 / 违反校验时，会构造 `RewriteInstruction`。
- `response_subgraph._h_rewrite` 会保留 `rewrite_instruction` 并继续走 rewrite loop。
- `answer/generator.py` 和 `answer/llm_verbalizer.py` 都已接入 `rewrite_instruction` 参数。
- 当 `rewrite_instruction.fallback_mode` 指向 fallback/system_fallback 时，会直接走确定性 fallback，而不是继续依赖 LLM。

### 3. LLM disabled / timeout / empty output 的确定性 fallback

- `llm_verbalizer` 仍然保留失败时的 deterministic fallback。
- `generate_answer()` 继续把 metadata 传递出去，并保留 `fallback_reason` / `answer_fallback_reason` / `verifier_*` 元数据。
- 单店事实场景仍优先使用确定性摘要，避免 LLM 漏事实。

### 4. 单店事实 workflow 主名收口

- `workflow_registry.py` 新增 `single_shop_fact_workflow` 作为主注册名。
- `deterministic_tool` 继续保留为 legacy alias。
- `workflow_runner.py` 现在会把 `deterministic_tool` 归一到 `single_shop_fact_workflow`。
- `run_deterministic_tool_workflow()` 的成功 patch 现在输出 `workflow_name="single_shop_fact_workflow"`。

## composer / verbalizer 契约对齐说明

1. `ResponseDirective` 作为最小回答中间结构，已经被 direct / clarification / fallback / deterministic / exploration workflow 复用。
2. `RewriteInstruction` 没有引入新平行 DTO，只做了最小消费：
   - 记录 verifier 失败原因
   - 参与 rewrite loop
   - 支持 fallback mode 直接走 deterministic text
3. `llm_verbalizer` 的 `fallback_template_type`、`template_fallback` 元数据和 deterministic fallback 契约保持对齐。

## verifier 空证据 / 空草稿说明

- 本批次没有再引入新的 claim verifier。
- 现有 verifier 仍然会把空 evidence / 空 draft 视为不可验证失败，而不是 pass。
- 本批次只补了 `rewrite_instruction` 的最小承接，没有改变 verifier 的安全边界。

## 仍然遗留的失败

### 已知且本批次未处理

1. `test_recommendation_flow.py` 仍有 4 个失败，主要涉及 recommendation 主链路的旧行为与结果整理，不属于本批次强改范围。
2. `test_e2e_llm_main_path.py` 仍有 2 个失败，分别涉及 recommendation / comparison 的端到端旧链路差异。

### 本批次没有做的内容

1. 没有引入 `ClaimExtractor` / `ClaimVerifier`
2. 没有改 `workflow_registry.py` 的主语义结构，只做了单店事实 alias 收口
3. 没有做 recommendation / comparison workflow 新建或重构
4. 没有做 `deterministic_tool -> single_shop_fact_workflow` 的物理迁移删除 legacy alias
5. 没有改第一层 `ContextualizedTurn` / `FocusContext`
6. 没有做 ranking policy / ToolResultCache / StageToolExecutor 可执行化
7. 没有拆 `discovery_decision`

## 实际修改文件清单

- `local_life_agent/answer/generator.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/answer/response_directive.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/engine/workflows/clarification_fallback_workflow.py`
- `local_life_agent/engine/workflows/deterministic_tool_workflow.py`
- `local_life_agent/engine/workflows/direct_response_workflow.py`
- `local_life_agent/engine/workflows/exploration_planning_workflow.py`
- `local_life_agent/tests/test_deterministic_tool_workflow.py`
- `local_life_agent/tests/test_phase7_workflows.py`
- `local_life_agent/tests/test_workflow_registry.py`

## 测试结果

### 已通过

- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`

### 仍失败

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 4 fail
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - 2 fail

## 是否建议进入 Phase 3

建议进入，但建议把 recommendation / e2e 的残余失败单独拆到后续批次，不要混入 Phase 3 的 claim / ranking / workflow 大改。
