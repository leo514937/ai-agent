# Phase 4 稳定化收口报告：recommendation 语义回归 + 3f 完成状态确认

## 结论

PASS。

本次只修复了第 4 批里的推荐回归与相关收口问题，没有进入 Phase 5，也没有新增第一层上下文能力。

## 修改前真实代码调研结果

### 1. 推荐主链路确实存在，但默认 spy backend 下会被打空

我先验收了推荐链路的真实执行结果，不是只看文档。

在 `SpyRealLLMBackend + mock_tools + db_client fallback` 的真实测试环境里，推荐流程会走到：

- `planning_subgraph`
- `execution_review_subgraph`
- `evidence_builder`
- `response_subgraph`
- `state_update_plan`

但是默认推荐样本会把 `check_open_status` 结果打成 `closed`，而当前 `rank_candidates()` 会直接过滤掉 closed 候选，导致：

- `ranking_snapshot.ranked = []`
- `last_recommendation_list = []`
- 后续 `"第一家有券吗"` 无法沿用推荐结果

这正是 `local_life_agent/tests/test_recommendation_flow.py` 里 3 个失败的直接原因。

### 2. `build_evidence()` 里 recommendation 分支对 `task_type` 的判断不够稳

真实 graph 里 `validated_plan` 是 Pydantic 模型，`task_type` 可能以 Enum 形式进入 `build_evidence()`。

修复前这里使用的是裸 `str(plan_dict.get("task_type", ""))`，对 Enum 值不够稳，推荐分支的触发存在脆弱性。

### 3. `3f` 探索工作流本身没有新增阻塞

我也顺带验收了探索相关回归：

- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`

两者均通过，说明探索 workflow 当前已处于可接受完成状态，不需要进入 Phase 5 才能继续。

## 本次改造点

### 1. RewriteInstruction / recommendation 这条线不动架构，只做稳定化

虽然本次任务重点是 recommendation 回归，但实际修复只围绕“推荐结果不要被空掉”这条最小闭环做了收口：

- `build_evidence()` 对 `task_type` 做 Enum 兼容
- recommendation 的 `open_status` 归一化
- ranking 阶段在“全是 closed”的情况下保留候选，不把结果打空

### 2. recommendation ranking 的收口逻辑

`rank_candidates()` 现在按下面策略工作：

- 优先过滤掉 `failed_constraints`、`detail_failed`、`closed`
- 如果过滤后完全没有候选，再退回到“只排除硬失败”的列表
- 这样默认数据即使全是 closed，也不会把 `ranked` 直接变成空

这保留了现有测试语义：

- 有 open 候选时，closed 仍然会被移除
- 全 closed 时，不至于空结果

### 3. recommendation evidence 构建更稳

`evidence_builder.py` 里做了两项兼容：

- `task_type` 读取使用 Enum 兼容逻辑
- `open_status` 从 `open_status / is_open / open_status_text` 中归一化

这样 recommendation 分支能稳定生成：

- `ranking_snapshot`
- `last_recommendation_list`
- `comparison_matrix` 的推荐兼容壳

## `_h_rewrite` / RewriteInstruction 状态

本次没有改写 rewrite loop，也没有进入 ClaimVerifier 更高层。

`3a` 仍维持之前的收口状态：

- verifier failure 可以转成 rewrite 指令
- rewrite loop 不再是纯裸计数

这次稳定化没有触碰 rewrite 结构，只是让推荐结果不再因为 closed 过滤而把后续链路打空。

## `_h_rewrite` 修改说明

本次没有新增 `_h_rewrite` 逻辑，也没有引入新计数器。

原因很直接：

- 当前失败不是 rewrite 指令消费问题
- 根因是 recommendation evidence/ranking 的结果被空掉

因此这次保持 rewrite 层不动，只做 recommendation 排序稳定化。

## composer 覆盖矩阵

本次没有新增 composer，只验证现有 deterministic composers 仍正常：

- `DirectResponseComposer`
- `ClarificationComposer`
- `SystemFallbackComposer`
- `SingleShopFactComposer`
- `RecommendationComposer`
- `ComparisonComposer`
- `ExplorationPlanComposer`

验证结果：

- `local_life_agent/tests/test_llm_verbalizer.py -q` 通过
- `local_life_agent/tests/test_answer_verifier.py -q` 通过

## generator / verbalizer / composer 选择策略

本次没有改 generator 的大方向，只修了 recommendation evidence/ranking 的前置条件。

当前链路依然是：

`AnswerPlan / EvidencePack -> response policy -> LLM verbalizer or deterministic composer -> verifier -> rewrite instruction -> rewrite or fallback -> ResponseContractV1 / final_response`

这次修复后，推荐场景在默认数据下不会直接掉到空候选，从而：

- `final_response` 能保住推荐结果
- `preview_text` 和 `ResponseContractV1` 的推荐出口一致性不再被空列表破坏

## 与 `ResponseContractV1` / `final_response` 统一出口的衔接

本次修复没有改统一出口协议，只保证推荐证据侧能稳定产出候选：

- `ranking_snapshot.ranked` 不再被空掉
- `last_recommendation_list` 可写回 session
- 后续 `"第一家有券吗"` 能沿用推荐列表继续查券

所以统一出口仍然有效，且 recommendation 的 session 续接恢复正常。

## 实际修改文件清单

- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
- [`local_life_agent/planning/policies/ranking_policy.py`](D:/javacode/hm-dianping/local_life_agent/planning/policies/ranking_policy.py)

## 明确没有做的内容

本次没有进入以下后续阶段：

- Phase 5 第一层上下文与澄清边界
- `ContextualizedTurn`
- `FocusContext`
- `FocusResolver`
- ResponseContract V2
- Redis SessionStore
- ClaimVerifier L2 / L3
- `complex_orchestrator`
- MapReduce
- `graph_builder` 重构
- `planning_subgraph` 整体重写

## 测试结果

### 先前失败项

`local_life_agent/tests/test_recommendation_flow.py -q`

修复前失败 3 项：

- `test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
- `test_recommendation_ranking_score_is_recomputable`
- `test_after_recommendation_first_item_reference_works`

修复后：

- `17 passed, 2 xfailed`

### 相关回归

- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `python -m compileall local_life_agent`
- `python -m pytest local_life_agent/tests -q`

最终全量结果：

- `1349 passed, 37 skipped, 2 xfailed`

## 是否建议进入 Phase 5

建议进入，但前提是按既有节奏继续做下一阶段，而不是在本次收口里额外扩张上下文层。

当前 recommendation / comparison / exploration 的主链路已经稳定，Phase 5 可以在这个收口状态上继续推进第一层上下文与澄清边界。
