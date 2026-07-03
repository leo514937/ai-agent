# 统一门店实体归一化边界：全链路替换进度

## 文档用途

本文件只用于标记“统一门店实体归一化边界”的全链路替换进度，不替代设计文档，也不扩大架构改动范围。

它要回答的只有四件事：

1. 哪些链路已经接入统一边界
2. 哪些链路仍在保留旧逻辑
3. 哪些回归已经通过
4. 哪些地方还不能宣称完成

## 范围约束

- 不重写 `graph_builder`
- 不新增 workflow runner
- 不新增 workflow
- 不引入 workflow-level MapReduce
- 不让 LLM 直接决定门店实体最终归一化结果
- 不允许多个链路各自维护第二套门店恢复逻辑
- 推荐、对比、单店问答、优惠券、营业状态、距离等链路要尽量共享同一份 canonical shop entity

## 统一边界定义

统一边界的核心输出以 `ShopResolutionResult` 为准，至少要承载：

- `status`
- `needs_clarification`
- `canonical_shop_entity`
- `candidate_entities`
- `resolution_reason`
- `source`

硬约束已经明确：

- `status` 只允许表示门店归一化结果
- `needs_clarification` 必须是独立布尔值
- `resolved / ambiguous / not_found / low_confidence / no_mention` 不能混用
- 只有 `resolved` 才能写 `current_shop`
- `ambiguous / low_confidence / not_found` 不能静默清空 `pending_clarification`

## 替换阶段看板

| 阶段 | 状态 | 说明 | 验收口径 |
|---|---|---|---|
| 1. 统一 schema / result 对象 | 进行中 | 建立 `ShopResolutionResult`、`canonical_shop_entity`、候选和 trace 的统一语义 | 新旧字段能并存，且结果契约稳定 |
| 2. 归一化与别名层 | 进行中 | 把 `current_shop / active_shop / ordinal_reference / explicit mention / alias / generated_alias` 纳入同一解析边界 | 同一门店不会被多套规则重复解析 |
| 3. facade 接入 | 进行中 | 用单一 facade 输出统一结果，保留对旧接口的兼容包装 | 旧调用点不需要一次性全改 |
| 4. planning / deterministic tool 对接 | 进行中 | 规划与确定性工具只消费统一结果，不再各自恢复门店 | 单店多 facet 只解析一次 shop_id |
| 5. session writeback 约束 | 进行中 | 写回只允许在 `resolved` 时更新 `current_shop` | 其他状态不应伪装成已解决 |
| 6. 推荐与证据链路修正 | 进行中 | `ranking_snapshot` 只能来自真实候选或 evidence | 禁止用门店实体 fallback 伪造排名 |
| 7. 回归测试与架构保护 | 待验证 | 保持现有主链路不变，同时验证新的边界约束 | 编译、单测和保护回归全部通过 |

## 当前已确认的替换方向

- 推荐场景不能再依赖硬编码 top-3 兜底
- 单店多 facet 不应再靠模糊匹配随便选店
- 有 `current_shop` 或唯一 resolved target 时，应优先进入确定性工具链路
- `pending_clarification` 只能在真正需要澄清时保留
- `session_write` 只在门店实体真正 resolved 后写入 `current_shop`

## 里程碑判定

当以下条件同时满足时，可以认为全链路替换达到可接受状态：

1. 门店实体归一化边界有单一入口
2. 推荐链路的排名与证据来自真实数据，不靠实体 fallback
3. 单店多 facet 复用同一 `shop_id`
4. ambiguous / low_confidence / not_found 不会错误清空 pending
5. deterministic tool 不再维护第二套门店恢复逻辑
6. `session_write` 的写回条件与统一边界一致
7. 架构保护回归通过

## 进度更新规则

- 如果某条链路已经接入统一边界，但回归未通过，状态仍记为“进行中”
- 如果旧逻辑仍在并行存在，不能标记为“完成”
- 如果只是补了兼容包装，但没有真正切换消费方，也不能标记为“完成”
- 如果新增了字段或状态定义，优先更新本文件，再更新报告文件

## 备注

- 本文件是进度标记文档，不是最终设计文档
- 若后续边界字段或状态定义发生调整，应优先更新本文件中的进度表和完成判定
- 后续若要做阶段性验收，建议在本文件下方追加一段“已完成 / 阻塞 / 待回归”小节，而不是另起一套口径
