# Full Failure Chain Audit: Semantic Schema / Router / Geo Guard / Decision Planner

## 结论

本次审计确认：用户这条本地生活查询的失败不是单点故障，而是**语义 schema 失配、路由/恢复链路重复触发、位置守卫丢失、搜索范围外溢、DecisionPlanner 输出截断**共同叠加形成的连锁失败。

其中，以下三段是**已被日志和代码同时证实的真实问题**：

1. 语义解析阶段的 `preferences` / `ranking_policy` schema 与模型输出不一致，导致结构化解析先失败，再退回 diagnostic fallback。
2. `resolve_shop` 在恢复链路中被重复调用，且 `location` 在不同分支上出现 `{}` 与 `null` 交替，触发 schema 校验失败或空结果回退。
3. 在位置丢失或不稳定时，`search_shops` 退化为较宽泛的关键字检索，造成跨城市候选混入、`distance_km` 长期为 `null`。

此外，DecisionPlanner 的 LLM 输出被长度限制截断，导致 JSON 解析失败并触发 fallback，这不是主因，但会放大后续决策退化。

## 审计范围

本报告只做事实核查、最小复现和修复顺序设计，不做大范围代码改写。

明确不覆盖的动作：

- 不重写 `graph_builder`
- 不关闭 verifier / rewrite
- 不跳过后续证据审计
- 不用 hardcode 的城市、店名、距离、评分或优惠券兜底

## 失败链路总览

链路可以按下面顺序理解：

1. LLM 语义输出与 `SemanticFrame` 期望 schema 不一致
2. `intent_parser` 进入 fallback / recovery，部分槽位结构被弱化
3. router / recovery 链路重复触发 `resolve_shop`
4. `location` 在 `null` / `{}` 之间漂移，导致 schema 校验失败或空地理约束
5. `search_shops` 在缺少稳定位置时退化为宽泛 keyword 搜索
6. 候选列表出现跨城市结果，`distance_km` 仍为空
7. DecisionPlanner 由于 LLM JSON 截断失败，最终进入 deterministic fallback
8. 决策 review 继续报告缺少 `category` / `value_for_money`，暴露出“偏好”与“事实 facet”混淆的问题

## 事实核验

### 1. 语义 schema 失配是真问题

这是本次失败链路的起点之一。

证据：

- `local_life_agent/domain/schemas.py` 中，`SemanticFrame.preferences` 是 `list[dict[str, Any]]`，`ranking_policy` 是 `RankingPolicy | None`。
- `local_life_agent/domain/facets.py` 中，`RankingPolicy` 是结构化模型，不是字符串。
- `local_life_agent/llm/prompts/local_life_parser.md` 的输出示例仍写着 `"preferences": []` 和 `"ranking_policy": ""`，与真实 schema 不一致。
- `var/python_service.log` 记录了明确错误：
  - `LLM_ENUM_OUT_OF_RANGE`
  - `preferences.0 Input should be a valid dictionary ... got 'value_for_money'`
  - `ranking_policy Input should be a valid dictionary ... got ''`

判定：

- `preferences` 这条短标记被当成了 dict list 的元素，属于**真实 schema drift**。
- `ranking_policy` 被当成字符串，属于**真实 prompt / model contract drift**。

影响：

- 结构化语义解析失败后，后续的 location / preference / ranking 信号更容易进入恢复态或降级态。

### 2. resolve_shop 重复调用且 location 漂移是真问题

这是链路中的第二个真实故障点。

证据：

- `local_life_agent/target/shop_resolver.py` 的 legacy 入口会把参数归一化后再分发到 `resolve_shop`。
- `resolve_shop` 的输入要求 `location` 是 dict；`null` 会触发 schema 校验失败。
- `var/python_service.log` 中同一 trace 下出现重复 `resolve_shop` 调用，且参数在 `"location": {}` 与 `"location": null` 之间来回切换。
- 日志同时出现：
  - `SCHEMA_VALIDATION_FAILED`
  - `error_message=Argument 'location' must be a dict`
  - `SHOP_NOT_FOUND`

判定：

- 这不是“正常空结果”，而是**恢复链路对地理参数的守恒性不足**。
- 同一查询里反复走相似分支，说明存在 retry / recovery 反馈回路，没有在失败态上形成稳定收敛。

影响：

- 地理约束无法稳定传递到后续工具调用。
- `distance`、附近推荐、同城过滤等能力会被动失真。

### 3. 跨城市候选混入是真问题

这是位置守卫失效后的直接外显。

证据：

- `local_life_agent/planning/plans/execution_plan_builder.py` 在推荐场景主要生成 `search_shops`，但当 `location` 丢失时无法形成强地理约束。
- `local_life_agent/tools/db_tools.py` 的 `search_shops(query, location=None, limit=None)` 在没有 location 时会退化为 keyword 检索。
- `local_life_agent/tools/db_client.py` 的 keyword 搜索覆盖 name / address / type，容易跨城市命中。
- `local_life_agent/eval/reports/latest_eval_report.json` 中多处可见：
  - `distance_km: null`
  - 上海、深圳等地址混入候选
  - `resolver_tool_name: "search_shops"` 或 `"resolve_shop+search_shops"`

判定：

- 这是**真实的地理外溢**，不是仅仅“结果少”。
- 在当前位置不稳时，检索层没有足够强的城市 / 半径守卫，导致推荐质量明显下降。

影响：

- 候选集会混入无关城市商家。
- 后续 evidence / decision / answer 都会建立在错误候选上。

### 4. DecisionPlanner JSON 截断是真问题，但属于放大器

这不是起点，但会让失败继续扩大。

证据：

- `local_life_agent/planning/llm_utils.py` 统一使用 `max_retries=1`。
- `local_life_agent/llm/openai_backend.py` 硬编码 `max_tokens: 1024`。
- `var/python_service.log` 中 DecisionPlanner 两次尝试都出现 `LLM_JSON_PARSE_ERROR`，而 raw preview 明显截断在 `answerable_facets` 附近。
- 随后进入 `DECISION_PLANNER_FALLBACK`。

判定：

- 这是**真实的输出预算 / 截断问题**。
- 但它更像是“已经脆弱的链路被进一步放大”，不是最初那一跳的根因。

影响：

- 结构化决策无法稳定输出。
- fallback 决策更容易缺失 facet 级别信息。

### 5. value_for_money 被当成必需事实 facet，是 contract 问题

这是一条重要的伴随问题，不应误判成“缺了某个工具”。

证据：

- `local_life_agent/tests/test_llm_semantic_capability_usage_audit.py` 已经在约束 `value_for_money` 作为偏好信号，而不是单独比较意图。
- `local_life_agent/planning/evidence/evidence_planner.py` 的默认工具 facet 主要是 `distance`、`open_status`、`coupon` 等事实项，没有 `value_for_money` 工具映射。
- `local_life_agent/planning/evidence/evidence_builder.py` 的 facet contract 也主要围绕事实可验证项展开。
- `var/python_service.log` 中 `decision_review` 报告 `missing_required_facets: ['category', 'value_for_money']`。

判定：

- `category` 作为实体语义项可以是合理要求。
- `value_for_money` 更像**派生偏好或排序信号**，不应简单当作一个“必须有事实工具证据”的缺失项。

影响：

- Review 层容易把偏好与事实混为一谈。
- 这会让系统误以为“还缺工具”，但实际上缺的是 contract 分类。

## 最小复现

### 复现 1: 语义 schema 失配

输入类似：

- `推荐北京邮电大学附近的火锅或烧烤，要性价比高的`

可观察到：

- 语义解析先触发 `preferences` / `ranking_policy` 结构化解析错误
- 然后 fallback 到 diagnostic / recovery 路径

### 复现 2: resolve_shop 的 location 漂移

在同一 trace 中观察：

- `location: {}`
- `location: null`
- `SCHEMA_VALIDATION_FAILED`
- `SHOP_NOT_FOUND`

这说明恢复链路没有把地理参数稳定下来。

### 复现 3: 推荐结果跨城市

在 eval report 中检查 recommendation 样本：

- 候选地址跨多个城市
- `distance_km` 仍然为 `null`

这说明位置丢失后，检索层没有形成有效约束。

## 修复优先级

### P0: 先修 schema contract

优先收敛：

- `SemanticFrame.preferences`
- `RankingPolicy`
- `local_life_parser.md` 输出示例
- `intent_parser` 的 normalize / recovery 路径

目标是让“偏好信号”和“结构化 ranking policy”先进入一致的 contract，避免一开始就掉进 fallback。

### P1: 统一 location 守恒

优先修：

- legacy / modern `resolve_shop` 入参归一化
- recovery 链路中的 `location` 传递
- 重复调用时的去重或收敛条件

目标是避免 `null` / `{}` 在多个节点之间反复抖动。

### P2: 给推荐搜索补强 geo guard

优先修：

- `search_shops` 的地理约束输入
- 位置缺失时的明确降级语义
- 候选过滤中的跨城守门

目标是防止“附近推荐”退化成泛 keyword 搜索。

### P3: 处理 DecisionPlanner 输出预算

优先修：

- Prompt 压缩
- 输出 schema 精简
- token budget 调整
- 必要时增加更稳健的结构化重试策略

目标是减少 JSON 截断导致的 fallback。

### P4: 区分事实 facet 与偏好 facet

优先修：

- `value_for_money` 不要再按“必须有事实证据”的方式处理
- review 层要能区分 derived preference 与 factual facet

目标是避免错误地把排序偏好当成工具缺口。

## 不建议的动作

以下做法会掩盖问题，而不是修复问题：

- 直接 hardcode 北京 / 火锅 / 烧烤 / 距离 / 评分 / 优惠券
- 只修 `resolve_shop`，不修 semantic schema
- 只关掉 verifier 或 rewrite 让输出“看起来更稳定”
- 只修 DecisionPlanner 截断，不修 location 和 search 约束

## 验证建议

修复后至少应覆盖：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_semantic_parser.py -q`
- `pytest local_life_agent/tests/test_distance_facet_contract.py -q`
- `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
- `pytest local_life_agent/tests/test_llm_semantic_capability_usage_audit.py -q`

如果后续进入端到端回归，再加：

- 本地生活推荐场景的 e2e 用例
- 多店对比场景的 e2e 用例
- 位置缺失时的澄清回退用例

## 参考证据

- `D:/javacode/hm-dianping/local_life_agent/domain/schemas.py`
- `D:/javacode/hm-dianping/local_life_agent/domain/facets.py`
- `D:/javacode/hm-dianping/local_life_agent/llm/prompts/local_life_parser.md`
- `D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py`
- `D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py`
- `D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py`
- `D:/javacode/hm-dianping/local_life_agent/planning/plans/execution_plan_builder.py`
- `D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_planner.py`
- `D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py`
- `D:/javacode/hm-dianping/local_life_agent/planning/llm_utils.py`
- `D:/javacode/hm-dianping/local_life_agent/llm/openai_backend.py`
- `D:/javacode/hm-dianping/var/python_service.log`
- `D:/javacode/hm-dianping/local_life_agent/eval/reports/latest_eval_report.json`

## 审计备注

本报告只负责确认失败链路与修复顺序，不代表这些问题已经被修复。

