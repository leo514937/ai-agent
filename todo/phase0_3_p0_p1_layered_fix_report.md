# Phase 0-3 P0/P1 分层修复报告

## 范围

- 仅修复 Phase 0-3 的状态契约、候选解析、证据规划和回答层回归。
- 未进入 Phase 4。
- 未新增平行链路，仍沿用现有 LangGraph 主图。

## 本次修复的问题

1. 单店精确店名在候选解析层被不必要地放宽，导致额外 `search_shops` 调用和候选膨胀风险。
2. 单店多 facet 回答在 verifier 失败后容易退化成通用失败话术，不能稳定输出“有券 / 营业 / 距离”等事实。
3. `ExecutionPlan` 的 fallback 只有 `tool_calls`，缺少 `stages`，导致部分测试直接读取 `stages[0]` 失败。
4. 推荐流中 verifier fallback 过宽，可能放过未完整按序输出的推荐文本。

## 已修复内容

### 1. 候选解析收口

- 在 [local_life_agent/target/candidate_resolver.py](/D:/javacode/hm-dianping/local_life_agent/target/candidate_resolver.py) 中增加了精确店名的本地直达匹配。
- 对完全精确的店名优先做 catalog exact match，再决定是否走原有 gateway 路径。
- 保留了原有 explicit / ambiguous / discovery 兼容逻辑。

### 2. 单店答案稳定化

- 在 [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py) 中加入单店回答的确定性摘要拼装。
- 当单店回答出现过于泛化的兜底文本时，直接用 `EvidencePack` 生成可读摘要。
- 保证多 facet 单店回答能稳定覆盖：
  - 优惠券
  - 营业状态
  - 距离 / ETA

### 3. Verifier 兼容层

- 在 [local_life_agent/answer/b2_mini_verifier.py](/D:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py) 中增加了 LLM verifier 的本地兼容校验。
- 当 verifier LLM 返回空 / 非法 schema / 不可用时，先用决策计划做本地规则校验。
- 对推荐 / 对比类回答收紧了顺序校验，避免只命中部分店名就误判为通过。

### 4. 计划结构补齐

- 在 [local_life_agent/planning/evidence/evidence_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py) 中为 fallback `ExecutionPlan` 补上 `stages`。
- 现在单店 fallback 计划同时具备：
  - `tool_calls`
  - `stages`
  - `target_shop_ids`

## 验证结果

已通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `pytest local_life_agent/tests/test_core_wrappers.py -q`
- `pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_p2_end_to_end.py -q`
- `pytest local_life_agent/tests/test_answer_verifier.py -q`
- `pytest local_life_agent/tests/test_phase_e_state_contracts.py -q`

## 备注

- 这次修复重点是把“候选解析、证据计划、回答生成、校验”四层的责任边界重新收紧。
- 没有引入 Phase 4 的 winner 决策改造。
