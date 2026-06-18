# AI 助手优化及旧链路清理进展

## 已完成工作

1. **前端交互优化**
   - 优化了 `AssistantComposer.vue` 的输入体验。
   - 实现了打开 AI 助手页面时默认自动对焦输入框。
   - 实现了在发送完一条消息并在加载完成（loading 状态切换）后，自动重新对焦输入框，避免用户需要手动点击。

2. **RAG 模块引入与路径修复**
   - 修复了 `learning_agent_service/rag/retrieval/__init__.py` 中的路径导入错误（飘红问题）。
   - 通过 Facade 设计模式重新暴露了 `rag_retrieval_pipeline`，确保系统能正确找到检索逻辑。

3. **后端图执行器 (LangGraph) Bug 修复**
   - **问题现象**：AI 大模型经常返回兜底的 “候选店 A/B/C” 内容，且 Java 后端 `UserServiceImpl.signCount` 出现 `UserHolder.getUser()` 为空的空指针异常。同时，即便大模型找对了，最终答案仍为兜底。
   - **根本原因**：LangGraph 在重构后使用了新的 `builder.py` 里的 `add_conditional_edges` 来进行节点间路由。然而，原有的子图 `subgraphs.py` 中的 `run_rag_subgraph` 仍返回旧版的 `Command(goto="compose_answer")`。新版 LangGraph 会优先遵从 `goto` 指令去强行跳转到 `compose_answer` 节点（该节点在新的拓扑里已被重命名或替代），导致发生 “Unknown channel” 错误从而被抛弃，最后触发了兜底话术。
   - **修复方案**：全面移除了 `subgraphs.py` 里对于 `Command(goto=target)` 的旧有图跳跃指令，统一改为直接返回 `state`，完美兼容并服从 `builder.py` 中新设计的 `add_conditional_edges` 编排。

4. **旧链路梳理与清理方案输出**
   - 真实统计了旧链路（`application/router` 以及 `runner.py`）未被删除的代码，累计约 **10,360 行**。
   - 整理出了新旧链路功能的模块替代映射表格（如 `phase0` -> `front adapters`, `runner.py` -> `LangGraphWorkflowRunner` 等）。
   - 最终成果已形成清理指导文档，存放在 `todo/old_link_cleanup.md` 中。

## 下一步计划
- 按照 `todo/old_link_cleanup.md` 中的步骤，逐步抽离 `adapters` 对旧链路工具函数的依赖，随后即可正式废弃这上万行旧代码。

---
## 最新进展 (当前会话)
1. **修复 RAG 门控拦截**
   - 修复了 `rag_gate.py` 中的意图拦截：短查询如“附近有什么推荐菜”之前会因为长度不够或 token 较少被判定为 `low_information` 并拦截，现在只要包含特定的意图词汇（推荐、附近、哪家等），就会予以放行。
2. **清理写死的测试兜底数据**
   - 修复了 `stages_back_core.py` 与 `stages_back_emit.py` 中写死的 `selected_shop_id in {3, 5}` 测试逻辑（导致命中“海底捞”与“新白鹿”时数据固定异常）。
   - 修复了因为生成的答案缺乏特定商铺名而导致整个输出被强行覆盖成“目前只能先给你一个部分判断。整体来看，这家店值得继续关注”的 Bug。
   - 现在用户提问特定门店或推荐，将会给出真实的、基于知识库和业务接口的数据，而不会再轻易触发硬编码兜底。

3. **深度验证与优化 RAG 重构 (基于架构审查)**
   - **移除硬编码兜底**：清理了 `rag/heuristics.py` 中写死的中文关键词语料（如 `_CN_COMPARE`、`_CN_COUPON` 等），将它们统一重构为从外部 `DomainRulesConfig` 中动态读取 (`_rule_tokens()`)，解决了本地生活领域规则硬编码严重的问题。
   - **整合 RetrievalQualityGuard**：将 `RetrievalQualityGuard` 成功编排进 `HybridRAGOrchestrator`（位于 `search.py` 与 `service.py`），对低质量的检索证据执行拦截与打分（`quality_verdict`），避免劣质证据直接进入回答。
   - **修复 RAG 过滤回归问题**：修复了 `test_qdrant_filter_builder.py` 中关于元数据硬过滤 (`owner_id`) 校验不匹配的导致测试用例挂掉的 bug，将测试用例中的字段升级为 `tenant_owner_id`，使其符合最新版权限设计语义。
   - **补充验收结论**：目前已通过单元测试 (`tests/rag/...`) 回归确认 P0 问题全面闭环。

4. **铲除旧执行架构 (SequentialWorkflowRunner) 及附属死代码**
   - **完成类目重命名与死代码删除**：将冗余庞杂的 `SequentialWorkflowRunner` 重命名为 `BaseWorkflowRunner`，彻底删除了其内部 700+ 行已经作废的串行执行分支（包括 `_invoke_stage_with_heartbeat_streaming`、`run_state`、旧式 `rag_plus_tool` 串接代码等）。
   - **清理周边依赖**：更新了 `builder.py`，使 `LangGraphWorkflowRunner` 继承自轻量干净的 `BaseWorkflowRunner`；并同步修改了 `__init__.py` 中的对外暴露，告别了“历史包袱”，项目执行链路实现了大规模瘦身。
   - **深度清理本地生活冗余分支**：在确认 LangGraph（位于 `adapters/stages_*.py`）已全盘接管后，安全抹除了 `local_life/subgraph/` 整套基于 Python Generator 的遗留生成器控制流流水线，成功“减负”约 200KB 代码。
   - **清除历史坏死测试**：伴随核心链路旧代码的移除，进一步清理了 `tests/` 目录下因为缺少依赖而导致 Collection Error 的 7 个死代码测试文件（主要是专门针对 `SequentialWorkflowRunner` 和 `LocalLifeSubgraph` 编写的老旧测试），排除了虚假的代码覆盖率干扰并恢复了测试流水线的纯净。

5. **全量修复核心业务类中的静态类型检查警告 (NoneType Error 隐患)**
   - 彻底梳理并修复了大量因为弱类型设计和 `_clean_text` 的 `str | None` 返回值所带来的类型推断断层（Pyrefly 警告）。
   - 修复了 `answer_quality_gate.py` 和 `answer_structure_composer.py` 中底层拼接空指针及 `int(None)` 运行时的致命报错风险。
   - 修复了 `entity_resolver.py` 多次因为 `NoneType` 缺失 `replace` 与 `strip` 方法而产生的隐式运行时崩溃隐患。
   - 修复了 `query_router.py` 中的二次求值引起的类型约束丢失，以及 `tool_result_normalizer.py` 里 Pydantic 的类型验证不匹配。
   - 修复了 `slot_extractor.py` 和 `tool_planner.py` 中的底层字典 `NoneType` 提取报错问题，成功让整个模块对类型系统“全绿”。
   - 彻底梳理并修复了 `memory/service.py` 中的一系列静态类型陷阱，包括 `Never` 变量收窄赋值、强类型 Enum 的属性提取、`Sequence[Any]` 对比 `Iterable[Any]` 签名的限制冲突，甚至移除了极度反模式的 `locals()` 隐式判定。
   - 修复了 `rag/local_life/orchestrator.py` 在提取 Qdrant 返回的弱类型 payload 时，由于返回值混杂 `Unknown | object` 导致 `list()` 构造函数因缺乏 `Iterable` 断言而报警的问题，全面植入了零运行开销的 `typing.cast`。

6. **重构本地生活店名实体抽取与多店比较链路**
   - 彻底贯彻了“规则优先召回候选、LLM 只做语义消歧、规则最终校验落库”的设计架构，避免了原先让 LLM 盲目生成店名可能带来的串店和上下文污染问题。
   - 修复了因为早期重构导致的大量 `ImportError`（如 `_explicit_entity_from_query`、`_resolve_alias_from_contexts` 等历史依赖方法丢失），补充了这些函数的逻辑以确保向后兼容与测试流水线的正常收集。
   - 为 `EntityResolver` 的 `SemanticSelector` 模块正确补齐了 `OpenAIRuntime` 运行时注入代码，重新激活了 LLM 真实的推理调用，使其能够基于用户的自然语言和历史对话精确地从候选项中“语义消歧”，杜绝了静默的逻辑逃课。
   - 更新了 `TargetShop` 和 `ExecutionContract` 核心结构，加入了 `comparison_targets` 字段；并在路由逻辑（如 `FacetExecutionPlan` 组装和 `validate` 校验流）中打通了“多店比较”对象的下发透传，使得像“海底捞和湖畔私房菜哪个好”这种复杂的多店铺对比意图能够正确路由给执行网关。
   - **(当前进行中) 修复未收录店名的静默回退 Bug**：在测试用例 `test_explicit_shop_beats_history_anchor` 中，发现当用户明确指定的店名（如“巴奴毛肚火锅”）不在库中时，虽然策略引擎（`TargetShopPolicy`）正确解析了该店名但 `shop_id=None`，可是 `route_review.py` 在拼接 `execution_requirements` 时因为 `target_shop.candidate_shop_ids` 为空，错误地 fallback 回了上一轮上下文（“海底捞”），导致后续节点取到了错误的数据并给出了错误回答。目前已定位并正在修复 `route_review.py` 和 `TargetShopPolicy` 中关于未知实体时的 `candidate_shop_ids` 分发逻辑。

7. **引入 grounded_strict 强约束回答模式**
   - 在 `composer.py` 中引入了 `grounded_strict` 模式，针对不同复杂意图（如对比、多店推荐等），提供了严格的结构化代码模板（如 `build_comparison_answer`），不再依赖 LLM 自由发挥补全。
   - 在答案生成前置增加了 `_strict_preflight_check` 和 `validate_answer_against_contract`，通过强校验断言拦截，有效杜绝了由于证据不足导致的大模型幻觉（Hallucination）。

## RAG 向量数据库商户简称强匹配空回问题修复 (RAG Metadata Exact Match Empty Pack Fix)
- 引入 EntityResolver 至 synthesize_retrieval_plan 以解析提取到的商户简称为具有置信度的规范命名、别名和 shop_id。
- 重构 qdrant_filters.py 的 shop_name 强等于匹配逻辑，分级优先采用 shop_id、官方名和 alias_names，避免名称不精准拦截数据。
- 在 retrieval_service.py 中增加了 RAG 宽松重试机制 (Relaxed Retry)：遇到 0 hits 时卸载商户强过滤进行二次查询，并基于 Python 代码实现防串店精准后过滤。
- 增加了检索 filter_strategy、重试次数、失败原因等结构化日志指标。

## 工具链路商户别名识别与防串店机制升级 (ToolCall Entity Resolution & Anti-Spoofing Fix)
- 发现 ToolCall 链路在处理如“海底捞水晶城店怎么样”这样的别名/简称时，如果 `shop_id` 未下发，底层工具（如 `_search_coupons`, `_check_open_status`）会静默 fallback 给假空结果或返回错误数据。
- 将 `EntityResolver` 集成至 `routing_signals/base.py` 的 `synthesize_tool_selection` 层：
  - 在决定工具调用和构建 payload 之前，统一提取 `shop_name` 并利用模型解析得到具有高置信度的 `shop_id`。
  - 对于产生多候选且置信度低，或需要澄清 (`should_clarify=True`) 的商户名称，直接拒绝生成明确的 tool 工具调用，迫使上游系统进入 Clarification 追问流程。
- 防护底层 `builtin.py` 接口：重构 `_search_coupons`, `_check_open_status`, `_get_distance_eta`，当外部直接指定 `shop_name` 且匹配不到正确的 `shop_id` 时，不盲目进行 `shop_id=0` 或错误名称查询，而是返回显式的 `error="shop_not_resolved"` 和 `empty_reason="multiple_candidates"`，以保证业务响应诚实、杜绝假空现象。

## P0/P1 商户解析结果强约束与假空值修复 (Shop Resolution & Fake Empty Values Fix)
- 引入了 `ShopResolveResult` 枚举类 (RESOLVED / NOT_FOUND / AMBIGUOUS / LOW_CONFIDENCE)，并在 `TargetShop` 和 `ResolvedTarget` 结构中透传解析结果。
- Qdrant RAG：修改了 `qdrant_filters.py`，将 `shop_name` 无条件设为 handled_keys，彻底屏蔽由于括号后缀不一致导致的 MatchValue 强制阻断（empty_pack）。
- ToolCall 解析对齐：修改了 `orchestrator_components.py` 中的工具执行载荷构建，使 ToolCall 完全继承由上游生成的 `resolved_shop_id`，保证 RAG 和 Tool 调用链路上的店铺实体一致性。
- 多店歧义防串店与禁止假空：在 `builtin.py` 中，放宽 `_resolve_catalog_shop` 搜索。如果仅有名称且命中多店非精确匹配时返回 `None` 以触发追问；全面剥离在遇到多店歧义或未找到解析店铺时的误导性假空值（如 `coupons=[]`, `distance_km=0.0`, `open_status=unknown`），改由底层直接抛出明确的 `error=shop_not_resolved` 及 `empty_reason=multiple_candidates`。

## 当前会话调查：商户名称匹配差异 (ToolCall vs RAG)
- **ToolCall 链路名称匹配瓶颈**：
  - 用户输入 `"海底捞水晶城店"` 时，通过 `_build_tool_input` 传给工具。
  - 工具通过 `_resolve_catalog_shop` 调用 `search_shops_by_name`，后台由于 SQL 中的模糊匹配 `LIKE '%海底捞水晶城店%'` 无法匹配到数据库中的 `"海底捞火锅(水晶城购物中心店）"`，导致首轮返回空。
  - 虽然 fallback 机制能拉回所有 `"海底捞"` 分店，但由于多店结果（`len(shops) > 1`）以及 `"海底捞水晶城店"` 不是 `"海底捞火锅(水晶城购物中心店）"` 的子串，最终校验 `search_name in first_shop_name` 失败，返回 `None`，触发 `shop_not_resolved`。
- **RAG 链路容错能力**：
  - RAG 链路在实体解析置信度低（`confidence < 0.5`）时，不会强加 `shop_name` 的 Metadata 强过滤，完全依赖 Qdrant 向量检索。
  - 即使添加了强过滤导致召回为 0，`retrieval_service.py` 内部拥有 **宽松重试机制 (Relaxed Retry)**，会自动脱掉 `shop_name` 等强过滤条件，将其拼入检索文本中进行二次重试，最后在 Python 内存中对结果进行 `shop_id` 的后过滤，从而避免了硬编码名称匹配失败导致的 0 召回。

## 禹墨科技教育·教案辅助设计智能体展示汇报页面开发
- **当前阶段：已完成开发并交付**
  - **交付文件**：[yumo_agent_presentation.html](file:///d:/javacode/hm-dianping/doc/yumo_agent_presentation.html)
  - **核心特色与功能**：
    - **“水墨微光”双色调主题**：支持极客极简深色主题（墨色金石）与纸张古朴浅色主题（宣纸墨香），适配汇报演示的不同光线场景。
    - **多案例交互对话模拟器**：预置了三个典型跨学科探究案例：
      1. *简易净水装置*（小学/初中，偏物理与观察，强化**摹略**与**逢疑/遇疑**）
      2. *桥梁承重优化*（初中/高中，偏工程结构，强化**双故**与**过疑**）
      3. *智能浇灌控制系统*（高中/大学，偏软硬件算法逻辑，强化**双故**与**遇疑Fail-safe**）
    - **双栏共创工作区**：左侧动态渲染智能体向导交互过程（包括推荐策略和引导性单选按钮），右侧实时同步渲染、生成并拼接结构化教案草稿，生动还原“对话式向导”而非“一键生成器”的设计定位。
    - **禹墨科学思想理论看板**：详尽展示了《墨经》科学思想在现代项目式教学中的转化应用，卡片式展示“四阶八法”（摹略万物、双故因果、测试研取、四疑反思）和四大核心设计原则。
    - **多格式导出与打印适配**：支持一键导出结构化 Markdown 源码，并针对纸张打印做了 CSS 媒体查询适配，支持一键保存 PDF 或打印输出纸质教案。

## 最新进展 (2026-06-18)
1. **解决 Python 服务启动时导入错误的问题**
   - **Stages 模块文件恢复**：定位到 `application/router/stages` 目录下的所有核心 `.py` 逻辑文件（如 `request_legality.py`, `complexity_router.py` 等 11 个文件）在本地均被误删除。使用 `git restore` 成功还原了该目录下的所有源码。
   - **Routing Signals 模块文件恢复**：定位到 `application/routing_signals` 目录下的核心 `__init__.py` 和 `base.py` 也被误删除，同样通过 `git restore` 成功恢复。
   - **消除重名包解析冲突**：解决了本地存在 untracked 废弃兼容桩文件 `routing_signals.py` 与正常还原的包文件夹 `routing_signals` 同名冲突、导致 Python 抛出 `is not a package` 导入错误的问题。已将冲突的临时文件 `routing_signals.py` 安全移动到 `scratch/routing_signals.py.bak` 备份并移除。
   - **验证成功**：重新运行 `start_all.sh` 脚本和手动测试，Python 服务的 `/health` 接口成功响应 `"status": "healthy", "ready": true`，模型网关、Qdrant 向量存储、Redis 缓存、PostgreSQL 数据库等全栈依赖均返回 `ready: true` 正常态。
2. **修复问答归因（final_answer 节点）的 `AttributeError` 崩溃**
   - **定位问题**：当用户发送类似于“你好”的消息时，后台 LangGraph 在进入 `final_answer` 节点时，会调用 `grounding_policy.py` 的 `claim_policy_for_facet`。但由于 `answer_style` 为 `None`，导致执行 `_clean_text(answer_style).lower()` 时抛出 `AttributeError: 'NoneType' object has no attribute 'lower'` 崩溃并使会话流中断。
   - **修复逻辑**：在 `grounding_policy.py` 中对 `answer_style` 和 `facet` 属性在调用 `.lower()` 前进行了安全性的判空（None/空字符串）防御检查。
   - **测试验证**：编写了测试脚本 `scratch/test_policy.py`，经验证已能在 `answer_style` 为 `None` 时顺利解析返回，AI 服务完全恢复正常运转。
