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
  - 在推送前，对 Python 端的所有单元与集成测试进行校验 (共 272 个测试)，以及 Java 端的代码编译，全部通过 ✅。
  - 将所有本地修改和新增文件（包括 `local_life_agent/` 目录下的 Python 代码和测试，以及 Java 端 Streaming Event 系列代码）提交并推送至 GitHub 远程仓库的 `toolcall` 分支。
