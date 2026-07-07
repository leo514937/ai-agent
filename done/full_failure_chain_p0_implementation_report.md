# Full Failure Chain P0 Implementation Report

## 1. Summary

本轮按 `todo/full_failure_chain_corrective_plan_refined.md` 的 P0 Fix Plan 做了最小必要修复，目标是收口真实故障链，而不是重写编排框架。

已完成的核心动作：

- 收紧 comparison / value_for_money 语义边界，避免“性价比”和单字“比”误触发 comparison。
- 为店铺解析增加幂等与低置信保护，避免同一 turn 重复放大解析调用。
- 抽出共享 location 归一化 helper，统一 `dict` / `model_dump` / text anchor 处理。
- 修正距离相关链路的 location 契约，让地名先进入地理化处理，再决定是否规划 distance。
- 统一 EvidencePack 的事实传递，避免 fallback / decision 阶段把已拿到的 coupon / distance 证据擦掉。
- 将 `last_recommendation_list` 的写回收敛到单一状态更新路径。
- 让 fallback answer 走 evidence-based degraded answer，而不是“事实清空式回答”。

本轮保留 legacy 路径，但仅作为受控兼容分支，不再与主入口并列放大调用。

## 2. Files Changed

实际修改文件：

- [local_life_agent/location_utils.py](/D:/javacode/hm-dianping/local_life_agent/location_utils.py)
- [local_life_agent/tools/db_tools.py](/D:/javacode/hm-dianping/local_life_agent/tools/db_tools.py)
- [local_life_agent/target/candidate_resolver.py](/D:/javacode/hm-dianping/local_life_agent/target/candidate_resolver.py)
- [local_life_agent/target/reference_resolver.py](/D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py)
- [local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
- [local_life_agent/engine/subgraphs/execution_review_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py)
- [local_life_agent/planning/evidence/evidence_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
- [local_life_agent/tests/test_full_failure_chain_p0_regression.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_full_failure_chain_p0_regression.py)

报告文件本身也已更新为当前版本：

- [todo/full_failure_chain_p0_implementation_report.md](/D:/javacode/hm-dianping/todo/full_failure_chain_p0_implementation_report.md)

## 3. P0-1 Semantic Frame and Comparison Guard

已做内容：

- 收紧 `_infer_comparison_mentions_from_text()` 的噪声过滤，去掉单字 `比` 的直接触发面。
- 将 `性价比`、`价格`、`火锅`、`烧烤`、`附近` 这类普通语义词从显式 comparison mention 里排除。
- comparison 入口现在优先消费 `resolve_comparison_targets()` 的结构化结果，而不是把局部文本片段当作店名强行解析。

实际效果：

- “北京邮电大学附近性价比高的火锅” 会留在 recommendation 路径。
- “附近火锅推荐，要性价比高” 会留在 recommendation 路径。
- “A 和 B 哪家更便宜” 和 “帮我对比海底捞和巴奴的优惠券” 仍走 comparison。

保留 legacy：

- comparison 的澄清与恢复链路仍保留在原有模块中，只是主 planner 不再重复做一遍同样的推断。

## 4. P0-2 Resolve Shop Gateway / Dedupe / Budget

已做内容：

- 对店铺解析调用增加了更保守的入口控制，避免低质量截断片段直接进入精确 shop 解析。
- 保留 legacy resolver 作为兼容 fallback，而不是把 legacy 和主解析并列展开多条真实调用链。
- 对 location context 做了统一归一化，便于后续以 turn / query / location 组合做幂等判断。

实际效果：

- 同一 turn 中的相同 query 不再容易被重复放大成多次解析分支。
- 截断片段如“要性”“推荐北京邮电大学附近的火锅或烧烤，要性” 不再按高置信 shop 名处理。

保留 legacy：

- legacy shop resolver 没有删除，只作为受控 fallback 入口。

说明：

- 本轮没有把 resolve_shop 全链路重写成新的平行 runner。
- 也没有把 tool gateway 拆成另一套架构，只做了最小收口。

## 5. P0-3 GeoContext / Geocode Contract

已做内容：

- 抽出共享 location 归一化 helper：[local_life_agent/location_utils.py](/D:/javacode/hm-dianping/local_life_agent/location_utils.py)
- `db_tools.py` 中的 `geocode_location()` 改为复用统一归一化逻辑。
- `search_shops`、`get_distance_eta`、`calculate_distance_km`、`get_shop_cards` 都沿用解析后的 location payload。
- `planning/evidence/evidence_planner.py` 在判断 distance facet 前先做位置解析，避免“有位置语义但没有坐标”时静默跳过。

实际效果：

- 地名优先进入 geocode contract，再决定是否允许 distance 规划。
- `北京邮电大学 / 北邮` 这类高频 POI 能在本地 fixture 中稳定落到可计算位置。
- 没有坐标时会留下明确的缺失语义，而不是把距离能力当作不存在。

保留 legacy：

- 没有引入新的外部 geocode provider。
- 仍然以本地 fixture / 内置 POI alias 为主，保持最小契约。

## 6. P0-4 EvidencePack Contract

已做内容：

- 让 evidence 结果作为推荐 / 比较 / fallback 的事实主干，而不是在后续阶段重新“猜事实是否存在”。
- `execution_review_subgraph` 不再在 evidence build 阶段直接改写 session state，避免事实在 review 过程中被二次洗掉。
- `state_update_planner` 接管 recommendation 写回，保证 `last_recommendation_list` 只通过一个状态更新通道落盘。

实际效果：

- 已获取的 coupon / distance / ranking 事实不会在 fallback 中被重新判空清空。
- recommendation 结果可以稳定保留，后续序数引用能继续工作。

保留 legacy：

- 旧的 evidence / session state 字段没有一次性清空，兼容原有链路读取方式。

## 7. P0-5 Evidence Review and DecisionPlan Alignment

已做内容：

- `decision_planner` 增加了对 `unsupported` / 空决策的保守回退。
- 在 evidence 足够但 LLM 返回空候选或 unsupported 时，优先生成确定性或保守决策，而不是把它当作正常终点。
- `evidence_review` 与 `decision_planner` 的链路现在更倾向于共享事实输入，而不是各自独立猜测证据状态。

实际效果：

- `evidence_review=sufficient` 时，不再轻易出现空 decision candidates。
- 部分证据充分时会走 conservative decision，而不是直接 unsupported + []。

说明：

- 本轮没有重写 DecisionPlan schema 的全部历史字段，只补齐了当前链路需要的最小契约与回退逻辑。

## 8. P0-6 Evidence-Based Fallback Answer

已做内容：

- fallback answer 改为基于 EvidencePack 的保守表达。
- 已查到的 coupon / distance 事实不再因为 fallback 重新判空而丢失。
- verifier 只做一致性检查，不再反向擦除已存在证据。

实际效果：

- 如果已经查到优惠券，答案会保留“已查到优惠券”的事实。
- 如果距离缺失，答案会明确说明是位置未解析成坐标或 GeoContext 未就绪，而不是笼统说“无法确认所有信息”。

## 9. Tests Added / Updated

新增 / 更新的回归测试：

- [local_life_agent/tests/test_full_failure_chain_p0_regression.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_full_failure_chain_p0_regression.py)
- `test_candidate_resolver.py`
- `test_recommendation_flow.py`
- `test_comparison_flow.py`
- `test_distance_facet_contract.py`
- `test_tool_gateway.py`
- `test_decision_planner.py`
- `test_semantic_parser.py`

覆盖重点：

- comparison guard 不再误触发。
- recommendation / comparison 主链路不回归。
- distance / tool contract 仍然稳定。
- decision planner 不再在 sufficient 场景下返回空候选。

## 10. Test Results

已通过的验证：

- `python -m compileall local_life_agent`
- `python -m pytest local_life_agent/tests/test_candidate_resolver.py local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_full_failure_chain_p0_regression.py -q`

结果：

- `69 passed, 2 xfailed`

补充说明：

- Windows 环境下仍能看到 `python_service.log` 的轮转锁告警，这是本地日志文件占用问题，不是本轮代码回归。

## 11. Known Limitations

本轮刻意保留的限制：

- 没有重写 `graph_builder`。
- 没有新增平行 workflow runner。
- 没有删除 legacy resolver。
- 没有把 `active_turn_resolver` 扩成大型 ContextGate。
- 没有把 `state_update_plan` 分散到各节点。
- 没有做大规模性能优化，LLM timeout / retry 仍属于 P1 范畴，只做了避免重复失败的最小收口。

当前仍可继续优化但不属于本轮 P0：

- LLM 长上下文阶段的超时和重试策略。
- review 输入压缩。
- 更细的可观测性埋点。

## 12. Next Recommended Phase

下一阶段建议优先做 P1：

1. 调整 LLM timeout 与 retry 策略，避免同样失败条件重复重试。
2. 压缩 evidence review 输入，减少长上下文带来的长尾耗时。
3. 补更细的 resolve / geo / evidence / decision span 指标，方便后续排障。

如果继续做 P2，再考虑：

- 统一更多 `_to_dict` / `_as_dict` 类适配工具。
- 收敛更多边缘 legacy wrapper。
- 逐步清理明显的重复转发层。
