# 第三层问题分析

本文件只基于当前仓库真实代码分析风险，不把目标架构当成已实现。
所有结论标注真实代码文件和行号，使用 `2026-07-05` 时点代码。

---

## P0（致命风险 — 必须优先解决）

### P0-1：可信表达没有独立权威合同

**风险**：第三层最终输出主要靠 `generate_answer()` 的 LLM verbalizer + `verify_answer()` 后验校验，缺少一个明确的 `ResponseContract` / `ResponseContract` 作为"最终回答合同"。

**真实代码**：
- `response_subgraph.py:345-357`（`_h_final_response()` 只写 `final_response` 字符串，无结构化合同）
- `final_response_builder.py:6-17`（`build_final_response()` 只包最小响应壳，不是主链路权威出口）
- `llm_verbalizer.py:429-558`（verbalize_decision_plan 返回纯文本，无结构化字段）

**影响**：
- 可信表达更多是"生成后再检查"，而不是"先约束后表达"
- API 层、graph 层、streaming 层的最终响应合同不一致
- 无法稳定追溯"这句话具体来自哪条证据"

### P0-2：`final_response` 被 8 个不同位置直接写入，无统一出口

**风险**：至少 8 个代码位置直接写 `final_response` 字符串，没有经过统一 verifier 或合同检查。

**写入位置**：
| 文件 | 行号 | 绕过统一 verifier |
|---|---|---|
| `response_subgraph.py:348`（`_h_final_response`） | 通过生成→验证→write | ⚠️ 当 draft 为空时 verifier 直接 pass（见 P0-5） |
| `response_subgraph.py:382-418`（`_h_clarify_response`） | 直接写 | ❌ 未进入统一 generate/verify |
| `response_subgraph.py:487`（`_h_fallback_answer`） | 直接写 | ❌ 未进入统一 generate/verify |
| `direct_response_workflow.py:159` | 直接写 | ❌ 绕过 |
| `deterministic_tool_workflow.py:933`（`_build_success_patch`） | 直接写 | ⚠️ workflow 内已 verify，但绕过 response_subgraph |
| `deterministic_tool_workflow.py:1028`（`_build_clarify_patch`） | 直接写 | ❌ |
| `exploration_planning_workflow.py:824`（`_build_success_patch`） | 直接写 | ⚠️ workflow 内已 verify，但绕过 response_subgraph |
| `clarification_fallback_workflow.py:233` | 直接写 | ❌ |

**影响**：
- 每个 bypass 路径都可能引入答非所问的文本
- 后续加可信表达改进时，无法保证覆盖所有出口

### P0-3：`generate_answer()` 仍是 LLM verbalizer 主路径，规则化 fallback 是兜底不是合同

**风险**：真正的自然语言答案仍由 LLM verbalizer 生成。规则化 fallback 只是兜底，不是主合同。

**真实代码**：
- `generator.py:605-700`：`generate_answer()` 主路径调用 `verbalize_decision_plan()`
- `llm_verbalizer.py:444-504`：三层 fallback（LLM 不可用→prompt 失败→LLM 异常→`_rule_based_verbalize`）
- `generator.py:664-670`：当 `config.ENABLE_LLM_VERBALIZER == False` 时返回固定占位符 `"【LLM 服务未启用】无法生成自然语言回答。"`——即使证据足够，也不会生成有意义回答

**影响**：
- 一旦 verbalizer 提示词或模型行为漂移，回答风格和忠实度都会受到影响
- LLM 禁用时零表达能力，没有任何 deterministic 保底

### P0-4：`ResponseMode` 没有统一 Enum，7+ 个字符串散落各处

**风险**：`response_mode` 是纯字符串，没有统一枚举或校验。

**真实代码**：
- `_routes.py:310`：`_route_workflow_runner` 直接比较字符串 `"discovery_decision"`、`"planning_subgraph"`、`"comparison"`
- `response_subgraph.py:131-154`：四路分支比较 `"direct_response"`、`"exploration_plan"`、`"clarify"`、`"fallback"` 等
- `deterministic_tool_workflow.py:906`：写入 `"direct"`
- `direct_response_workflow.py:156`：写入 `"direct_response"`
- `exploration_planning_workflow.py:1093`：写入 `"exploration_plan"`
- `clarification_fallback_workflow.py:230`：写入 `"clarify"`
- `orchestration_router_shadow.py`：写入 `"reject"`

**目前至少有 7 个不同的字符串值**：`direct_response`、`reject`、`direct`、`exploration_plan`、`clarify`、`fallback`、`answer`。

`"answer"`、`"tool_answer"`、`"comparison"` 作为 response_mode 值存在，但 `response_subgraph.py:133-152` 中没有一个专门的分支处理它们——都落入第 154 行的通用 answer 路径。

**影响**：
- 新增模式必须手动保证所有消费点同步更新
- 没有校验，非法字符串不会被发现
- 路由逻辑无法集中审计

### P0-5：`verify_answer()` 在 evidence 为空或 draft 为空时直接 pass

**风险**：当 evidence 为空或 `draft_response` 为空时，不做任何校验直接返回 pass。

**真实代码**：
- `response_subgraph.py:290-298`（`_h_answer_verify`）：
  ```python
  if not evidence or not state.get("draft_response", ""):
      return {
          "verify_result": "pass",
          "verifier_recoverable": True,
      }
  ```
- `verifier.py:625-664`（`verify_answer` 主逻辑）中对空 draft 的无 check 返回

**影响**：
- 空回答或零证据回答会通过校验进入 `final_response`
- 用户可能看到空文本或 LLM 编造的"无证据"文本

### P0-6：`_h_rewrite` 只递增计数器，没有结构化 RewriteInstruction

**风险**：`_h_rewrite` 只做 `rewrite_count += 1`，没有任何结构化修复指令。

**真实代码**：
- `response_subgraph.py:339-342`：
  ```python
  def _h_rewrite(state: GraphState) -> dict:
      rc = state.get("rewrite_count", 0) + 1
      txt = state.get("draft_response", "")
      return {"draft_response": txt, "rewrite_count": rc}
  ```
- `llm_verbalizer.py:134-152`：LLM verbalizer 内部有简单 rewrite 指令文本（当 `rewrite_count > 0` 时在 prompt 中追加一段中文指令），但不是结构化的

**影响**：
- 重写无法精确修复特定 claim
- 上限 `MAX_REWRITE_ATTEMPTS = 2`（`config.py:175`），但 `_routes.py:279` 和 `llm_verbalizer.py:12` 实际使用时 `max(1, MAX_REWRITE_ATTEMPTS - 1) = 1`——实际只重写 1 次
- 根本不知道为什么 rewrite 失败/成功

### P0-7：没有 ClaimExtractor，verifier 只靠文本规则和 LLM

**风险**：当前 verifier 不从 draft_response 中抽取结构化 claims 做证据对齐。

**真实代码**：
- `verifier.py:243-346`（`_facet_rules`）：纯中文关键词匹配（"有券"、"营业中"、"公里"、"评分"、"人均"）
- `verifier.py:400-474`（`_comparison_issues`）：纯文本规则（检查"更好"、"更优"、"胜出"等关键词）
- `b2_mini_verifier.py:362-558`：LLM 做完整文本判断
- 没有 `ClaimExtractor` 模块，没有从文本中抽取 `(claim_type, shop_id, value, evidence_ref)` 的结构化步骤

**影响**：
- 关键词匹配对复杂句式（否定、假设、反问）完全无效
- LLM verifier 成本高且不保证结构化输出
- 无 claim 级可追溯性

### P0-8：`final_response` 与 `preview_text` 语义不统一

**风险**：`final_response` 是 graph 内最终字段，`preview_text` 是流式预览，两者没有统一结构化合同。

**真实代码**：
- `response_subgraph.py:345-357`（`_h_final_response` 写 `final_response` 和 `preview_text`）
- `preview_policy.py:29-43`（`sanitize_preview_text` 单独过滤增量文本）
- `app.py:120-166`（`event_stream` 在每个 delta 上调用 `sanitize_preview_text`）
- `app.py:194-226`（流式终点组装 final payload，字段来自 `final_response` + `cards` + `suggested_replies`）

**影响**：
- "展示给用户的内容"、"最终图状态中的内容"、"流式预览内容"三者边界不清
- 调试"最终用户到底看到了什么"比较困难

---

## P1（重要风险 — 需要在第三层收敛前解决）

### P1-1：独立 workflow 提前写 `final_response`，绕过统一 verifier 和合同

**风险**：三个独立 workflow 都直接写 `final_response`，但只在 workflow 内部 verify。

**真实代码**：
- `direct_response_workflow.py:156-159`：`final_response` 直接写入，无 verifier
- `deterministic_tool_workflow.py:849-955`（`_build_success_patch`）：第 933 行写入 `final_response`，第 931 行写入 `evidence_pack`——完全不经过 `response_subgraph` 的统一流水线
- `exploration_planning_workflow.py:795-837`（`_build_success_patch`）：第 824 行写入 `final_response`，第 822 行写入 `evidence_pack`

**绕过路径**：`_routes.py:311-320` 的 `_route_workflow_runner()` 对 `response_mode` 做三重判定路由（workflow_name / workflow_callable / response_mode），`response_subgraph.py:128-173` 的入口处对 `direct_response` 和 `exploration_plan` 做了 pass-through（第 133 行）——这些 workflow 写入的 `final_response` 实际上绕过了统一 LLM verbalizer 和 verifier。

**影响**：后续在第三层加任何统一 contract 或 verifier 改进，都无法覆盖这三个 workflow 的输出。

### P1-2：`response_subgraph` 同时承担 plan / generate / verify / rewrite / fallback / clarify

**风险**：第三层子图已经把表达、校验、重写、兜底、澄清全包了。

**真实代码**：
- `response_subgraph.py:128-173`：mode 分支
- `response_subgraph.py:181-357`：build → generate → verify → rewrite → final_response
- `response_subgraph.py:375-490`：clarify / fallback
- `response_subgraph.py:44-125`：`_compose_single_shop_response` 单店保守渲染

**影响**：
- 边界过宽，后续如果继续加"可信表达"规则，会继续塞进同一个大子图
- 无法独立升级/测试特定模块

### P1-3：`_compose_single_shop_response()` 只覆盖 coupon / open_status / distance 三个 facet

**风险**：单店事实回答的保守修正只对三个 facet 有处理。

**真实代码**：
- `response_subgraph.py:44-125`（`_compose_single_shop_response`）：
  - 第 69-81 行：coupon
  - 第 82-92 行：open_status
  - 第 93-107 行：distance
  - 第 113 行：`draft_text.strip() or f"{shop_name}的信息我已经整理好了。"`（无 facet 时的通用兜底）

**缺少**：`rating`、`avg_price`、`review_summary`、多个 facet 组合。

**影响**：
- 推荐、对比、探索在表达上没有统一的可信表达策略
- 单店多 facet 组合查询（"评分多少、人均多少、有什么券"）只能落到无意义的兜底

### P1-4：没有 `ResponseContract`，`final_response` / `answer_text` / `preview_text` 三者缺少权威顺序

**风险**：graph 内部字段和 streaming payload 字段不完全同构。

**真实代码**：
- `response_subgraph.py:191-357`：写 `final_response` + `draft_response` + `preview_text`
- `app.py:194-226`：流式终点组装 answer_text、cards、suggested_replies、shops、vouchers
- 没有 `ResponseContract` 验证最终输出结构

**影响**：
- 无法保证"最终用户看到的" = "graph 输出的" = "trace 记录的"

### P1-5：没有 claim-based verification，verifier 无法细粒度定位问题

**风险**：当前 verifier 只有文本级规则和 LLM 整体判断。

**真实代码**：
- `verifier.py:243-346`：`_facet_rules` 关键词规则——只能检测文本中"有没有某关键词"，不能检测"某 claim 是否正确表达了证据"
- `verifier.py:498-622`：`_deterministic_verify`——整体性校验，没有 claim 级定位
- `b2_mini_verifier.py:362-558`：LLM 做整体文本判断

**影响**：
- 无法精确告诉 generator/rewriter "哪句话有问题"
- rewrite 时只能整体重生成，不能局部修复

### P1-6：`conversation_continuity` 只是 metadata，但可能存在被误用为事实源的风险

**风险**：`_build_conversation_continuity()` 从 session 里抽取 `previous_focus`、`previous_task_type`、`inherited_constraints`，但它被注释为 metadata only。

**真实代码**：
- `_compat.py:586-632`（`_build_conversation_continuity`）：从 `SessionState` 读取历史焦点，全部设成 metadata-only

**影响**：
- 未来如果把连续性提示误当事实，会导致错误续答
- 无明确隔离机制防止其渗入 `AnswerPlan`

### P1-7：rewrite 上限语义不直观，实际只执行 1 次

**风险**：配置值 `MAX_REWRITE_ATTEMPTS = 2`，但实际 rewrite 上限 = `max(1, MAX_REWRITE_ATTEMPTS - 1) = 1`。

**真实代码**：
- `config.py:175`：`MAX_REWRITE_ATTEMPTS = 2`
- `llm_verbalizer.py:12`：`_GRAPH_REWRITE_LIMIT = max(1, MAX_REWRITE_ATTEMPTS - 1)`
- `_routes.py:279`：同样使用 `max(1, MAX_REWRITE_ATTEMPTS - 1)`
- `response_subgraph.py:156-157`：还叠加了 `BudgetContext.remaining("rewrite_budget")` 限制

**影响**：
- 配置不直观，改 MAX_REWRITE_ATTEMPTS 不一定按预期生效
- 三层控制（config 值、减一逻辑、budget）不可集中审计

### P1-8：部分 workflow 在回答层内部写 `SessionState`

**风险**：当前 `SessionState` 被部分 workflow 修改，但没有被 `response_subgraph` 校验。

**真实代码**：
- `deterministic_tool_workflow.py:293-596`：目标解析中反复读取/可能写入 `session_state` 和 `session_state_before`
- `exploration_planning_workflow.py:1046`：`apply_state_update_plan()`（`state_update_plan_preview`）可能会写 `SessionState`

**影响**：
- `SessionState` 在独立 workflow 和 `response_subgraph` 之间没有被隔离
- workflow 在写入 `final_response` 后可能已修改 `SessionState`，`response_subgraph` 不会再次校验

---

## P2（关注风险 — 在第三层收敛中一并解决）

### P2-1：verifier 的 LLM 切换条件缺少策略化入口

**风险**：`_needs_llm_verification()` 的逻辑是硬编码的，不是策略对象。

**真实代码**：
- `verifier.py:219-232`：`_needs_llm_verification()` 判断依据：
  - `answer_type in {"comparison", "exploration_plan", "exploration"}`
  - `answer_type == "recommendation"` 且 `has comparison_matrix`
  - `selected_targets > 2`
  - `evidence.get("answer_verify_force_llm")`

**影响**：无法通过配置/策略动态切换，需要改代码才能调整。

### P2-2：fallback 覆盖范围有限，主要集中于单店

**风险**：`_h_fallback_answer()` 主要覆盖单店场景。

**真实代码**：
- `response_subgraph.py:422-491`：
  - 第 450-467 行：单店营业状态
  - 第 468-472 行：单店优惠券
  - 第 473-485 行：工具失败 / 熔断 / unknown / unsupported
  - 第 423 行：其他情况退化为"抱歉，暂时无法处理您的请求"

**影响**：
- 比较、推荐、探索规划的 fallback 文案等于通用的"暂时无法处理"
- 用户得不到任何有用信息

### P2-3：回答相关测试有局部覆盖但缺少合同级测试

**现有测试**：
- `test_answer_verifier.py`
- `test_llm_verbalizer.py`
- `test_p4_evidence_decision_answer_protocol.py`
- `test_p10_experience_performance.py`
- `test_phase7_workflows.py`
- `test_e2e_llm_main_path.py`

**缺口**：
- 缺少可信表达合同测试
- 缺少 citation / confidence / uncertainty 的端到端测试
- 缺少 response envelope 的契约测试
- 缺少 workflow bypass 路径的边界测试

### P2-4：`draft_response`、`final_response`、`preview_text`、`answer_text` 四者缺少映射关系

**风险**：四个文本字段之间的转换关系没有统一管理。

**真实代码**：
- `draft_response`：由 `generate_answer()` 写入（`response_subgraph.py:203`）
- `final_response`：由 `_h_final_response()` 从 `draft_response` 复制（`response_subgraph.py:348`），或被 8 个 bypass 位置直接写入
- `preview_text`：由 `_h_final_response()` 同行写入（`response_subgraph.py:348`），或被 `event_stream` 消费
- `answer_text`：在 `app.py:194-226` 由 `event_stream` 组装，来源是 `final_response`

**影响**：
- 无法保证 `preview_text` 最终展示的和 `final_response` 一致
- `answer_text` 可能和 `final_response` 不一致（在 `app.py` 中有额外处理逻辑）

### P2-5：第三层 trace 缺少每个阶段的独立 span

**风险**：当前 trace 把 generation / verification / rewrite / fallback 合并为一个长 span。

**真实代码**：
- `trace.py:80-198`：`TurnTrace` 能收集 `response_mode`、`answer_source`、`verifier_result`、`fallback_reason`、`rewrite_count`
- `trace.py:386-573`：`build_turn_trace()` 从整个 graph state 拼 trace，`response_subgraph` 内部没有插入额外的 trace span

**缺少**：
- 每个阶段的独立 span（generation / verification / rewrite / fallback）
- `rewrite_reason` 的结构化记录（当前只是字符串）
- `degraded_reason` 的标准化枚举

### P2-6：预览层只做过滤，不做结构化可信表达

**风险**：`sanitize_preview_text()` 只能挡住未验证 claim 的流式文本。

**真实代码**：
- `preview_policy.py:29-43`：`can_emit_preview(text, verified=False)` 基于 `verified` 布尔值做过滤

**影响**：
- 预览层解决了"别乱播"，但没有解决"怎么清晰表达可信度"
- 预览不展示 `confidence`、`uncertainty`、`source` 等结构化信息

### P2-7：`build_final_response()` 存在但没有成为主出口

**风险**：`build_final_response()` 只返回一个简单 dict，没有统一接管主回答链。

**真实代码**：
- `final_response_builder.py:6-17`：只返回 `answer_text`、`trace_id`、`session_id`、`clarification`、`cards`

**影响**：
- API 层、graph 层、streaming 层的最终响应合同不一致
- 如果需要统一搬家到 `ResponseContract`，`build_final_response()` 需要升级或废弃

---

## 文档与代码偏差

用户想要的"第三层：回答层 / 可信表达层"与当前代码的偏差：

- 当前没有独立的 `ResponseContract` / `ResponseContract`
- 当前 `ResponseMode` 是散落字符串，不是 Enum
- 当前没有 `ClaimExtractor`，verifier 无法做 claim-based verification
- 当前没有 `RewriteInstruction`，rewrite 只是计数
- 当前 `final_response` 从 8 个位置写入，无统一出口
- 当前没有 `DeterministicComposer` 覆盖推荐/对比/探索场景
- 当前第三层 trace 缺少每个阶段的独立 span
- 当前 `AnswerPlan` 职责过重（89 个字段），需要收敛为输入 DTO
