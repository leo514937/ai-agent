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


