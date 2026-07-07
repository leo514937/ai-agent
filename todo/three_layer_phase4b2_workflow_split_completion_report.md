# Phase 4-B2：recommendation / comparison 独立 workflow 拆分完成报告

结论：`PARTIAL PASS`

## 1. 修改前真实代码调研结果

本次改动前，我先核对了真实实现，而不是按文档假设补空文件。

调研结论如下：

- `local_life_agent/planning/orchestration_router.py` 已经能识别 recommendation / comparison 场景，但原始主语义仍落在 `discovery_decision`，没有稳定的独立 workflow 入口。
- `local_life_agent/engine/workflow_registry.py` 和 `local_life_agent/engine/workflow_runner.py` 的 dispatch 主链路仍以 `workflow_name` 为主，comparison / recommendation 的独立入口没有真正落到 registry 层。
- `local_life_agent/engine/_routes.py` 的 workflow runner 路由已经存在，能把 workflow dispatch 后的状态送回 `planning_subgraph`。
- `local_life_agent/engine/subgraphs/planning_subgraph.py` 已经承载了 recommendation / comparison 的真实规划、候选集、比较目标解析、澄清与证据规划逻辑。
- `local_life_agent/domain/schemas.py` 里已有 `ComparisonMatrix`、`DecisionPlan`、`AnswerPlan` 等结构，但 `OrchestrationDecision` 还没有专门用于拆分 workflow entry 的字段。
- `local_life_agent/tests/test_recommendation_flow.py` 和 `local_life_agent/tests/test_comparison_flow.py` 证明 recommendation / comparison 的主链路仍依赖统一 planning / response 出口。
- `ResponseContractV1` / `final_response` 的统一出口仍然在 response 层，不应该在 workflow 内另起出口。

同时我也验收了前置阶段是否还保持有效：

- 3a / 3b / 3c 相关测试在本次修改后仍然通过。
- comparison 的独立 workflow 拆分之前存在一个实际回归：我一开始把新 workflow 包装成了“先执行 planning_subgraph、再进入 planning_subgraph”，导致 comparison 流重复执行；这个问题已修正。

## 2. 这次改造后，recommendation / comparison 的状态

### recommendation workflow

- 新增了真实文件 `local_life_agent/engine/workflows/recommendation_decision_workflow.py`。
- workflow 现在有独立入口名 `recommendation_decision_workflow`。
- registry / runner 可以识别该入口。
- workflow 只负责发出 dispatch patch，不再复制 planning 逻辑，也不直接写 `final_response`。

### comparison workflow

- 新增了真实文件 `local_life_agent/engine/workflows/comparison_decision_workflow.py`。
- workflow 现在有独立入口名 `comparison_decision_workflow`。
- registry / runner 可以识别该入口。
- workflow 同样只负责发出 dispatch patch，不再重复执行 planning_subgraph。
- 这个修正解决了我在第一次拆分时引入的比较流“双跑 planning_subgraph”问题。

### legacy alias

- `discovery_decision` 仍然保留为 legacy alias。
- recommendation / comparison 的新入口已经从 alias 中拆出来，但不破坏旧路径。

## 3. `_h_rewrite` / ClaimVerifier / 3c 前置关系

本阶段不做 3e / 3f，也不引入新的 claim-level 能力。

我只确认并保留了现有结构：

- `response_subgraph` 仍然是统一最终出口。
- `workflow_runner` 仍然负责 registry dispatch。
- `ClaimVerifier L1` 的前置能力未被本次改动破坏。

## 4. route / registry / runner 修改说明

### `local_life_agent/domain/schemas.py`

- 给 `OrchestrationDecision` 增加了 `workflow_entry_name`。
- 这个字段用于把“业务上的 workflow 名称”与“registry entry 名称”拆开。
- 这样 recommendation / comparison 可以保持 legacy `workflow_name` 兼容，同时又能被独立入口识别。

### `local_life_agent/planning/orchestration_router.py`

- recommendation / comparison 场景在 policy table 中补上了对应的 `workflow_entry_name`。
- 验证与补丁生成时会保留这个 entry 名称。
- 这样 router 仍然可以保留 `discovery_decision` 兼容语义，但同时把新 workflow 入口显式带出来。

### `local_life_agent/engine/workflow_registry.py`

- 注册了两个真实入口：
  - `recommendation_decision_workflow`
  - `comparison_decision_workflow`
- registry 现在不再只把 recommendation / comparison 当作 `discovery_decision` 的隐式别名。

### `local_life_agent/engine/workflow_runner.py`

- runner 优先读取 `workflow_entry_name`。
- registry lookup 也优先按 entry 名称做。
- fallback patch 也保留了 `workflow_entry_name`，避免 trace 和状态丢失。

### `local_life_agent/engine/_routes.py`

- workflow runner 的路由也识别 `workflow_entry_name`。
- 这样 recommendation / comparison 的新入口可以继续回到共享 planning_subgraph，不需要复制一整套编排链路。

## 5. 修改前后 workflow 选择策略

修改前：

- recommendation / comparison 主要还是依靠 `discovery_decision` 兼容路径。
- 独立 workflow 名义存在，但没有真正成为 registry / runner 的主入口。

修改后：

- router 继续允许 `discovery_decision` 作为兼容语义。
- recommendation / comparison 会携带独立 `workflow_entry_name`。
- registry / runner 按 entry 名称完成独立 dispatch。
- 真正的规划执行仍复用现有 `planning_subgraph`，避免复制第二套流程。

## 6. 与统一 `final_response` / `ResponseContractV1` 的衔接

本阶段没有改写统一出口。

- workflow 只负责 dispatch。
- 真正的自然语言输出仍由统一 response 层完成。
- `ResponseContractV1` / `final_response` / `preview_text` 的语义保持不变。
- 这次拆分只是把 recommendation / comparison 的入口从 legacy alias 中拆开，没有在 workflow 内自建最终答案出口。

## 7. 实际修改文件清单

- `local_life_agent/domain/schemas.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/engine/_routes.py`
- `local_life_agent/engine/workflows/recommendation_decision_workflow.py`
- `local_life_agent/engine/workflows/comparison_decision_workflow.py`
- `local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py`
- `local_life_agent/tests/test_workflow_registry.py`

## 8. 明确没有做的 3e / 3f 内容

本阶段没有做以下内容：

- 3e：`comparison_matrix -> winner` 强约束
- 3f：`exploration_planning_workflow` 接入共享能力
- ClaimVerifier L2 / L3
- ResponseContract V2
- ContextualizedTurn / FocusContext
- Redis SessionStore
- complex_orchestrator / MapReduce
- 重新拆 recommendation / comparison 的内部 planning workflow

## 9. 测试结果

### 本次重点测试

- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py -q`
  - `4 passed`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
  - `5 passed`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
  - `3 passed`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
  - `4 passed`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - `7 passed, 1 skipped`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
  - `24 passed`

### 仍然存在的全量失败

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 仍有 3 个历史失败：
    - `test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
    - `test_recommendation_ranking_score_is_recomputable`
    - `test_after_recommendation_first_item_reference_works`
  - 这些失败属于 recommendation 既有语义问题，不是这次 workflow split 新引入的回归。

### 编译与全量

- `python -m compileall local_life_agent`
  - 通过
- `python -m pytest local_life_agent/tests -q`
  - `1344 passed, 37 skipped, 2 xfailed, 3 failed`

## 10. 是否解除 3e / 3f 阻塞

结论：`是，已解除前置阻塞`

原因：

- 3d 的 recommendation / comparison 独立 workflow 已经真实拆分出来。
- comparison 流的重复执行回归已修正。
- 3a / 3b / 3c 前置能力保持通过。
- 因此后续可以进入 3e / 3f 的工作，不再被 3d 挡住。

## 11. 是否建议进入 Phase 4-C / 后续批次

建议继续进入后续批次，但要保留一个事实判断：

- recommendation flow 仍有 3 个历史失败未解决。
- 这些失败不影响本次 3d 的阻塞解除，但后续如果要收敛全量回归，仍需单独处理 recommendation 的旧语义差异。
