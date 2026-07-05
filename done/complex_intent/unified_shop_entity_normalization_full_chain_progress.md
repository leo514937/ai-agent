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

## 当前稳定结论

从当前仓库代码看，统一门店实体归一化已经切到主链路，但仍保留少量兼容入口和旧字段镜像。更准确地说：

- 主链路已经统一到 `ShopResolutionResult` / `ShopCandidate` / `ShopResolutionSource` / `ShopResolutionStatus`
- 归一化与别名解析已经由 `target/shop_resolver.py`、`target/shop_resolution_policy.py`、`domain/shop_entity.py` 承接
- 规划、确定性工具、状态写回、答案合成已经开始消费统一结果
- 旧逻辑没有彻底删除，而是以兼容包装和镜像字段形式保留，便于现有调用点平滑迁移

因此，这里不应写成“全部替换完成”，更稳妥的表述是：

- 主干链路已替换
- 兼容层仍存在
- 少数消费方仍需回归确认

## 本轮收口结果

### 已完成

- 推荐成功后不再把首个推荐商家静默写成 `current_shop`
- 推荐后的“这家有券吗”继续保持澄清，不再被误判为已选定单店
- 比较链路可以稳定读取 `last_recommendation_list`，包含“第二家/这三家”这类回指
- 比较后的“第二家有券吗”可以继续回到确定性单店券查询，并正常写回 `current_shop`
- `target/reference_resolver.py` 已补上对嵌套 `session_state_before / session_state` 的读取

### 仍保留兼容层

- `target/shop_resolver.py`、`core/candidate_core.py`、`engine/workflows/deterministic_tool_workflow.py` 仍保留 legacy 结果形态读取
- `domain/state.py` / `domain/graph_state.py` 的 meta 字段仍保留，用于兼容和回归观察
- `engine/graph_builder.py` 的兼容导出仍在

### 仍需后续清理

- 少数 legacy 字段镜像仍然存在，属于兼容期保留
- 若后续再收紧语义边界，可继续减少 `comparison_targets` 与 `last_recommendation_list` 的桥接路径

### 回归结果

- `python -m compileall local_life_agent` 通过
- 推荐 / 比较 / 单店 / 确定性工具核心回归通过
- 结构扫描未发现新增 workflow / MapReduce / RAG / 交易支付订座能力
- 本轮收口结果可视为“主链路已稳定，兼容层仍保留”

## 替换阶段看板

| 阶段 | 状态 | 说明 | 验收口径 |
|---|---|---|---|
| 1. 统一 schema / result 对象 | 已稳定 | `ShopResolutionResult`、`canonical_shop_entity`、候选和 trace 语义已统一，保留 legacy 镜像只为兼容 | 新旧字段能并存，且结果契约稳定 |
| 2. 归一化与别名层 | 已稳定 | `current_shop / active_shop / ordinal_reference / explicit mention / alias / generated_alias` 已进入同一解析边界 | 同一门店不会被多套规则重复解析 |
| 3. facade 接入 | 已稳定 | 单一 facade 已输出统一结果，旧接口以兼容包装保留 | 旧调用点不需要一次性全改 |
| 4. planning / deterministic tool 对接 | 已稳定 | 规划与确定性工具主消费路径已统一，回指恢复、比较引用和确定性单店券查询已回归；legacy 入口仍保留作兼容 | 单店多 facet 只解析一次 shop_id |
| 5. session writeback 约束 | 已稳定 | 写回只允许在 `resolved` 时更新 `current_shop` | 其他状态不应伪装成已解决 |
| 6. 推荐与证据链路修正 | 已稳定 | `ranking_snapshot` 已要求来自真实候选或 evidence，且推荐/比较后的回指恢复已稳定回归 | 禁止用门店实体 fallback 伪造排名 |
| 7. 回归测试与架构保护 | 已稳定 | 编译、核心单测和保护回归已通过，未引入新的 workflow / tool / MapReduce / RAG 路径 | 编译、单测和保护回归全部通过 |

## 当前已确认的替换方向

- 推荐场景不能再依赖硬编码 top-3 兜底
- 单店多 facet 不应再靠模糊匹配随便选店
- 有 `current_shop` 或唯一 resolved target 时，应优先进入确定性工具链路
- `pending_clarification` 只能在真正需要澄清时保留
- `session_write` 只在门店实体真正 resolved 后写入 `current_shop`

## 仍保留的兼容层 / 未彻底替换点

下面这些地方不是“没有接入统一边界”，而是“为了兼容现有调用，仍然保留旧入口或镜像字段”：

- `target/shop_resolver.py` 里的 `as_legacy_dict()` 和兼容返回形状
- `tools/db_tools.py` 与 `tools/java_client.py` 的旧工具适配路径
- `core/candidate_core.py` 里对 legacy `resolve_shop` 结果的解包与桥接
- `engine/workflows/deterministic_tool_workflow.py` 中仍存在对旧结果形态的兼容读取
- `domain/state.py` / `domain/graph_state.py` 里的 `current_shop_meta`、`last_recommendation_list_meta`、`pending_clarification_meta` 等兼容状态
- `engine/graph_builder.py` 暴露的兼容导出与测试回归入口

这些不应被理解为“主链路没替换”，而应理解为“旧接口仍在兼容期”。

## 里程碑判定

当以下条件同时满足时，可以认为全链路替换达到可接受状态：

1. 门店实体归一化边界有单一入口
2. 推荐链路的排名与证据来自真实数据，不靠实体 fallback
3. 单店多 facet 复用同一 `shop_id`
4. ambiguous / low_confidence / not_found 不会错误清空 pending
5. deterministic tool 不再维护第二套门店恢复逻辑
6. `session_write` 的写回条件与统一边界一致
7. 架构保护回归通过
8. 兼容层仍存在但不再承担主决策语义

## 进度更新规则

- 如果某条链路已经接入统一边界，但回归未通过，状态仍记为“进行中”
- 如果旧逻辑仍在并行存在，不能标记为“完成”
- 如果只是补了兼容包装，但没有真正切换消费方，也不能标记为“完成”
- 如果新增了字段或状态定义，优先更新本文件，再更新报告文件
- 如果主链路已统一，但兼容层仍保留，请标记为“已稳定”或“部分替换”，不要写成“全量替换完成”

## 备注

- 本文件是进度标记文档，不是最终设计文档
- 若后续边界字段或状态定义发生调整，应优先更新本文件中的进度表和完成判定
- 后续若要做阶段性验收，建议在本文件下方追加一段“已完成 / 阻塞 / 待回归”小节，而不是另起一套口径
