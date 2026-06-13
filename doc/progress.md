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
