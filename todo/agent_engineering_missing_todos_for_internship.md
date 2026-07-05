# Agent 工程能力补充 TODO（P18-P26）

## 总结

这份文档是在当前仓库 `ai-agent` 的 `toolcall` 相关分支基础上，对已有 `todo/complex_intent_query_architecture_stabilization_plan.md` 的补充，而不是替代。

现有 P0-P17 已经覆盖了主流程稳定性、路由优先级、facet 保留、EvidencePack / DecisionPlan / AnswerPlan / AnswerVerify、SessionState 写回安全、复杂 query 测试矩阵、exploration_planning 协议同构、EvidenceReview 退化与回退、EvidencePlanner 能力预算、SSE / trace / metrics、Deadline / Budget / Freshness / TTL、Prompt 版本管理、Java API 契约校验、图级错误边界，以及冻结 workflow 级 Map-Reduce、万能 ReAct、交易/预约/支付等方向。

本补充文档只关注“对 Agent 开发能力很重要，但当前 P0-P17 没有单独成项”的工程议题，重点面向实习项目展示，强调协议、测试、可观测性、可回放性、恢复能力、运行时语义和调试体验，而不是推荐系统、交易系统或本地生活产品闭环。

## 与现有 P0-P17 的关系

这份补充 TODO 的定位是“工程护栏”和“研究型 Agent 能力增强”，与 P0-P17 的关系是并列补充，不是重新排序，也不是替换。

P18-P26 不改变现有 P0-P17 的优先级，不重写 `graph_builder`，不引入新的主 workflow，不引入 workflow 级 Map-Reduce，不引入交易/预约/支付，不引入大规模推荐模型，也不把离线工程能力包装成新的业务功能。

它们主要补足以下空白：

1. 工具治理协议还不够完整。
2. 工具调用缺少可复现的 record-replay 夹具。
3. LLM 结构化输出失败缺少统一恢复链路。
4. 节点级 model routing / fallback / cost control 还没有单独成项。
5. 复杂 query 缺少一键调试快照。
6. 评估维度还停留在测试 case 层，没有形成 Agent rubric。
7. 多轮上下文压缩还没有系统化边界。
8. 运行时取消、超时、部分结果语义没有单独固化。
9. 缺少本地生活场景下的分层长期记忆协议：当前项目已有 SessionState 短期业务状态，但还没有跨 session 的长期显式用户偏好记忆，也没有明确 SessionState、显式偏好、行为归纳记忆、检索/排序记忆之间的边界。

## P15-P17 进一步补充

下面三项虽然已经属于现有主方案中的后续必做工程项，但它们同样是面向 Agent 开发能力的重要补充，这里一并纳入本 TODO，避免阅读时散落在别处。

### P15 LLM 提示词质量与 prompt 版本管理（后续必做工程项）

**说明：** 本轮架构方案只关注结构性不变量和协议收敛，不解决 LLM prompt 层的问题。但这是决定系统输出准确性的**第一因素**，通常比任何结构性不变量的影响更大。

每个 turn 调用 5+ 次 LLM（`hard_guard → top_intent_router → semantic_parse → goal_planner → decision_planner → answer_generate`），提示词分散在各 planner 和 router 文件中。LLM 版本升级、prompt 修改都可能导致同一 facet 语义漂移，比如 `coupon` 和 `voucher` 的解析结果不一致。

**当前实现现状：**

- `local_life_agent/llm/client.py` 已经提供 `load_prompt()`，并在调用层记录 `prompt_hash` / `system_prompt_hash` / `prompt_version`。
- `local_life_agent/planning/llm_utils.py` 已经把 prompt 拆成 `load_two_part_prompt()`，并记录 user/system prompt hash，说明 prompt 已经不是纯 inline 形态。
- `local_life_agent/tests/test_prompt_contract.py` 已经在检查 prompt 文件存在、`## System Prompt` / `## User Prompt` 结构、以及外部文件加载。
- 现有 prompt 文件包括 `top_intent_router.md`、`local_life_parser.md`、`tool_planner.md`、`goal_planner.md`、`evidence_planner.md`、`evidence_sufficiency_review.md`、`decision_planner.md`、`answer_verbalizer.md`、`answer_verifier.md`。

**建议的落地方式：**

- 建一个轻量的 prompt inventory/manifest，列出 `prompt_name`、负责人、使用节点、输入 schema、输出 schema、是否属于关键路径。
- 继续保留外部 `.md` prompt 文件作为唯一来源，不把完整 prompt 再写回 Python 常量里。
- 只要 prompt 文件内容变化，`prompt_version` / `prompt_hash` 必须变化，并在日志和 trace 中可追踪。
- 把 prompt 变更和回归测试绑定：`top_intent_router`、`local_life_parser`、`goal_planner`、`decision_planner`、`answer_verifier`、`answer_verbalizer` 这些关键节点都要有对应的最小回归集。
- LLM 版本升级不要直接改生产 prompt 结构，先跑固定 eval / golden trace / prompt diff review，确认 facet 语义没有漂移，再切版本。

**建议：**

- prompt 版本化 + 回归触发机制（prompt 变更自动跑相关测试）
- prompt diff review 流程
- 定期评估 LLM 版本升级对语义提取的影响

**验收标准：**

- 每个关键 prompt 都能在日志里看到稳定的 `prompt_version` / hash。
- prompt 文件改动能自动触发相关节点的回归测试。
- prompt diff review 能指出“哪一类语义可能被改坏”，而不是只看文本 diff。
- LLM 升级前后，facet 解析与 verifier 通过率不能无声退化。

**建议测试用例：**

- `top_intent_router.md` 修改后，`chat/capability/local_life/unsafe/out_of_scope` 分类回归必须重跑。
- `local_life_parser.md` 修改后，`coupon / open_now / distance / comparison_targets` 的解析用例必须重跑。
- `answer_verifier.md` 修改后，必须重跑“unknown 不应被判 false”和“unsupported winner 必须失败”的契约测试。
- 用 mock backend 固定输出，验证 prompt 内容变化会改变 `prompt_hash` 但不破坏 schema 兼容性。

**对应代码事实：**

- `D:\javacode\hm-dianping\local_life_agent\llm\prompts\`
- `D:\javacode\hm-dianping\local_life_agent\llm\llm_client.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\llm_utils.py`
- `D:\javacode\hm-dianping\local_life_agent\tests\test_prompt_contract.py`

**与现有 P0-P17 的关系：** 这是对 P1/P2/P4/P6/P9/P11 的横向补强。P15 不改变路由、协议或状态边界，只负责把 prompt 层变更纳入版本化和回归控制，避免语义漂移。

### P16 Java API 契约校验（后续必做工程项）

**说明：** Python 侧工具 `db_tools.py` / `java_client.py` 依赖 `src/` Java 后端接口格式。如果后端返回值字段变更，比如 `coupon_list` 改名为 `deals`，Python 解析可能静默返回空列表，进而让 `EvidencePlanner` 标记为 `unknown_facets`，最后用户只看到“暂无法确认”。

当前无入站 schema 校验，格式不匹配就会变成静默降级。

**当前实现现状：**

- `local_life_agent/tools/java_client.py` 已经维护了 `JAVA_TOOL_ENDPOINTS`，工具到 Java REST 路径的映射是集中式的。
- `JavaToolClient.call()` 已经能把 4xx / 5xx 显式翻成失败/未知结构，而不是直接把 HTTP 错误吞掉。
- `local_life_agent/tools/db_tools.py` 负责把数据库/Java 返回映射成业务工具结果，说明当前契约问题已经影响到工具层。
- `local_life_agent/domain/schemas.py`、`local_life_agent/domain/evidence.py`、`local_life_agent/answer/answer_plan_builder.py` 已经在消费 `unknown_facets` / `failed_facets`，所以契约问题会直接流向答案质量。

**建议的落地方式：**

- 把每个 Java 工具的入站/出站 payload 定义成 Python Pydantic schema，而不是只依赖“能解析成 dict”。
- schema 校验应当放在工具适配层或 ToolCallGateway 边界，失败要显式标记为 `failed`，不要静默变成空数据。
- 对 Java endpoint 返回做最小 contract snapshot：保存代表性响应样例和字段列表，作为 CI 的固定检查集。
- 对高频工具（`resolve_shop`、`search_shops`、`get_shop_detail`、`get_coupon_list`、`check_open_status`、`get_distance_eta`、`get_shop_cards`、`get_shop_review_summary`、`get_deal_list`）优先补 schema 和 fixtures。
- 当 Java 后端字段改名或缺字段时，先 fail tool，再由 `EvidenceReview` 决定 degrade / clarify / fallback，而不是让用户看到“静默 unknown”。

**建议：**

- Tool result 入站 Pydantic schema 校验
- 格式异常显式 fail tool，标记 `failed_facets`，不走静默空
- Java 侧 + Python 侧建立接口契约文档，纳入 CI

**验收标准：**

- 每个 Java 工具都能用 schema 明确表示期望响应结构。
- 字段改名或缺失会触发显式失败，而不是被误判为“没数据”。
- CI 能在接口契约变更时提醒相关工具和测试同步更新。
- `unknown_facets` 只用于真实“不知道/查不到”，而不是契约漂移造成的假 unknown。

**建议测试用例：**

- 模拟 `coupon_list -> deals` 这种字段改名，验证工具直接失败并标记 `failed_facets`。
- 模拟缺少 `shop_id` / `shop_name` / `rating` 等核心字段，验证 schema 校验报错路径。
- 模拟 4xx / 5xx 响应，验证 `JavaToolClient` 返回的错误形态进入工具失败分支。
- 用固定 JSON fixture 回归 `get_coupon_list`、`check_open_status`、`get_distance_eta` 的字段兼容性。

**对应代码事实：**

- `D:\javacode\hm-dianping\local_life_agent\tools\db_tools.py`
- `D:\javacode\hm-dianping\local_life_agent\tools\java_client.py`
- 后端接口：`D:\javacode\hm-dianping\src\main\java\com\hm\dianping\controller\`

**与现有 P0-P17 的关系：** 这是对 P4/P5/P8 以及原 P16 主题的补强。它不改变工具治理主流程，而是把 Java/Python 接口契约显式化，避免隐式空结果污染证据链。

### P17 图级错误边界（后续必做工程项）

**说明：** 当前 `graph.invoke()` 没有统一异常处理。子图异常会直接传播到顶层调用者，缺少统一 degradation 路径。P1 的单 dispatch 不变量覆盖了正常路径，但没有覆盖异常路径。

**当前实现现状：**

- `local_life_agent/agent.py` 是顶层执行入口，`run_agent_graph()` 负责构造初始 state 并调用 `graph.invoke()`。
- `local_life_agent/app.py` 在流式接口里又包了一层线程安全和 `try/except`，说明最外层已经意识到异常需要收口，但这还不等于图级统一错误边界。
- `local_life_agent/engine/graph_builder.py` 已经有图构建验证逻辑和 route 检查，但它更像构图完整性检查，不是运行时异常收口。
- 现有路由表里已经存在 `fallback_answer`、`clarification_fallback`、`degrade` 等结构化出口，所以错误边界应该复用这些受控路径，而不是抛原始异常。

**建议的落地方式：**

- 在 `run_agent_graph()` 或其上层增加统一的 safe invoke envelope，把 `build_graph()`、`graph.invoke()`、最终结果归一化这三段分开捕获。
- 按异常类型分层映射：构图失败、节点执行失败、LLM/工具失败、序列化失败、用户取消、未知错误。
- 统一把异常转成结构化 state / debug 信息，包括 `error_code`、`fallback_reason`、`failed_node`、`recoverable`、`trace_id`。
- 不要让异常直接透传到 HTTP 层或调用方；如果必须报错，也应先落到 `clarification_fallback` / `fallback_answer` / degrade answer。
- 流式接口里要同步区分“已取消”“已失败”“已降级完成”，避免前端拿到半路异常却不知道最终状态。

**建议：**

- `graph_builder` 增加 try/except wrapper
- 所有子图异常映射到结构化 fallback（`clarification_fallback` 或降级回答）
- 不允许原始异常直接传播给调用方

**验收标准：**

- `graph.invoke()` 的任何异常都能被收口成结构化失败或降级结果。
- 调用方不会看到未处理 Python traceback 作为业务响应。
- `trace` / `debug` 中能定位异常发生的层级和节点。
- 如果异常可恢复，系统应优先走明确的 fallback / clarify，不应直接终止 turn。

**建议测试用例：**

- mock 一个节点抛异常，验证最终响应变成结构化 fallback，而不是直接炸掉。
- mock `graph.invoke()` 抛异常，验证 `run_agent_graph()` 仍返回可解释的 `AgentResponse`。
- mock 流式接口在中途异常，验证状态为 failed / cancelled / degraded 之一，而不是悬空。
- 验证构图校验失败时输出的是可定位的 build error，而不是不透明 crash。

**对应代码事实：**

- `D:\javacode\hm-dianping\local_life_agent\agent.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`
- `D:\javacode\hm-dianping\local_life_agent\app.py`

**与现有 P0-P17 的关系：** 这是对 P1/P8/P12 的补强。P17 不改变 graph 结构和主路由，只负责把异常收口成可控的 fallback / degrade 路径，避免顶层直接炸掉。

## P18 Tool Governance / Permission / Idempotency

**背景问题：** 当前 `ToolCapabilitySpec` 更偏向描述 `supported_facets`、`required_inputs`、`timeout`、`failure`、`retryable`，但还不足以表达工具是否只读、是否可重试、是否需要确认、是否允许预览、是否允许并行、是否包含敏感字段等治理语义。对 Agent 来说，这类元数据不是“锦上添花”，而是工具编排能否安全扩展的基础。

**为什么对 Agent 开发重要：** Agent 的核心风险不只在“能不能调用工具”，还在“该不该调用、能不能重复调、能不能并行调、能不能在预览里调、失败后是否能自动重试”。治理协议越清晰，planner、validator、reviewer 的职责越清楚，Agent 才能在不依赖硬编码规则的情况下扩展工具集。

**当前项目可能的缺口：** 现有 read-only 工具占主导，但工具能力描述还没有把 `tool_side_effect`、`idempotency_key_required`、`safe_to_retry`、`requires_user_confirmation`、`permission_scope`、`sensitive_fields`、`cacheable`、`cost_level`、`max_qps`、`allowed_in_preview`、`allowed_in_parallel` 这些字段明确纳入 schema 或文档约束。

**建议的最小实现范围：** 只补 schema / 文档 / 测试建议，不重构工具系统本身。新增一个治理层的 `ToolGovernanceSpec` 或等价字段集合，先覆盖 read-only 工具；未来如果出现 mutation tool，再要求经过 confirmation gate，但本阶段不实现 mutation 能力。

**非目标 / 不要做什么：** 不引入交易/预约/支付，不做复杂权限系统，不做真实 idempotency 事务层，不重构 ToolRegistry，不把治理协议和业务逻辑耦合成 if/else。

**验收标准：** 任何工具都能清晰表达是否只读、是否可缓存、是否可并行、是否允许预览、是否允许重试、是否需要确认、是否敏感、是否有成本等级；文档必须明确 mutation tool 的未来门禁，但本阶段不出现 mutation 工具。

**建议测试用例：** 设计 read-only 工具的治理 schema 校验用例；设计“允许预览但不允许最终写回”的工具声明用例；设计“允许并行但不允许重试”的工具声明用例；设计“敏感字段必须脱敏记录”的元数据测试。

**与现有 P0-P17 的关系：** 这是对 P8/P9/P10/P12 的补强。P8 负责证据不足迭代，P9 负责 planner 生成能力，P10 负责性能与并行，P12 负责预算与时效；P18 则补齐工具层治理元数据，不重复这些主线。

## P19 Tool Call Cassette / Replay Harness

**背景问题：** 复杂 Agent 问题最难复现的部分不是单步逻辑，而是“LLM 决策 + 工具 I/O + 状态写回 + 证据合成”这一整条链路。没有 record-replay 夹具，很多回归只能靠线上偶现或手工重跑，调试成本会非常高。

**为什么对 Agent 开发重要：** Agent 的正确性经常依赖时序和状态。Cassette 可以把工具返回固定住，让我们验证“同一输入在固定工具结果下是否得到稳定决策”，这对回归测试、调试、面试展示都很关键。

**当前项目可能的缺口：** 目前已有 golden trace，但它更偏状态演化验证；还缺一种能固定 `tool_results` 的离线回放夹具，也缺对 `orchestration_decision`、`execution_plan`、`tool_calls`、`tool_results`、`evidence_pack`、`decision_plan`、`answer_plan`、`state_update_plan`、`final_response` 的整体串联记录。

**建议的最小实现范围：** 只做测试夹具，不接真实线上录制系统。定义 cassette JSON 结构，能记录 query、session_state_before、orchestration_decision、execution_plan、tool_calls、tool_results、evidence_pack、decision_plan、answer_plan、state_update_plan、final_response，并支持离线回放。

**非目标 / 不要做什么：** 不做复杂 A/B，不接线上埋点录制平台，不做多版本比较平台，不把 cassette 变成生产环境数据采集系统。

**验收标准：** 离线测试可通过 cassette 固定工具输出并回放整条决策链；至少有 3 条样例 cassette：复杂推荐、多店对比、单店多 facet 工具失败；cassette 和 golden trace 的职责边界必须写清楚。

**建议测试用例：** 相同 cassette 多次回放结果一致；固定不同 tool_results 时，decision 和 answer 随证据变化但状态写回规则不漂移；工具失败 cassette 能稳定进入 degrade 或 clarification。

**与现有 P0-P17 的关系：** 这是对 P6/P11 的补充。P6 管复杂 query 测试矩阵，P11 管 observability / metrics / streaming；P19 关注“离线固定工具 I/O 的复现能力”，不替代 trace，也不替代测试矩阵。

## P20 Structured Output Recovery

**背景问题：** LLM 的结构化输出在真实环境中经常出错，常见问题包括 JSON parse error、schema validation error、missing required field、invalid enum、wrong type、extra hallucinated field、partial output。只要关键节点一处解析失败，就可能把整条 graph 卡死。

**为什么对 Agent 开发重要：** Agent 依赖很多结构化对象协作运行，比如 OrchestrationDecision、SemanticFrame、GoalPlan、ExecutionPlan、DecisionPlan、AnswerPlan、StateUpdatePlan。若没有统一恢复策略，LLM 稳定性问题会直接变成系统级不可用问题。

**当前项目可能的缺口：** 当前还没有把“parse → schema validate → normalize/coerce → repair once → fallback rule template → clarification/direct fallback”固化成明确协议，也没有把 parse_error_type 和 fallback_reason 做结构化记录。

**建议的最小实现范围：** 不让解析异常直接中断 graph；对关键 LLM 输出对象统一加恢复链路；每类对象都走同一套恢复流程，并在失败时结构化记录原因和 fallback 路径。

**非目标 / 不要做什么：** 不要无限重试，不要做多轮自动修复风暴，不要把所有错误都吞掉，不要让 fallback 变成新的隐式业务逻辑。

**验收标准：** 人工构造异常 LLM 输出样例时，系统能按预期进入 repair 或 fallback；关键对象的失败都会被结构化记录；解析失败不会把 graph 直接打断。

**建议测试用例：** 非法 JSON；字段缺失；枚举值错误；类型错误；多余幻觉字段；半截输出；repair 一次失败后进入 rule template 或 clarification 的样例。

**与现有 P0-P17 的关系：** 这是对 P1/P4/P17 的补强。P1 管单主流程不变量，P4 管 Evidence/Decision/Answer 协议，P17 管图级错误边界；P20 专注 LLM 结构化输出恢复，不替代这些边界。

## P21 Model Routing / Fallback / Cost Control

**背景问题：** Agent 的不同节点对模型能力和延迟的需求并不一样。路由器、语义解析、规划器、回答器、验证器，不应该都默认同一个 model profile，否则要么成本过高，要么速度过慢，要么弱节点用强模型浪费资源。

**为什么对 Agent 开发重要：** 节点级 model routing 是把“能跑”变成“可长期运营”的关键一步。简单节点可以走 fast_model，复杂决策或验证节点可以走 strong_model，节点失败后还能通过 fallback strategy 降级到规则模板或澄清。

**当前项目可能的缺口：** 现有文档已经有 prompt 版本管理和预算概念，但还没有单独定义 `primary_model`、`fallback_model`、`timeout_ms`、`max_retries`、`fallback_strategy` 这种节点级模型策略，也没有对 hard_guard、top_intent_router、semantic_parse、goal_planner、decision_planner、answer_generate、answer_verify 做建议 profile。

**建议的最小实现范围：** 只在文档和测试建议层定义节点级 profile，不接真实多模型平台。先写清楚每个节点推荐用什么 profile，再决定后续是否需要配置化。

**非目标 / 不要做什么：** 不接真实多模型平台，不改业务逻辑，不把 model routing 和业务路由混在一起，不引入复杂动态计费。

**验收标准：** 文档里每类节点都有明确的建议 profile；profile 至少覆盖 primary_model / fallback_model / timeout_ms / max_retries / fallback_strategy；超时后能落到规则模板或 clarification。

**建议测试用例：** 简单路由节点走 fast_model 的配置样例；验证节点走 strong_model 的配置样例；模型超时后 fallback 到规则模板；模型失败后进入 clarification。

**与现有 P0-P17 的关系：** 这是对 P8/P9/P10/P12 的补充。P8 负责降级策略，P9 负责 planner 能力边界，P10 负责体验和性能，P12 负责预算；P21 只补节点级 model 策略，不替代这些机制。

## P22 Agent Run Snapshot / Debug Bundle

**背景问题：** 复杂 query 的调试常常需要同时查看 query、normalized_query、session_state_before、semantic_frame、orchestration_decision、workflow_name、execution_plan、tool_calls、tool_results、evidence_pack、decision_plan、answer_plan、verification_result、state_update_plan、session_state_after、final_response、trace_spans、errors。如果这些信息散落在多个日志和 trace 里，排查成本会很高。

**为什么对 Agent 开发重要：** 一键 debug bundle 是把 Agent 开发从“看日志猜问题”升级到“拿一个完整 run 包快速定位问题”的关键工具，也很适合面试展示，能直接体现工程化能力。

**当前项目可能的缺口：** 现有 trace / metrics 更偏在线可观测性，还缺一个面向本地调试与展示的完整 run 快照导出能力，并且需要注意隐藏敏感字段。

**建议的最小实现范围：** 定义 debug bundle JSON schema，支持导出一次复杂 query 的完整快照；包含全部关键阶段对象；对敏感字段做脱敏或裁剪；示例中展示一个复杂 query 的完整 bundle。

**非目标 / 不要做什么：** 不替代 P11 trace/metrics，不做完整在线告警系统，不保存长期个人数据，不做跨会话隐私画像。

**验收标准：** 能给出 debug bundle JSON schema 示例；能给出复杂 query 示例；bundle 中关键对象齐全，敏感字段隐藏正确。

**建议测试用例：** 复杂推荐查询的完整 bundle；多店对比查询的完整 bundle；单店多 facet 且包含工具失败的完整 bundle；敏感字段脱敏检查。

**与现有 P0-P17 的关系：** 这是对 P11/P13 的补充。P11 关注 trace、metrics、streaming，P13 关注状态类型收敛；P22 关注“每次 run 的可导出快照”，不替代在线观测，也不要求全量迁移。

## P23 Agent Evaluation Rubric

**背景问题：** 现在很多测试只回答“对不对”，但 Agent 开发需要更细的评估维度，例如路由是否正确、facet 是否找全、目标是否解析对、工具计划是否合理、证据是否扎实、是否有不支持的断言、澄清是否恰当、状态写回是否正确、答案是否有帮助、延迟是否落在可接受区间。

**为什么对 Agent 开发重要：** 没有 rubric，就很难把“看起来差不多”的答案和“真的更好”的答案区分开。Rubric 能支撑 200+ 离线评测集，也能支撑少量人工评测或 LLM-as-judge 评测。

**当前项目可能的缺口：** 现有测试矩阵偏 case 驱动，还没有把评价维度系统化成评分 JSON schema，也没有明确各维度的分值或判断方式。

**建议的最小实现范围：** 定义评分 JSON schema，并明确至少包含 `route_correctness`、`facet_recall`、`facet_precision`、`target_resolution_correctness`、`tool_plan_correctness`、`evidence_grounding`、`unsupported_claim_rate`、`clarification_correctness`、`state_update_correctness`、`answer_helpfulness`、`latency_bucket`。

**非目标 / 不要做什么：** 不建设线上 A/B 平台，不把 rubric 变成复杂业务 KPI 仪表盘，不把离线评分和生产路由强绑定。

**验收标准：** 能给出评分 JSON schema；能给出 3 条 query 的评估样例；同一 query 能按多个维度分别打分，而不是只给单一总分。

**建议测试用例：** 一条推荐查询、一条多店对比查询、一条单店多 facet 查询，分别产出评分样例；对路由错误、证据不足、错误澄清、状态污染等情况给出差异化评分。

**与现有 P0-P17 的关系：** 这是对 P6/P11/P13 的补充。P6 管 case 集，P11 管观测，P13 管类型收敛；P23 则把“怎么评好坏”单独成体系，不替代测试矩阵。

## P24 Context Packing / History Compression

**背景问题：** 多轮对话会让上下文快速膨胀。若所有历史都原样进入 prompt，不但成本高，还会污染当前 turn 的决策；但若压缩过度，又会丢掉引用消解、候选列表和证据回查所需的信息。

**为什么对 Agent 开发重要：** Agent 的长期稳定性很大程度取决于上下文管理。Context packing 需要明确哪些历史进入 prompt，哪些只放 SessionState，哪些通过 `evidence_ref` 回查，才能既省 token 又保留推理连续性。

**当前项目可能的缺口：** 目前还没有系统化定义结构化 SessionState、自然语言历史摘要、证据引用三者的分工，也没有把 `last_recommendation_list`、大工具结果、过期状态的压缩规则写成明确协议。

**建议的最小实现范围：** 保留结构化 SessionState 作为主要上下文；`last_recommendation_list` 只保留 `shop_id` / `rank` / `evidence_ref` / short reason；大型 tool_results 不直接塞 prompt，优先用 EvidencePack 摘要；超阈值自然语言历史做摘要化；过期状态按 TTL 清理。

**与 P26 的协同：**

- P24 负责 context packing / history compression。
- P26 负责长期显式偏好记忆。
- P24 不能把全部长期记忆原样塞进 prompt。
- P24 需要通过 `MemoryReadContext` 筛选后，才把少量相关偏好送入 `semantic_parse` / `goal_planner` / `ranking_policy`。

**非目标 / 不要做什么：**

- P24 不负责实现长期个性化 memory 系统；P24 只负责 context packing / history compression。
- P24 不做向量 memory。
- P24 不做复杂检索增强。
- P24 不做行为归纳画像。
- P24 不让压缩逻辑侵入业务决策。

**验收标准：** 有一张清晰的 context packing 规则表；能解释哪些信息进入 prompt、哪些只进入 SessionState、哪些通过 evidence_ref 回查；多轮 query 的 token 膨胀得到控制。

**建议测试用例：** 长对话压缩后仍可正确指代“第一家/第二家/刚才那家”；大工具结果压缩后回答仍可追溯；过期状态在 TTL 后被清理且不会误用。

**与现有 P0-P17 的关系：** 这是对 P5/P10/P12/P13 的补充。P5 管状态写回安全，P10 管体验与性能，P12 管预算与 TTL，P13 管类型收敛；P24 则专注多轮上下文压缩边界。

## P25 Cancellation / Partial Result Policy

**背景问题：** Agent 运行过程中会遇到 client_disconnect、user_cancel、deadline_exceeded、tool_timeout、llm_timeout、partial_result_available 等事件。如果这些语义没有统一定义，就会出现“超时了到底是继续、降级还是停止”的歧义。

**为什么对 Agent 开发重要：** 取消和部分结果语义是运行时稳定性的最后一层。它决定了超时后哪些节点可跳过，哪些必须 fallback，部分成功的工具结果如何进入 degrade answer，以及系统是否能给出可信的半成品结果。

**当前项目可能的缺口：** 现有 P12 关注预算字段和降级，但还没有把运行时取消、部分结果、用户主动取消、客户端断开等事件单独成项，也没有定义这些事件与节点跳过策略之间的关系。

**建议的最小实现范围：** 先定义事件语义，再定义动作语义。明确哪些事件可触发停止、哪些可触发 degrade、哪些必须 fallback；把工具部分成功、LLM 超时、用户取消三类情形写成测试建议。

**非目标 / 不要做什么：** 不做完整异步任务系统，不做后台任务编排，不引入复杂任务恢复队列，不把 cancellation 语义和业务 fallback 混成一层。

**验收标准：** 文档中能清晰区分 `client_disconnect`、`user_cancel`、`deadline_exceeded`、`tool_timeout`、`llm_timeout`、`partial_result_available`；能明确超时后哪些节点跳过、哪些节点 fallback；部分结果能稳定进入 degrade answer。

**建议测试用例：** 工具部分成功但后续 LLM 超时；用户主动取消后链路及时停止；deadline 超时后进入可验证的降级答案；部分结果可用时答案标记为 degrade 而不是 final。

**与现有 P0-P17 的关系：** 这是对 P12/P17 的补充。P12 负责预算与时效字段，P17 负责图级错误边界；P25 负责运行时取消和部分结果语义，不替代预算逻辑。

## P26 Local-Life Long-Term Preference Memory

**背景问题：** 当前项目已经有结构化 `SessionState`，能处理会话级短期业务状态：

- `current_shop`
- `last_recommendation_list`
- `pending_clarification`
- `comparison_targets`

这些状态用于解决：

- “这家有券吗？”
- “第一家远吗？”
- “刚才第二家和第三家比一下”
- “那家现在还开着吗？”

但它不是长期用户记忆，不能跨 session 持久保存明确用户偏好，例如：

- 不吃辣
- 喜欢安静
- 预算 100 左右
- 周末常带娃
- 不喜欢排队
- 偏好某个商圈
- 以后推荐餐厅别太吵
- 更喜欢有包间
- 更在意停车方便
- 对某类菜系过敏或忌口

本地生活长期记忆不是“历史对话全文”，而是可解释、可追踪、可冲突处理的用户偏好结构。

**业界设计参考与本项目取舍：**

1. 本地生活长期记忆通常分层：
   - `in-session context`：当前会话意图和业务状态
   - `explicit context / explicit preference`：用户明确说出的稳定偏好
   - `long-term memory`：从订单、搜索、浏览、拒绝、收藏、客服等行为中归纳出的长期偏好
   - `memory encoding`：把 memory blocks 转成 embedding / graph / ranking features
2. 当前项目只做轻量 explicit preference memory：
   - 因为它最适合实习项目展示 Agent memory 边界
   - 不需要大规模行为日志
   - 不需要推荐模型
   - 可解释、可测试、可回放
3. 当前项目暂不做 inferred durable memory：
   - 不从点击、收藏、搜索、工具结果中自动推断长期偏好
   - 不做“用户看了两次火锅，因此长期喜欢火锅”这种推断
   - 行为归纳记忆需要去噪、去重、合并、衰减、晋升、版本化和评估，本阶段只作为未来方向
4. 当前项目暂不做 memory encoding / ranking memory：
   - 不做 memory embedding
   - 不做 consumer context graph
   - 不做 feature store
   - 不做 ranker 训练
   - 不做线上 A/B

**为什么对 Agent 开发重要：**

- 长期记忆是 Agent 从单会话工具编排走向持续个性化助手的关键能力。
- 但长期记忆必须和短期业务状态解耦。
- `SessionState` 负责当前会话引用和任务状态。
- `UserPreferenceMemory` 负责跨 session 用户偏好。
- 长期记忆只能作为 `planning` / `ranking` / `clarification` 的软上下文。
- 长期记忆不能直接生成事实 claim。
- 长期记忆不能污染 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification`。
- 当前 query 显式约束必须优先于长期记忆。
- 长期记忆必须可解释、可追踪、可删除、可覆盖、可过期。

**当前项目可能的缺口：**

- P5 已覆盖 `SessionState` 写回安全。
- P12 已覆盖 TTL / freshness / budget。
- P24 覆盖 context packing / history compression。
- P23 覆盖 Agent Evaluation Rubric。
- 但当前还没有单独定义：
  - `UserPreferenceMemory` schema
  - `MemoryReadContext`
  - `MemoryUpdatePlan`
  - `MemoryBackend` adapter
  - 长期偏好冲突处理
  - 长期记忆删除 / 覆盖规则
  - 记忆 `source` / `confidence` / `evidence_ref` / `ttl` / `status`
  - 显式偏好与行为推断偏好的边界
  - Mem0 可选接入边界
  - 记忆使用是否正确的评估指标

**建议的记忆分层：**

### L0 Conversation / Turn Memory

当前 turn 的原始输入、临时解析、工具中间结果、LLM 临时输出。

要求：

- 不跨 turn 持久化为长期记忆
- 不直接参与长期偏好
- 大型 tool results 通过 EvidencePack 摘要，不直接塞 prompt

### L1 SessionState / In-session Context

当前会话业务状态，包括：

- `current_shop`
- `last_recommendation_list`
- `comparison_targets`
- `pending_clarification`
- `active_constraints`

要求：

- 用于确定性引用消解
- 由 `StateUpdatePlan` 写回
- 不交给 Mem0 或向量 memory 管理
- 失败路径不得污染

### L2 Explicit Preference Memory

用户明确表达的长期偏好，例如：

- “我不吃辣，以后推荐别太辣”
- “我喜欢安静一点的店”
- “预算一般 100 左右”
- “以后推荐餐厅别太吵”
- “我周末通常带娃”

要求：

- 由 `MemoryUpdatePlan` 写回
- 可跨 session 读取
- 作为 preference facet / `ranking_policy` 软约束
- 不直接生成事实 claim
- 当前阶段重点实现

### L3 Inferred Durable Preference Memory

从多次订单、搜索、浏览、拒绝、收藏等行为归纳出的长期偏好。

要求：

- 当前不实现
- 只作为未来方向
- 未来必须具备去噪、去重、合并、衰减、晋升、版本化、评估和回滚机制
- 不允许当前阶段从一次工具结果或一次用户选择自动写长期偏好

### L4 Encoded / Retrieval / Ranking Memory

把 memory blocks 编码成 embedding、graph 或 ranker features。

要求：

- 当前不实现
- 只作为未来方向
- 不引入向量召回、feature store、ranking model、A/B 平台

**建议的最小实现范围：**

### 1. 新增 `UserPreferenceMemory` schema

字段至少包括：

- `user_id`
- `preference_id`
- `preference_type`: `taste | budget | scene | location | deal | accessibility | dietary_restriction | allergy | ambience | negative_preference`
- `value`
- `polarity`: `like | dislike | require | avoid`
- `scope`: `global | local_life | restaurant | cafe | hotpot | parent_child | date_scene | business_area`
- `source`: `explicit_user_statement | confirmed_correction`
- `confidence`
- `evidence_ref`
- `created_at`
- `updated_at`
- `ttl`
- `status`: `active | expired | deleted`
- `version`
- `last_confirmed_at`
- `conflict_group`

说明：

- `source` 第一阶段只允许 `explicit_user_statement` / `confirmed_correction`。
- 不允许 `behavioral_inference` 作为当前阶段 `source`。
- `evidence_ref` 必须指向原始用户表达或对应 turn trace。
- `status` 支持 `deleted`，便于“忘掉这个偏好”。

### 2. 新增 `MemoryReadContext`

要求：

- 每轮 query 开始时按 `user_id` 加载少量相关长期偏好。
- 只读取 `active` 且未过期的偏好。
- 只把与当前 query 相关的偏好注入 `semantic_parse` / `goal_planner` / `ranking_policy`。
- 不把全部历史偏好塞进 prompt。
- 与 P24 Context Packing 协同，长期记忆必须经过筛选和压缩。
- `MemoryReadContext` 只能影响 facet / `ranking_policy` / clarification，不直接生成 final_response。
- `MemoryReadContext` 需要记录 `memory_used`、`memory_ignored`、`memory_conflicts`。

### 3. 新增 `MemoryUpdatePlan`

要求：

- 只允许从明确用户表达中写入长期偏好。
- 示例：“我不吃辣，以后推荐别太辣。”
- 不允许从一次推荐点击、一次搜索结果、一次工具结果里自动推断长期偏好。
- 支持 override / delete，例如：
  - “我现在可以吃辣了”
  - “以后也可以吃辣了”
  - “忘掉我不吃辣这个偏好”
- `MemoryUpdatePlan` 与 `StateUpdatePlan` 分离，避免长期偏好污染 `SessionState`。
- `MemoryUpdatePlan` 必须带 `source`、`confidence`、`evidence_ref`、`ttl` 或 `status`。
- `MemoryUpdatePlan` 必须明确 `operation`: `create | update | delete | no_op`。
- `MemoryUpdatePlan` 必须写入 `reason`，说明为什么这句话是长期偏好，而不是当前 turn 临时约束。

### 4. 新增 `MemoryBackend` adapter

建议：

- 先实现 `InMemoryPreferenceBackend` 或本地 JSON / SQLite backend，便于测试和演示。
- 可选实现 `Mem0PreferenceBackend`。
- Mem0 只能作为 backend，不作为核心状态系统。
- Mem0 只允许保存 / 检索 `UserPreferenceMemory` 这一类长期显式偏好。
- 不允许 Mem0 或任何外部 memory backend 直接控制：
  - workflow routing
  - tool planning
  - state writeback
  - final_response
  - current_shop
  - last_recommendation_list
  - comparison_targets
  - pending_clarification

推荐架构：

```text
UserPreferenceMemory schema
MemoryReadContext
MemoryUpdatePlan
MemoryBackend interface
  ├── InMemoryPreferenceBackend
  ├── SQLitePreferenceBackend / JSONPreferenceBackend
  └── Mem0PreferenceBackend optional
```

**验收标准：**

- 当前阶段能清晰区分 `SessionState` 和 `UserPreferenceMemory`。
- 只允许显式偏好进入长期记忆，不允许行为推断记忆进入当前实现。
- `MemoryReadContext` 只能作为软上下文，不得直接决定 final_response。
- `MemoryUpdatePlan` 可以支持 create / update / delete / no_op。
- 记忆可删除、可覆盖、可过期、可追踪。
- 文档明确 Mem0 是可选 backend，不是核心记忆系统。

**建议测试用例：**

- 明确偏好写入：用户说“我不吃辣，以后推荐别太辣”，应产生 active 的长期偏好。
- 偏好删除：用户说“忘掉我不吃辣这个偏好”，应产生 delete 语义。
- 偏好覆盖：用户说“我现在可以吃辣了”，应覆盖旧偏好而不是叠加冲突。
- 跨会话读取：下一次会话能读取到有效偏好。
- 当前 query 优先级：用户明确说“今天就想吃辣”，应优先于长期“不吃辣”偏好。

**与现有 P0-P17 的关系：**

- P26 是对 P5/P12/P24/P23 的补充，不替代它们。
- P5 继续负责短期引用消解和会话状态安全。
- P12 继续负责 TTL / freshness / budget。
- P24 继续负责上下文压缩，P26 只提供可筛选的长期偏好输入。
- P23 继续负责评估，P26 可作为新的评估维度来源。

**与 P24 的协同：**

- P24 负责 context packing / history compression。
- P26 负责长期显式偏好记忆。
- P24 不能把全部长期记忆原样塞进 prompt。
- P24 需要通过 `MemoryReadContext` 筛选后，才把少量相关偏好送入 `semantic_parse` / `goal_planner` / `ranking_policy`。

**非目标 / 不要做什么：**

- 不做交易、预约、支付、订单记忆。
- 不做推荐模型训练。
- 不做大规模画像系统。
- 不做行为归纳长期记忆。
- 不做向量 memory 作为主实现。
- 不做线上 A/B。
- 不把长期记忆直接写进 `SessionState`。
- 不让长期记忆直接控制 routing / tool planning / final_response。
- 不把“历史对话全文”当长期记忆。
- 不做复杂检索增强或消费级 user profile center。

## 推荐执行顺序

建议优先顺序是 P18 → P20 → P19 → P25 → P21 → P22 → P23 → P24 → P26。

理由如下：

1. 先补工具治理协议，后面的恢复、回放、调试和评估才有统一语义。
2. 先补结构化输出恢复，能显著减少 graph 中断和测试不稳定。
3. 先补 replay harness，后续所有调试和评估都会更可靠。
4. 再补取消和部分结果语义，完善运行时边界。
5. 然后补 model routing、debug bundle、evaluation rubric、context packing、长期显式偏好记忆，这些更偏能力增强和工程展示。

如果资源有限，可以先做“协议 + 恢复 + 回放 + 调试快照”四件套，它们最能体现 Agent 工程能力。

## 验收清单

1. 文档明确区分 P18-P26 与 P0-P17，不重复替代已有内容。
2. 文档明确区分 P26 与 P5/P12/P24/P23，不把长期显式偏好记忆混成 SessionState。
3. 每个补充项都包含背景问题、重要性、缺口、最小实现范围、非目标、验收标准、测试用例、关系说明。
4. 文档明确只补充工程 TODO，不引入 workflow 级 Map-Reduce、万能 ReAct、交易/预约/支付、大规模推荐模型、多模态、线上 A/B 平台。
5. 文档明确不重写 `graph_builder`，不改变现有 P0-P17 优先级。
6. 文档对未来 mutation tool 的 confirmation gate 有明确约束，但本阶段不实现 mutation。
7. 文档可以直接作为实习项目展示的工程路线图，重点突出 Agent 协议、恢复、回放、调试、评估、上下文管理和长期显式偏好记忆。

## 风险和非目标

本补充文档的主要风险，不在于内容太多，而在于后续实现时把“工程协议”滑向“业务功能扩张”。因此需要持续守住边界。

**不要做的边界：**

1. 不引入 workflow 级 Map-Reduce。
2. 不引入万能 ReAct Agent。
3. 不引入交易/预约/支付。
4. 不引入大规模推荐模型。
5. 不引入多模态。
6. 不引入线上 A/B 平台。
7. 不重写 `graph_builder`。
8. 不改变现有 P0-P17 的优先级，只作为补充 TODO。
9. 不把长期显式偏好记忆扩展成行为画像系统。
10. 不把长期显式偏好记忆实现成向量召回 / feature store / ranker 训练平台。
11. 不把长期记忆直接塞满 prompt。

**额外非目标：**

1. 不把治理协议做成重型权限系统。
2. 不把回放夹具做成线上录制平台。
3. 不把 debug bundle 变成长期隐私存储。
4. 不把 model routing 做成真实多模型编排平台。
5. 不把 context packing 做成长期记忆系统。
6. 不把长期显式偏好记忆误写成 SessionState。
7. 不把长期显式偏好记忆做成行为归纳画像。

这份补充文档的目标很单纯：让 Agent 的工程能力看得见、测得到、回放得了、解释得清，而不是扩大业务范围。
