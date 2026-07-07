# Phase 8 / 5c precheck blocking report

## 结论
FAIL

## 前置门禁验收结果
本轮门禁未通过，原因是第 8 批要求的“当前全量测试没有遗留失败”不成立。

已确认的前序状态：

1. 5a-a 已完成。
2. 5a-b 已完成。
3. 5b 已完成，并通过回归。
4. recommendation / comparison / single_shop / coupon / e2e 主链路已通过。
5. `ResponseContractV1 / final_response` 当前没有显式 bypass 回退迹象。

但仍有残余失败存在，因此不能进入 5c。

## 修改前真实代码调研结果
根据当前仓库和报告状态：

1. 第 7 批 SessionStore 基础设施已落地：
   - `SessionStore` 接口
   - `InMemorySessionStore`
   - `RedisSessionStore`
   - 分区 TTL
   - Redis fallback
2. 第 6 批已完成最终收口：
   - `load_session` 拆分
   - target_resolve 权威归第二层
   - `planning_subgraph` 收缩为兼容编排层
3. 第 5 批前半段能力已稳定：
   - `ContextualizedTurn / FocusContext`
   - `ErrorEnvelope / EarlyResponseDirective`
   - `hard_guard / slot_extractor / active_turn_resolver` 边界收紧
   - `pending_clarification / clarification_request` 收敛

## 门禁不通过的直接原因
执行全量测试后，仍有 4 个失败，均属于当前仓库的遗留未收口项：

- `local_life_agent/tests/test_real_llm_acceptance.py::test_spy_e2e_query_2_comparison`
- `local_life_agent/tests/test_stage14_verification.py::test_group_deictic_size_parsing`
- `local_life_agent/tests/test_stage14_verification.py::test_resolve_deictic_reference_with_group`
- `local_life_agent/tests/test_stage14_verification.py::test_deictic_priority_clarification`

其中：

- `test_spy_e2e_query_2_comparison` 期望的 `answer_source` 与当前 `clarification_fallback_workflow` 不一致。
- 3 个 `stage14_verification` 用例是 group deictic / clarification 语义断言失败，`recover_context` 仍返回 `SIGNAL_ONLY` 而非测试期望的 `RESOLVED` / `NEED_CLARIFICATION`。

## 当前主链路状态
主链路门禁通过：

- recommendation flow
- comparison flow
- single coupon flow
- single shop multifacet
- e2e llm main path

所以阻塞点不是主链路崩坏，而是全量测试仍未清零。

## Trace / Eval / ResponseContract V2 为什么不能现在做
第 8 批要求门禁严格：

- “当前全量测试没有遗留失败”

现在不满足，所以不能进入：

- 三层 Trace schema 统一
- latency / cost benchmark
- ResponseContract V2 权威出口

否则会把已有遗留失败和第 8 批新增语义混在一起，后续排障会变得不清楚。

## 实际修改文件清单
本轮未修改业务代码，只新增阻塞报告：

- [`todo/three_layer_phase8_5c_precheck_blocking_report.md`](./three_layer_phase8_5c_precheck_blocking_report.md)

## 明确没有做的 5c 内容
未做：

- 三层 Trace schema 统一
- latency / cost benchmark
- ResponseContract V2

## 测试结果
已通过的门禁测试：

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`

全量测试结果：

- `python -m pytest local_life_agent/tests -q`
- 结果：`4 failed, 1368 passed, 37 skipped, 2 xfailed`

## 是否建议进入第 9 批
不建议。

当前第 8 批门禁不通过，应该先把上述 4 个残余失败分清是历史遗留还是需要单独修复，再考虑 5c。
