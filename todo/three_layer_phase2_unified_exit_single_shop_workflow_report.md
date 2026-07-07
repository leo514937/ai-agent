# 三层改造 Phase 2：统一出口与单店事实 workflow 收敛报告

## 1. 结论

**PARTIAL PASS**

本阶段完成了单店事实工作流的入口别名收敛、证据层 `open_status` 契约修复，以及 workflow runner 的统一入口对齐；但推荐流与部分 e2e 主链路仍有既有失败，且全量测试里还存在一批与本阶段无关的历史问题，因此不能判定为完整 PASS。

## 2. 修改前真实代码调研结果

### 2.1 `ResponseMode` 与消费面

- `ResponseMode` 已覆盖当前真实写入值里最主要的模式：`direct`、`direct_response`、`reject`、`clarify`、`fallback`、`answer`、`tool_answer`、`comparison`、`exploration_plan`。
- `normalize_response_mode()` 已能处理 legacy alias，且 `direct_response` 归一为 `ResponseMode.DIRECT`，当前测试契约也是按这个行为断言的。
- 说明：本阶段没有发现需要新增 `ResponseMode` 枚举项的强需求。

### 2.2 `ResponseDirective` / `RewriteInstruction`

- `ResponseDirective` 已存在，可作为最小回答中间结构复用。
- `RewriteInstruction` 仍然是 DTO，当前 rewrite loop 只是接收其信息，不是 claim-driven rewrite 执行器。
- 本阶段没有新增重复 DTO。

### 2.3 Composer 现状

- `SingleShopFactComposer` 已存在，并且 `compose_deterministic_response()` 已按 `answer_type` / `fallback_template_type` 路由到：
  - `ClarificationComposer`
  - `SystemFallbackComposer`
  - `SingleShopFactComposer`
  - `DirectResponseComposer`
- 说明当前 deterministic composer 已能承接“单店事实 / 降级 / 澄清 / 通用回应”的最小职责。

### 2.4 Workflow 真实出口写点

本阶段调研确认，当前仍存在多个直接写 `final_response` 的 workflow / handler：

- `direct_response_workflow.py`
- `clarification_fallback_workflow.py`
- `deterministic_tool_workflow.py`
- `exploration_planning_workflow.py`
- `response_subgraph.py` 内部 `_h_final_response`

其中：

- `direct_response_workflow` 与 `clarification_fallback_workflow` 仍然是明确的“直接出答” workflow。
- `deterministic_tool_workflow` 实际上就是单店事实 workflow 的实现体，只是历史名字仍是 `deterministic_tool`。
- `exploration_planning_workflow` 仍会在 fallback / clarify 场景自己落 `final_response`。
- `response_subgraph` 仍是第三层统一出口的总闸，但并未接管所有 workflow 的最终自然语言生成。

### 2.5 verifier 真实边界

- `response_subgraph._h_answer_verify()` 在 Phase 1 已修掉空 evidence / 空 draft 直接 pass 的漏洞。
- `answer/verifier.py` 已会对空输入返回失败。
- 本阶段又补了单店事实流里 `is_open` -> `open_status` 的证据归一化，避免 verifier 因字段契约不一致把“营业中”误判成证据缺失。

### 2.6 `BudgetContext` / `review_policy.py` / `ranking_policy.py`

- `BudgetContext` 已具备剩余预算读取与耗尽记录。
- `review_policy.py` 已定义 P0 允许的 sufficiency next action。
- `ranking_policy.py` 已具备确定性排序打分能力。
- 这些底座足以支撑当前 Phase 2 的最小收敛，不需要新增执行层或大改 workflow registry。

## 3. 复用的已有对象

- `ResponseMode`
- `ResponseDirective`
- `RewriteInstruction`
- `SingleShopFactComposer`
- `compose_deterministic_response()`
- 现有 `deterministic_tool_workflow`
- 现有 `response_subgraph`

## 4. 本阶段实际修改

### 4.1 统一单店事实 workflow 入口别名

- 在 `workflow_runner.py` 中增加了 `single_shop_fact_workflow -> deterministic_tool` 的 registry lookup alias。
- 这样外层 orchestration 如果开始使用更语义化的单店事实名字，也能落到现有真实实现，不会开出第二个 workflow。

### 4.2 明确 workflow registry 语义

- `workflow_registry.py` 中把 `deterministic_tool` 的描述改成“single-shop fact workflow (legacy deterministic_tool alias)”。
- 这只是语义对齐，不改变 registry 主语义，也没有新增平行 workflow。

### 4.3 修复单店事实证据契约

- 在 `planning/evidence/evidence_builder.py` 中补了 `is_open` 兼容：
  - `is_open=True` -> `open_status=open`
  - `is_open=False` -> `open_status=closed`
  - 同步影响 `facet_results`、`evidence_items`、候选商家 open_status 写入
- 这样 deterministic 单店事实流在 verifier 看来是同一套证据契约，不会再因为工具返回字段差异而落到 `deterministic_verifier_rejected`。

## 5. verifier 空证据 / 空草稿修复说明

- 这个漏洞在 Phase 1 已经修复，本阶段没有重复造 verifier。
- Phase 2 只是补了 `open_status` 的证据归一化，避免“证据其实有，但字段没对齐”导致 verifier 误判。

## 6. LLM disabled / timeout / empty fallback 修复说明

- 这部分仍沿用 Phase 1 的 deterministic fallback 收敛结果。
- 本阶段没有引入新的 LLM fallback 分支，也没有新增占位文案。
- fallback 仍保留 `answer_source` / `fallback_reason` / degraded metadata 的语义。

## 7. composer / verbalizer 契约对齐说明

- 仍复用现有 deterministic composer，没有复制出第二套 final answer composer。
- 本阶段新增的只是证据层 `open_status` 归一化，确保 deterministic composer 和 verifier 对同一事实字段说同一种语言。
- `single_shop_fact_workflow` 作为别名接入后，外层调用语义和内部真实实现更一致。

## 8. 第 0 批 / 第 1 批 / 第 2 批失败修复情况

### 已修复

- 空 evidence / 空 draft 不再直接 pass（Phase 1 已修）。
- LLM verbalizer fallback / metadata 契约问题（Phase 1 已修）。
- deterministic_tool 单店事实流对 `is_open` 的证据契约不一致导致 verifier 误判（本阶段已修）。
- `single_shop_fact_workflow` 的入口别名已接到现有 `deterministic_tool` 实现。

### 仍遗留

- 推荐流主链路仍有 4 个失败：
  - 闭店商家未从 answer 文本中剔除
  - detail failed 商家未从 answer 文本中剔除
  - `last_recommendation_list` 没有写回 session
  - 推荐后“第一家有券吗”未走到预期 coupon tool
- e2e 主路径仍有 2 个失败：
  - ordinal reference 仍有场景落到了 `clarification_fallback_workflow`
  - deictic comparison 在缺少 current shop 时没有输出预期澄清文案

## 9. 实际修改文件清单

- `/D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py`
- `/D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py`

## 10. 明确没有做的内容

本阶段没有做以下事情：

- 没有重写 `graph_builder.py`
- 没有重写整个 `planning_subgraph`
- 没有拆 `discovery_decision`
- 没有新增 recommendation / comparison workflow
- 没有引入 ClaimExtractor / ClaimVerifier
- 没有引入 ResponseContract V1/V2
- 没有引入 StageToolExecutor / ToolResultCache / RankingPolicy 可执行化
- 没有改 `ContextualizedTurn` / `FocusContext`
- 没有删除 legacy alias
- 没有改 workflow registry 主语义
- 没有把 `deterministic_tool` 迁移成新 workflow

## 11. 测试结果

### 通过的关键测试

- `python -m pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`

### 仍失败的 Phase 2 相关回归

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 4 failed / 13 passed / 2 xfailed
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - 2 failed / 5 passed / 1 skipped

### 全量回归

- `python -m pytest local_life_agent/tests -q`
- 结果：`51 failed, 1273 passed, 37 skipped, 2 xfailed`
- 说明：这些失败里包含大量与本阶段无关的既有问题，尤其集中在 recommendation / clarifying / router / goal_draft / semantic main path 等区域，本阶段没有扩大修复面。

### 编译检查

- `python -m compileall local_life_agent`
- 通过

## 12. 是否建议进入 Phase 3

**建议谨慎进入 Phase 3，但前提是先把 recommendation / ordinal reference / deictic clarification 这组残留单独立项。**

理由：

- Phase 2 需要的“统一出口 + 单店事实 workflow 收敛”已经有了最小闭环。
- 但 recommendation 主链路仍然不稳，直接进入下一阶段容易把本就独立的问题继续混在一起。
- 如果 Phase 3 目标不是 recommendation / reference 主链路，那么可以继续推进；否则建议先把这部分遗留单独收口。
