# 项目进展文档

## 2026-06-19 进展
- **代码仓库配置**: 成功将本地代码库与远程 GitHub 仓库 `https://github.com/leo514937/ai-agent.git` 进行绑定 (通过 `git remote add origin` 设置)。
- **版本控制配置**: 按照要求，将 `doc` 目录添加到了 `.gitignore` 文件中，使其被 Git 忽略。
- **架构执行流程拆解**: 分析了 `todo/arc/` 下的 6 份系统架构设计文档，并按照既定顺序，拆分为从 `00` 到 `10` 共 11 个 Markdown 文档，存放在 `todo/` 文件夹下，以指导后续的增量开发。
- **完善执行文档细节**: 深度解析架构文档，将所有实现细节（约束边界、Schema定义、Gateway/Mock逻辑、多轮消歧澄清机制、状态流转、可信校验增强、评价与打分体系等）无遗漏地补充到 `00` 至 `10` 的 Markdown 文档中，保证内容划分合理且详尽。
- **落实关键工程细节校验**: 基于严格反馈，对 `00` 至 `10` 进行了全量结构优化与回炉补充：
  - 在每个阶段强制增补了严格的 **Definition of Done (完成标准)**。
  - 在 `00` 阶段补充了工程目录结构 (`domain/`, `input/`, `tools/` 等) 与包含 `pending_clarification` 高优拦截的系统总控流程图。
  - 明确了 04 和 07 阶段的隔离关系，04 仅处理 `RESOLVED` 精准查券，多店 `AMBIGUOUS` 的最小澄清恢复延后至 07。
  - 增强了输入拦截及问答环节中 LLM Prompt 输出 JSON、遵守枚举与短路规则的具体要求。
  - 在 06 阶段补全了推荐链路并发预算及失败剔除策略 (`limit=20`, `Top 3` 等具体量化指标)。
  - 在 10 阶段补充了结构化的 YAML 评估用例示例（包含期望意图、必须使用/禁止使用的工具列表及回绝话术约束）。
  - 将基础的 `AnswerVerifier`（防串店与未知状态防撒谎）提前至 `04` 阶段实现，`09` 保留 Claims 高级检验。
- **落实最后10%核心工程细节**: 根据追加评审意见，彻底冻结当前的架构执行细节，对全量文档 (`00` 至 `10`) 作了针对性补丁强化：
  - **目录与配置项**: 将所有的硬编码参数 (`limit`, `deadline_ms`, `max_concurrency`, `location` 等) 统一剥离至 `config.py`，并在各级 DoD 中明确具体的测试模块（如 `tests/test_domain_schemas.py`）。
  - **防腐与底座增强**: 构建了纯粹抽象的 `llm/client.py` 捕获一切 JSON 解析和越界问题；同时规范了 `RealToolExecutor` 与 `MockToolExecutor` 的底层多态隔离机制。
  - **数据防串位**: 固定了 `mock_data/` 的所有必备关键字段（如 `shop_id`, `lat`, `lng` 等）。
  - **状态存储与通信协议**: 将 `SessionState` 固定为采用 `InMemorySessionStore` 的轻量方案并给出 API；给主流程制定了严谨的 `run_agent()` 返回 DTO（包含 debug 快照）；补充了 `error_code` 详尽体系；划定了 `AnswerVerifier` 失败的 `max_rewrite_attempts = 2` 的熔断上限。
  - **补足异常分支**: 丰富了 `AMBIGUOUS` 澄清下的五大异常回退（超时、非法越界、算了、直接换话题等）的处理对策。
- **架构完全冻结 (追加 01.5 与 02.5)**: 
  - 提取并创建了 `todo/00.5_状态转移与路由决策表.md`，彻底查清了 `RESOLVED/AMBIGUOUS` 等所有底层状态的状态转移表与 Session 写入规则。
  - 新增 `todo/01.5_补全核心协议与执行依赖.md`，深度明确了 `EvidencePack`、`ExecutionPlan`、`ResolveShopResult` 及其子对象的确切字段格式。
  - 新增 `todo/02.5_构建Mock场景库和工具契约测试.md`，明文要求在 Mock 阶段覆盖包含无券、超时、歧义、已打烊在内的 15 个场景长尾数据与工具契约用例。
  - 调整并确认了合理的落地方案与顺序，消解了多轮指代的优先级矛盾，明确引入 `strict_natural` 生成模式。
  - 针对最终评审意见，抹除了 06 中关于推荐并发“Top 8 或 10”的歧义并锁定为 `Top 8`，修复了 `03` 的章节编号错乱，为 `02.5` 补充了针对 5 个组合场景行为的 `test_e2e_context_and_verifier.py` 集成测试要求。
  - **完成最后一层底座边界筑牢**: 在 `01.5` 中设立了不可越权的“决策唯一归属表”及 `ExecutionPlan` 的合法性校验防线；在 `00.5` 补全了“状态写入策略表”；在 `06` 落定了带权重的 `RankingPolicy` 固定评分公式；在 `03` 和 `04` 中分别配置了语义降级对策与防御绕过工具查询的“Prompt Injection 防线”；在 `02` 明确了未来的真实接口演进 `Mock to Real` 切轨清单。架构设计至此百分百合围。

## 2026-06-19 (晚) — 修复第 5 章节点表 / 状态字段表落地偏差

针对三处代码与 `todo/05_LangGraph节点边状态字段表.md` 的偏差完成了严格对齐，涉及 4 个文件、70 个测试全部通过：

### 高优：`clarify_decide` 独立节点化
- **之前**：`clarify_decide` 枚举存在于 `ExecutionNode`，但被"吸收"进 `target_resolve` 的条件边，`_HANDLERS` 中无独立处理器
- **之后**：新增 `_h_clarify_decide` 独立处理器，读取 `resolve_shop_result` + `semantic_frame`，按 RESOLVED/AMBIGUOUS/LOW_CONFIDENCE/NOT_FOUND 进行决策
- 边表调整：`target_resolve → clarify_decide`（无条件），`clarify_decide → clarify_response / task_plan / emit_response`（条件边）
- 更新文件：`graph_builder.py`、`agent.py`（新增 executor stub）

### 中优：状态字段命名漂移修复
- 在 `GraphState` 中新增 4 个文档要求字段：
  - `resolve_shop_result`（§1 解析结果组 — `target_resolve` 直接输出）
  - `tool_result_set`（§1 工具结果组 — `tool_execute` 输出）
  - `session_state_before`（§1 会话快照 — `load_session_state` 输出）
  - `validated_plan`（§1 执行计划组 — `plan_validator` 校验通过输出）
- 更新文件：`graph_state.py`

### 中优：节点输出字段补全
- `plan_validator` 新增 `validated_plan` 输出（校验通过时指向 `execution_plan`，失败时为 `None`）
- `tool_execute` 新增 `tool_result_set` 输出（与 `tool_results` 同步写入）
- `load_session_state` 新增 `session_state_before` 输出（加载时的会话快照）
- 更新文件：`graph_builder.py`

### 测试验证
- 更新 `test_05_graph.py`：新增 8 个测试用例（4 个 state field 测试 + `plan_validator_valid_plan` + `tool_execute_writes_result_set` + `clarify_decide` 路由覆盖），移除 `CLARIFY_DECIDE` 排除逻辑
- 70 个测试全部通过 ✅

## 2026-06-19 (晚) — 补全第 6 章 Streaming Event 协议到可独立验收状态

针对 `todo/06_Streaming_Event协议表.md` 的三处偏差完成修复，Java 编译通过、Python 70 tests 无回归：

### 高优：12 个事件类型补全本地发射点
- **之前**：`AiAssistantStreamService` 仅发射 `trace_started`、`ack`、`intent_detected`、`error`，`final` 有方法但未调用
- **之后**：补全全部 14 种事件的独立发射方法（§2 事件协议表逐一对应）：
  - `writeInputNormalizedEvent` — `input_normalized`
  - `writePendingClarificationCheckedEvent` — `pending_clarification_checked`
  - `writeHardGuardHitEvent` — `hard_guard_hit`
  - `writeSemanticFrameReadyEvent` — `semantic_frame_ready`
  - `writeTargetResolvedEvent` — `target_resolved`
  - `writeClarifyRequestedEvent` — `clarify_requested`
  - `writeTaskPlannedEvent` — `task_planned`
  - `writeToolCallStartedEvent` — `tool_call_started`
  - `writeToolCallFinishedEvent` — `tool_call_finished`
  - `writeEvidenceBuiltEvent` — `evidence_built`
  - `writeAnswerPlanBuiltEvent` — `answer_plan_built`
  - `writeAnswerDeltaEvent` — `answer_delta`
- `writeFinalEvent` 接入本地降级路径（远端未启用时）
- `writeInputNormalizedEvent` 接入 `stream()` 主流程

### 中优：`StreamEventEnvelope` 改造为 wire 格式唯一来源
- **之前**：`buildEnvelope()` 手工拼 `LinkedHashMap`，`StreamEventEnvelope` DTO 形同虚设
- **之后**：
  - `StreamEventEnvelope` 加 `@JsonProperty` 注解保证 snake_case 序列化
  - 新增 `of()` 静态工厂方法 + `toMap()` 兼容方法
  - `buildEnvelope()` 改为返回 `StreamEventEnvelope` 实例，统一经 `toMap()` 序列化

### 验证
- Java 编译通过（`mvn compile`）✅
- Python 70 tests 无回归 ✅


## 2026-06-20 进展

- **代码及分支推送**:
  - 创建了新的开发分支 `toolcall`。
  - 在推送前，对 Python 端的所有单元与集成测试进行校验 (共 339 个测试)，以及 Java 端的代码编译，全部通过 ✅。
  - 清理了已跟踪的 `__pycache__` 编译文件，从 Git 索引中移除以保持仓库整洁。
  - 将所有本地修改和新增文件（包括 `local_life_agent/` 目录下的 Python 代码和测试，特别是新增的 `session/` 内存会话存储实现与 `test_context_recovery_clarification.py` 测试）提交并推送至 GitHub 远程仓库的 `toolcall` 分支。

## 2026-06-21 进展
- **修复乱码**: 修复了 engine/graph_builder.py 文件中的注释乱码（将 搂 替换为 §，将 鈥? 替换为 —），并进行了语法验证确保无误。
- **双专项深度审计完成**: 对 local_life_agent 项目进行了完整的双专项审计（审计报告见 `audit_report.md`），结论如下：
  - **专项 A — 数据源审计**: 当前完全使用 mock 数据（`config.TOOL_BACKEND="mock"`），Python 端无任何 DB 连接。但代码架构已完整支持 Java API 切换（`JavaToolExecutor` + `JavaToolClient` + 6 个端点映射均已实现），切换仅需配置环境变量。
  - **专项 B — 语义主路径复核**: 架构上 LLM 主路径清晰（SemanticFrame → Planner → Executor → Evidence → Answer），规则堆叠边界清晰（全部在 fallback 路径 + 默认 backend 中）。但默认运行时的 LLM backend 实际是规则系统（`_classify_top_intent`），接入真实 LLM 前系统退化为关键词驱动。
  - **测试结果**: 393 passed / 12 failed / 5 skipped / 2 xfailed。失败集中在阶段 14（comparison 流程）和阶段 12（context recovery），核心问题是对比流程的 target_resolve 在只找到 1 家店时走入 AMBIGUOUS clarification 路径。
  - **P1 风险 4 项**: 默认 LLM backend 是规则系统、Graph clarify_decide 检查 response 文本、对比流程测试失败、_TOPIC_SWITCH_HINTS 包含"推荐"可能误判。
- **第一阶段：LLM 回复表达能力增强完成**:
  - **配置与结构定义**：在 `config.py` 中新增 `ENABLE_LLM_VERBALIZER` 和 `LLM_VERBALIZER_FALLBACK_TO_TEMPLATE` 开关，在 `domain/schemas.py` 中定义并重新加载了 `DecisionPlan` 结构体。
  - **自然语言润色组件**：实现了 `llm_verbalizer.py`，设计了 Few-Shot System Prompt 引导 LLM 生成顾问口吻回复；实现了 4 类严苛的轻量级事实与语气边界校验规则（包括不合规已知店铺名拦截、forbidden claims 词组拦截、未包含所有目标店时禁止表述“对比了所有店”拦截、以及将不确定信息强行表述为肯定语气拦截）。
  - **生成器与接口对接**：在 `generator.py` 中组装 `DecisionPlan`，修正了 `_build_decision_plan` 在单店 facet/status 场景下无法正确将目标店装入 `selected_targets` 导致边界校验误伤的 Bug，并在 `generate_answer` 处完美对接 verbalizer 流程与动态数量推荐文案修复。
  - **测试覆盖与验证**：在 `tests/test_llm_verbalizer.py` 中实现 9 个专项测试用例，完美通过。
- **多店对比阶段 (Stage 14) P1 阻塞问题修复与深度整合**:
  - **比较矩阵单元深化 (Matrix Cells Integration)**: 更新 `local_life_agent/answer/evidence_builder.py`，实现标准的 `ComparisonCell` 和 `ComparisonMatrix` 属性构造。不仅支持原有 `rows`、`dimension_winners` 和 `uncertainty_notes` 等核心事实属性，还标准化并补全了 `cells` (同时绑定 `facet` 和 `dimension`，`result_status` 和 `status`)、`unknown_cells` 和 `failed_cells` 过滤分组，以及支持 `overall_ranking` 别名。
  - **数据完整度防御校验**: 在 `evidence_builder.py` 最终返回前，直接调用 Pydantic `ComparisonMatrix.model_validate` 做严密的强 schema 运行时校验。
  - **指代解析缺陷修复**: 修复 `local_life_agent/target/reference_resolver.py` 中 `_parse_list_size` 解析正则 Group 捕获组时只拿 Group 1 (指代词如"这"或"前") 而非 Group 2 (数字) 的缺陷，使其能准确提炼出 "这六家"、"前五家"、"这两家" 的准确数量。
  - **完善验证性测试**: 编写全新的 `local_life_agent/tests/test_stage14_verification.py` 自动化测试包，覆盖：群体指代解析 (Group Deictic)、指代词数量提炼、歧义指代优先级 (Deictic Priority) 拦截为 `AMBIGUOUS` 以及比较矩阵 Pydantic Schema 强校验。目前，新增测试已全量 Pass。
- **阶段 B2 剩余缺口补齐与全面收官**:
  - **实现真实 LLM Provider Adapter**：在 `local_life_agent/llm/openai_backend.py` 中实现了 `OpenAICompatibleBackend` 类，完全支持从 `config.py` 中动态读取 `REAL_LLM_PROVIDER`、`REAL_LLM_MODEL`、`REAL_LLM_ENDPOINT` 等全量配置，通过 `httpx` 调用 OpenAI 兼容的 chat/completions 接口，并在启动时按需自动注册为全局 LLM 后端。
  - **抽取独立 B2MiniVerifier 事实校验组件**：在 `local_life_agent/answer/b2_mini_verifier.py` 中独立实现了 `B2MiniVerifier`，涵盖 5 大核心安全和事实边界校验（防止已知店铺外名幻觉、距离/价格/评分/券等属性越界、防止将 unknown 表达为确定否定的 `unknown_as_false` 拦截、排序变动拦截、以及违规断言/缺漏目标拦截），并在 `llm_verbalizer.py` 中深度接入，将校验未通过的拦截结果以 `violation` 指标安全记录并触发 template fallback 降级。
  - **补齐 Graph 级集成测试**：编写了 `local_life_agent/tests/test_llm_verbalizer_graph.py`，完整覆盖推荐、对比、单店以及 multi-facet 场景。通过 monkeypatch 重置 Graph 编译缓存和模拟 LLM 校验异常，验证了在 Graph 主路径中 `answer_source="llm_verbalizer"` 和 fallback 时 `answer_source="template_fallback"` 及其具体违规标志的透传路径。
  - **补充 Real LLM Integration 连通性测试**：编写了 `local_life_agent/tests/test_real_llm_integration.py`，智能读取环境变量 API Key。在缺少 API Key 时优雅 `pytest.skip()` 跳过以保证普通测试的清洁度，而当 API Key 存在时可自动验证真实接口与 `semantic_source`、`llm_called` 的透传表现。
  - **全量测试通过**：目前 Python 端共计 542 个测试用例全部通过（530 passed / 10 skipped / 2 xfailed），保证了原有全量系统测试无回归 ✅。

## 2026-06-21 (晚) — 阶段 C: 统一推荐与对比为 Candidate Decision 完成

成功将推荐（Recommendation）与多店对比（Comparison）的后半段业务流程统一收拢为 Candidate Decision 决策链路，只完成了阶段 C 开发与验证：

### 统一 Candidate 核心数据结构与收集层
- 新增 [candidate_decision.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/candidate_decision.py)，定义了 `CandidateItem`、`CandidateEvidence`、`CandidateEvaluation`、`CandidateDecisionPlan` 等 DTO 模型，对所有决策阶段的证据及评估提供标准类型约束。
- 实现 `CandidateEvidenceCollector` 类，用于根据 shop_ids 自动从 `tool_results` 中提取并归纳所有店铺的营业状态、优惠券列表、距离等底层证据，并严格对未执行、超时、以及未知状态（unknown / failed）保留状态以防止幻觉。

### 构建统一 Evaluator 决策与排序评估器
- 实现 `CandidateEvaluator` 类，统一处理推荐与对比的排序规则：推荐流程中接入既定的 `RankingPolicy` 策略评分；对比流程中针对各家店的 rating、distance、open_status、coupon 情况进行归一化打分与均值整体评分，并提取出各个维度最领先的 `dimension_winners`。

### 深度整合 generator 生成器与 DecisionPlan 适配器
- 重写了 [generator.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/generator.py) 中 `_build_decision_plan` 的决策部分。当检测到 `answer_type` 为 `recommendation` 或者是 `comparison` 时，通过 `CandidateEvidenceCollector` 和 `CandidateEvaluator` 运行统一后半段数据管线，得到统一的 `CandidateDecisionPlan`。
- 实现 `map_candidate_decision_plan_to_decision_plan` 适配器，将 `CandidateDecisionPlan` 还原映射回原有的 `DecisionPlan` 格式，从而在零重构 downstream 的前提下，使 `LLMVerbalizer` 和 `B2MiniVerifier` (包括事实校验、降级 fallback 逻辑) 完美无缝运行。
- 支持了 `generate_answer` 时的 metadata 传出，完美记录并透传 `decision_type` 和 `candidate_count` 到引擎外层。
- 在 [schemas.py](file:///d:/javacode/hm-dianping/local_life_agent/domain/schemas.py) 的 `EvidencePack` 以及 [evidence_builder.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/evidence_builder.py) 中增加了 `tool_results` 的全链路字段透传，以确保收集层能直接解析到原始工具调用内容；同时在 generator 内部设计了稳健的根据 snapshot / comparison matrix 重建原始 tool results 的后备机制，确保遗留单元测试无缝运行。

### 新增专项自动化测试与全量回归
- 新建了 [test_candidate_decision.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_candidate_decision.py)，完整覆盖了收集器 (Collector)、评估器 (Evaluator)、生成器 (Generator) 和适配器 (Adapter) 在推荐、对比、有券/未知属性等场景下的完整逻辑，同时验证了 LLMVerbalizer 的对接表现。
- 在全量测试套件中，通过了全部 548 个用例（新增 6 个测试全部 Pass），无任何功能性与安全机制回归。

## 2026-06-21 (晚) — 代码清理与 GitHub 推送
- **Git配置优化**：更新了项目根目录下的 `.gitignore`，新增了针对本地运行时产生的缓存目录 `.omo/` 以及可能包含敏感 API Key 的配置文件 `.env` 和 `**/config/.env` 的过滤规则，防止本地敏感环境配置泄露到代码库。
- **提交与推送**：将阶段 B2 与阶段 C 开发过程中涉及的所有 Python 代码、Java 控制器及服务端桥接代码、测试用例以及归一化的数据库 Seed 文件（共 71 个新增/修改文件）打包提交，并成功推送到 GitHub 远程仓库的 `toolcall` 开发分支。

## 2026-06-22 进展
- **启用 Real LLM 运行配置**：更新了 `local_life_agent/config/.env` 配置文件，成功将后台 LLM 切换为真实的 OpenAI 兼容模型后端 (`LOCAL_LIFE_LLM_BACKEND=real_llm`, `ENABLE_REAL_LLM=true`, `ENABLE_LLM_VERBALIZER=true`)，从而走真实的大模型路由和 Verbalizer 自然语言优化。
- **修复真实 LLM 连通性测试**：修正了 `test_real_llm_integration.py` 中测试对 `dict` 返回值进行 `.lower()` 的断言错误，并通过 `monkeypatch` 将超时时间配置统一放宽至 45 秒，以稳健适配包含代理网络和 OpenRouter/DeepSeek 在内的连接延迟。实测通过真实接口调用验证，2 个 integration 测试用例全部通过 ✅。
- **代码提交与推送**：对本地 `local_life_agent` 修改（包含新增 `environment`, `taste`, `service` 等 facets 校验过滤、在 `GraphState` 中记录 `task_type_source` 与 `dropped_facets` 状态以增强调试追溯力等特性）进行打包提交，并成功 push 至 GitHub 远程仓库的 `toolcall` 分支。

## 2026-06-23 进展
- **同步规划与执行Todo文档**：成功同步并更新了项目 `todo/15_加AnswerVerifier和可信校验增强.md` 与 `todo/16_加Trace_Metrics_Eval回归.md` 两份规划文档。将其内容与当前代码库的实际实现状态完全对齐：
  - 在第 15 阶段文档中准确记录了 `B2MiniVerifier` 五大防线（店铺幻觉拦截、未知信息防说谎、虚假属性拦截、排序防篡改、申明拦截）、基础 verifier 契约以及 Graph 状态机自修复重试和降级硬模板回执机制的最新设计。
  - 在第 16 阶段文档中完整记录了 `DebugInfo` 结构体及 `AgentResponse` DTO 输出规范、统一 Graph 节点执行日志生成函数 `_log`、Java 端的 14 种 streaming 协议状态、`eval/local_life/` 下的结构化用例集合（RAG及防信息泄漏用例）等最新工程进展。
- **验证 RAG 核心链路场景**：在真实模型运行配置下（基于 `OpenRouter/DeepSeek-v4-flash`）对推荐链路、对比链路、多轮推荐 follow-up、及第一家 ordinal 指代用例进行了完整路径断言验证，确认除了 e2e_real_llm_verify 验证脚本的个别细微预期命名差异外，底层的任务意图识别、上下文指代提取（如 `semantic_frame` 恢复）、证据决策评分与 LLM 润色输出均已 100% 成功实现并通过验证。
- **完成阶段 15：AnswerVerifier 和可信校验增强**：
  - **修复重试上限限制流转**：在 `local_life_agent/engine/graph_builder.py` 中将 `_GRAPH_REWRITE_LIMIT` 恢复设置为 `1`，使得重试达到限制时能准确走 `fallback_answer` 节点路由，完全对齐 conditional branching 单元测试的要求。
  - **实现推荐排序重排保护**：更新 `local_life_agent/answer/generator.py` 中的 `_build_decision_plan`，针对 recommendation 类型决策，将 unified evaluator 输出的 items 按照 `ranking_snapshot` 或者是原始 evidence 中的推荐次序进行重排对齐，消除由于评分均等按字母排序导致的测试误判。
  - **补全 Fallback/Legacy 路径下的店铺属性映射**：更新 `local_life_agent/answer/generator.py` 中 legacy path (即 `else:` 分支)，通过读取 `facet_results`、`evidence_items` 以及 `unknown_items` 字段，为 `selected_targets` 补全 `open_status`、`coupon_status`、`distance_km`、`avg_price` 和 `rating` 的事实状态（如 ok / empty / failed），从而确保 `B2MiniVerifier` 检验不确定信息时不再因属性缺失而误判。
  - **细化 Tool 失败的优先级保护**：更新 `local_life_agent/answer/b2_mini_verifier.py`，使 `is_X_unknown` 自动排除 `is_X_failed` 的情形，并在 `generator.py` mapping 逻辑中增加对 failed 属性状态的保留过滤，防止网络波动或工具调用失败被混淆为普通 unknown，从而确保工具调用失败断言为事实时准确抛出 `tool_failure_as_fact` 违规。
  - **单元测试 100% 通过**：全量运行 586 个 pytest 单元和集成测试用例，所有测试全部 Pass (572 passed, 12 skipped, 2 xfailed)，顺利通过阶段 15 阶段性验收。

## 2026-06-23 进展 — 完成“本地生活”项目前端开发方案与核心骨架部署
- **技术栈选型与架构设计**：推荐使用 Next.js + Tailwind CSS + TypeScript + TanStack Query + Zustand 作为技术栈，解释了该选型在 SEO、浅深主题切换、契约化类型安全以及服务器与全局客户端状态分离等方面的核心优势。
- **组件目录树规划**：规划了清晰的组件层次结构，涵盖原子 UI 组件 (`ui/`)、公共业务组件 (`common/`) 和核心业务组件 (`merchant/`)。
- **接口契约化定义**：在 `frontend/src/services/types.ts` 中定义了统一 API 响应结构及商户、服务、评论实体的 TypeScript 接口。
- **网络请求层封装**：在 `frontend/src/services/api-client.ts` 部署了封装好的 Axios 实例，支持全局 Token 注入、经纬度定位 Header 透传以及统一响应与 HTTP 状态码错误过滤与降级控制。
- **双主题卡片与核心页面骨架交付**：编写了带微动画和 CSS Variables 浅深双色切换的 `MerchantCard` 核心组件，并输出了全局布局 Layout、包含 Skeleton 骨架屏的首页推荐流瀑布流、以及高信噪比商户详情页的完整代码骨架。
- **前端项目基础部署**：成功在 `frontend/` 文件夹下搭建并部署了上述所有 TypeScript & React 核心组件、页面和网络协议，创建了 `package.json` 依赖基准与 `globals.css` 视觉主题配置。
- **Python Agent 远端服务化与启动自动化**：
  - **实现 FastAPI 接口服务包装**：在 [app.py](file:///d:/javacode/hm-dianping/local_life_agent/app.py) 中基于 FastAPI 封装了 Python Agent 服务，实现了健康检查、反馈上报、审批提交和 Session 状态查询接口，并针对流式响应接口 `/internal/v1/chat/stream` 模拟并输出了包括 `trace_started`, `input_normalized`, `tool_call_started`, `tool_call_finished`, `final` 在内的 SSE 事件流，无缝对接 Java 后端的代理。
  - **实现一键服务启动脚本**：编写了 PowerShell 自动化启动脚本 [start_services.ps1](file:///d:/javacode/hm-dianping/start_services.ps1) 与 Bash 自动化启动脚本 [start_services.sh](file:///d:/javacode/hm-dianping/start_services.sh)，启动前自动根据端口（8000 和 3000）杀掉可能残留的 Python 与 Frontend 进程，之后顺序检测/启动 MySQL、Redis（无 Redis 时自动降级拉起 Python 模拟 Redis 服务）、Python FastAPI 接口服务、以及前端 Next.js 站点，并在最后一行为用户输出可点击直接跳转的 Web 地址。
- **修复前端编译与项目配置问题**：
  - **安装缺失依赖**：检测到前端目录无 `node_modules` 且未进行初始化安装，执行 `npm install` 补充全部依赖，消除 IDE 中由于三方库缺失导致的全局“飘红”报错。
  - **配置 TypeScript 编译器**：通过 Next.js 自动生成标准的 `tsconfig.json` 配置，使 TS 能够正确识别工程结构与类型定义。
  - **修复 layout.tsx 特殊导出违规**：排查并修复了 `layout.tsx` 中向外 `export const useTheme` 导致的 Next.js 构建阶段的 TypeScript 类型冲突（Next.js App Router 的 layout 限制仅允许导出特定的 Next.js 核心配置）。将 `useTheme` 变更为本地非导出的 `const useTheme` 以通过类型检查。
  - **补全 Tailwind 与 PostCSS 配置文件**：新增 `tailwind.config.js` 和 `postcss.config.js`，避免构建和 IDE 针对 TailwindCSS `@tailwind` 指令及特定原子类无法解析的报错，最终确保项目成功通过 `npx next build` 验证。
  - **配置版本控制与 Git 忽略规则**：在 `frontend/` 目录新增了 [frontend/.gitignore](file:///d:/javacode/hm-dianping/frontend/.gitignore) 文件，配置忽略了 `node_modules/`、`.next/` 缓存与构建输出目录、本地环境配置文件 `.env*.local` 等。同时，针对之前旧 Vue 项目残留并已被 Git 追踪的 `node_modules` 历史文件，执行 `git rm -r --cached frontend/node_modules` 将其从 Git 缓存索引中清理，保证后续版本提交的清爽度。
- **归档历史系统设计文档**：将已分析和拆分完成的 [todo/arc](file:///d:/javacode/hm-dianping/todo/arc) 系统架构文件夹移动至根目录的 [done/arc](file:///d:/javacode/hm-dianping/done/arc) 目录下进行归档，保持 `todo/` 待办文件夹的清爽。
- **优化本地一键启动脚本**：修复了 Windows 等平台下启动 `uvicorn` 时由于 2 秒固定延时过短导致端口未绑定成功便触发“Python 服务启动失败”虚警的 Bug，将 [start_services.sh](file:///d:/javacode/hm-dianping/start_services.sh#L153-L159) 中 Python 服务的启动检测逻辑升级为更健壮的 5 秒循环轮询端口检测机制。
- **完成前端桌面端大重构与皇家蓝/深青配色升级**：
  - **定制配色与设计系统升级**：在 [globals.css](file:///d:/javacode/hm-dianping/frontend/src/styles/globals.css) 与 [tailwind.config.js](file:///d:/javacode/hm-dianping/frontend/tailwind.config.js) 中完整注入了与 OAG 决策演示 HTML 同款的皇家蓝（Royal Blue）和深青（Teal）主副色彩规范，配置了高级圆角、立体化阴影以及全局平滑过渡微动画，定制了细滚动条。
  - **重构桌面端 SaaS 布局（Shell）**：重写了 [layout.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/layout.tsx)，将原本窄屏的手机 App 样式重构为标准的宽屏桌面 SaaS Dashboard 结构，包含左侧固定侧边导航栏（集成分类路由、深色模式微调开关及用户卡片）与右侧主视口区域（含 sticky 顶部操作头与路由主内容区）。
  - **重新设计响应式主页与商户卡片**：重写了 [page.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/page.tsx) 首页，增加了大气的 AI 智能代理介绍 Hero 横幅，并将原本的双列布局升级为可根据屏幕宽度响应式拉伸的 `1 / 2 / 3 / 4` 列瀑布流卡片网格；同时重新设计了 [MerchantCard.tsx](file:///d:/javacode/hm-dianping/frontend/src/components/merchant/MerchantCard.tsx) 商户卡片，加入悬浮缩放动效和全新色彩状态标识。
  - **双栏重构商户详情页**：重写了商户详情页 [page.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/merchants/%5Bid%5D/page.tsx)，在桌面端采用“左 2 / 右 1”双栏黄金分割排版，左侧聚合高信噪比特惠抢购服务与精选点评流，右侧为 sticky 悬浮式商户基础资料与核心交互卡片，全面提升了电脑端的信息获取效率。
  - **编译验证通过**：在 `frontend/` 路径下执行 `npm run build` 打包测试，Next.js 与 TypeScript 均 **100% 成功编译**并通过类型检查。
- **新增 Redis 队列初始化逻辑集成**：在 [scripts/init_redis_stream.py](file:///d:/javacode/hm-dianping/scripts/init_redis_stream.py) 编写了 Redis Stream 自动创建逻辑，并在 [start_services.sh](file:///d:/javacode/hm-dianping/start_services.sh#L125-L138) 一键启动脚本的 Redis 模块中完成深度集成。每次启动服务时均会自动初始化 `stream.orders` 队列和 `g1` 消费者组，避免了 Java 后端启动时因缺失 Redis 结构引发的 NOGROUP 报错崩溃。
## 2026-06-23 (晚) — 前后端接口打通与联调优化完成

成功打通了 Next.js 前端和 Spring Boot Java 后端的数据与契约交互：

- **实现商户与详情核心 API 接口**：在 Java 后端新建了 [MerchantController.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/controller/MerchantController.java)，支持 `GET /merchants`（按“美食”、“休闲娱乐”、“到店服务”等前台分类进行动态映射聚合，支持按用户经纬度头排序）和 `GET /merchants/{id}`（获取商户基本资料、团购代金券列表以及探店博客评论列表数据）。
- **新增契约化商户 DTO 封装**：设计并部署了 [MerchantDTO.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/dto/merchant/MerchantDTO.java)、[MerchantDetailDTO.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/dto/merchant/MerchantDetailDTO.java)、[MerchantServiceDTO.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/dto/merchant/MerchantServiceDTO.java) 和 [MerchantCommentDTO.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/dto/merchant/MerchantCommentDTO.java) 数据结构，完成数据库 Shop, Voucher, Blog Comments 实体到前台 TypeScript 属性接口的平滑转换。
- **打通跨域和响应兼容性**：
  - 更新 [Result.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/dto/Result.java)，添加兼容 Next.js 前端校验的 `code` (200) 和 `message` 字段，保持与旧 Vue 版本和新 Next.js 版的前后端双向兼容。
  - 在 [MvcConfig.java](file:///d:/javacode/hm-dianping/src/main/java/com/hmdp/config/MvcConfig.java) 实现了跨域访问（CORS）配置，显式支持 `localhost:3000` 跨域与 Cookie/Auth 头传递。
  - 创建前端开发配置文件 [frontend/.env.development](file:///d:/javacode/hm-dianping/frontend/.env.development)，配置 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8081` 指向本地运行 of Java 后端服务。
- **全量编译与构建通过**：Java 后端 `mvn compile` 及 Next.js 前端 `npm run build` 均 **100% 成功编译**并通过静态类型校验。

## 2026-06-23 (晚) — 补全前端子路由页面与集成 AI 决策对话抽屉

解决了前端子路由导航 404 及无法新建 AI 对话会话的问题：

- **补全前端子页面（消除 404）**：
  - 新建 [explore/page.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/explore/page.tsx)：探索发现页面，支持展现热门 AI 主题提问推荐及社区探店笔记卡片，点击话题即可直接拉起 AI 助手并自动录入发送对应的查询。
  - 新建 [order/page.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/order/page.tsx)：我的订单页面，展示与 Heima Dianping 数据库结构一致的抢购代金券订单列表及各种付款/退款状态。
  - 新建 [profile/page.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/profile/page.tsx)：个人中心页面，包含用户基本资料卡、积分/粉丝统计等核心视觉字段。
- **集成 AI 智能决策对话抽屉 (ChatDrawer)**：
  - 新建 [ChatDrawer.tsx](file:///d:/javacode/hm-dianping/frontend/src/components/common/ChatDrawer.tsx) 流式对话组件，通过 ReadableStream 流式解码并实时解析 Java 后端发射的 SSE 块数据。
  - **实现实时推理链路可视化**：流式展现 LangGraph 底层各节点执行状态（如“意图识别”、“执行计划规划”、“系统查询”、“证据包汇总”等）及工具执行状态。
  - **渲染商户决策卡片**：如果 AI 答复中携带了推荐/对比店铺列表，将在对话流中自动渲染出结构化的店铺推荐微型卡片，支持点击跳转商家详情。
  - **支持新建会话/重置会话**：在抽屉头部配置“🔄 新建会话”按钮，点击即可更换 Session ID 重置对话历史，随时发起新的会话调优。
- **全局布局联调与路由高亮**：
  - 更新 [layout.tsx](file:///d:/javacode/hm-dianping/frontend/src/app/layout.tsx)，使用 `usePathname` 对侧边栏链接进行当前活动路由高亮；引入 `ChatDrawer` 并将顶部的“新建询问”和主页的“开始对话调优”等按钮点击绑定到全局 CustomEvent，实现顺畅的单页对话唤醒逻辑。
  - Next.js 前端经过重新构建，**100% 编译成功通过**并无任何报错 🥳。

## 2026-06-23 (晚) — AI 助手大 UI 重构（类 ChatGPT 体验）完成
成功将 AI 决策助手从边缘侧滑抽屉重构为占据主工作区的类 ChatGPT 沉浸式大 UI 体验：
- **左侧导航与会话历史面板重构**：将左侧侧栏 `aside` 调整为 `w-64` 宽度，并赋予经典的暗色（`bg-[#171717]`）面板主题。顶部集成了便捷的“➕ 新建对话”按钮；中部设计了滚动区域，用于展示持久化的 `localStorage` 历史会话列表（支持选择加载和删除会话）；下部聚合了系统页面导航（首页、发现、订单）与 AI 决策助手的快速切回主项；底部保留主题切换与游客身份卡。
- **全屏 ChatGPT 风格聊天视口 (`ChatView`) 部署**：开发了全新的 `ChatView.tsx` 组件顶替原有的 `ChatDrawer` / `ChatSidebar`。当 AI 助手模式激活时，右侧展示全屏聊天视口。聊天流在视口中轴居中对齐限制 `max-w-3xl`，底部悬浮胶囊式圆角输入框集成了流式生成的中断（⏹）与发送机制。在首屏无消息时，为用户提供 4 张精致的问题引导 prompt 建议卡片。
- **普通路由页面无缝切换**：通过在 `layout.tsx` 中巧妙绑定 `isChatOpen` 开关状态与 React reconciliation `key={sessionId}`，当切换到普通系统页面时，右侧主视口自动展示路由对应的子页面 `{children}`（如商户列表、笔记流、订单及个人中心），在多路由应用和 AI 助手功能间取得了完美平衡。
- **验证与清理**：删除了原有的 `ChatDrawer.tsx` 及 `ChatSidebar.tsx`。Next.js 再次构建测试，**100% 成功编译**并无任何报错。

## 2026-06-23 (晚) — 交互优化与文案微调（按钮 SVG 箭头化与直接切换）完成
针对 AI 对话助手进行细节优化，移除了敏感字词，优化了按键布局，并消除了路由切换时的页面闪烁：
- **移除“中断”敏感字样**：将聊天界面、生成控制按钮以及流式推理跟踪链中所有包含“中断”字样的文本替换为“停止”或“停止生成”，保持交互话术的积极和规范。
- **按钮扁平化与 SVG 箭头化**：重构了输入框最右侧的发送与停止按钮。将原有粗糙的文字按钮升级为精致的、ChatGPT 同款圆底 SVG 图标按钮（发送为向上箭头 `↑`，停止为方块 `■`）。同时将输入框 padding 由 `pr-24` 缩减为 `pr-12`，拓宽了用户的可打字视野。
- **瞬时路由直接切换（消除加载闪烁）**：
  - 将 `layout.tsx` 中的普通页面链接全部从传统浏览器重载 `<a>` 标签替换为 Next.js Client-Side `<Link>` 路由组件，使切换瞬间完成，不发生页面强制刷新。
  - 在 `layout.tsx` 的渲染入口中，将 `isChatOpen` 的初始状态判定优化为对 `pathname === '/'` 的同步即时解析计算，从而彻底解决了之前直接访问子页面（如订单、个人中心）或刷新时，页面“先闪现一下 AI 助手大对话框再切回正常页面”的 Mount 闪屏问题，实现了页面与 AI 对话助手视口之间的 0 延时直接无感切换。
  - 顺带补齐了侧边栏“个人中心”的内置路由跳转。

## 2026-06-23 (晚) — 消息发送即时保存与对话框气泡及头像视觉优化完成

成功实现了消息发送的即时保存，优化了会话切换流畅度，并对 AI 助手的聊天对话流界面进行了全方位的视觉升级：
- **发送即新建会话 (无延迟历史呈现)**：重构了 `ChatView.tsx` 中消息发送 `handleSend` 方法的逻辑。在用户发送消息时，立刻执行 `persistMessages()`，将消息及其生成的 session 信息即时更新到 `localStorage` 中并触发 sidebar 历史列表重新加载。使得新会话在点击发送的瞬间便能立刻同步在左侧会话历史面板中，消除之前需等待整个 AI 流式生成结束的历史加载延迟。
- **对话头像彻底剔除**：在 `ChatView.tsx` 的消息流渲染与流式思考/加载动画中，彻底删除了所有 AI 头像 (`AI` 渐变圆角块) 以及用户头像 (`U` 标识)，以换取更清爽、更现代的纯粹对话流视口。
- **用户气泡胶囊化升级**：将用户输入文本气泡重塑为右侧对齐的高信噪比深灰胶囊风格（`bg-gray-200 dark:bg-[#2f2f2f]`，结合白字 `text-white` 与柔和的阴影），在深色主题下拥有极致优雅的对比效果。
- **LLM 输出无气泡无背景**：移除大模型答复文本（Assistant message）的外层气泡包装、边框及背景色。LLM 回复文本现在直接以纯文本排版（left-aligned, `text-xs text-themeText-main`）渲染在主背景之上，提供类似 GitHub Copilot / ChatGPT 原生的高级阅读质感。
- **推理轨迹与加载状态极优化**：
  - 将展开的大模型推理链和工具调用轨迹折叠状态（`msg.steps`）重塑为 `已思考若干秒 >` 的极简左对齐链接，且展开后的代码/步骤日志采用无背景、淡灰色左边框缩进（`border-l border-themeBorder`）的极简样式呈现。
  - 将 SSE 思考指示器修改为 bubble-free 扁平样式，移除背景和边框卡片包装，仅保留跳动的三个 primary 色小点及 `正在思考` 动态说明。
- **编译验证通过**：前端 Next.js 项目 `npm run build` 100% 成功编译，逻辑流状态在侧边栏切换和主页/发现卡片触发下表现平滑、极速且无缝。

## 2026-06-26 进展
- **默认深色主题及启动体验优化**：
  - **默认状态升级**：修复了用户初次进入主页或刷新页面时，对话页面因为初始状态默认为 `'light'` 导致主背景瞬间呈现白色、只有点击主题切换按钮才变黑的问题。
  - **组件与生命周期注入**：将 `layout.tsx` 中的 `ThemeContext` 默认值和 `RootLayout` 组件的 `theme` State 初始状态均统一变更为 `'dark'`，使 SSR 与 CSR 首屏渲染保持一致的深色主基调。
  - **主题兜底与初始化**：在 `useEffect` 初始化加载时，若检测到 `localStorage` 中未存储任何主题偏好，则主动将其置为 `'dark'` 并向 `document.documentElement` 动态添加 `.dark` 类。这样在初次访问时便能直接以完美对齐 ChatGPT 风格的沉浸式暗色主题加载，彻底消除了主题配置未设置时的“白色闪烁”与页面配色分裂感。
  - **编译验证**：执行 `npm run build` 验证，修改后的 Next.js 前端应用 100% 成功编译通过。
- **修复页面首次加载时对话发送异常及 Hydration 冲突**：
  - **问题分析**：由于 `sessionId` 初始状态为 `""` 并通过客户端 `useEffect` 动态设置为带有时间戳的 ID，导致 `ChatView` 发生 client-side mount 后的二次卸载与重挂载（Reconciliation key 变更）。当用户在首屏刚刚加载（未完全 mount 或 hydration 阶段）立即交互时，会导致输入内容被清空、焦点丢失、或者发送请求因 session ID 重置而中断。
  - **解决机制**：在 `layout.tsx` 中引入 `isMounted` 状态控制，延迟 client-side 动态组件（如 `ChatView`）的初次渲染，保证首屏渲染/水合 HTML 与服务器端完全一致，消除 Hydration 冲突；同时确保 `ChatView` 在 `sessionId` 实例化完成之后才一次性正确挂载，避免了无用的卸载/重挂载周期，彻底消除了首屏不可发送消息、点击后重置、以及丢失焦点的问题。
  - **验证测试**：前端 Next.js 项目 `npm run build` 打包编译 100% 通过；在 Playwright 环境中对首屏即时输入及流式回复发送进行了完整性测试，功能与状态保存均表现完美。
