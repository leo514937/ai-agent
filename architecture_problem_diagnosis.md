# Python 本地生活服务架构问题诊断文档

> 结论先行：当前系统的主要问题，**不只是模型不够聪明**，而是“路由过早收口、RAG / toolcall 组合脆弱、证据门槛与回答兜底策略不合理”共同放大了答非所问的体感。
>
> 更精确地说：当前问题不是缺少 RAG、toolcall、memory，而是缺少一条从用户需求到任务计划、从证据到答案的强约束链路。

这份文档只回答“问题是什么、为什么会答非所问”。具体改造方案见：[改进实施文档](architecture_improvement_plan.md)。

## 1. 总体判断：能力都有，但约束链路不够强

当前链路已经具备：

- routing
- RAG
- toolcall
- memory
- compose_answer
- LangGraphWorkflowRunner / SequentialWorkflowRunner
- 证据门控
- session persistence / memory promotion

但这些能力之间的约束关系还不够稳定。系统更像是“先猜一个 `required_action`，然后让后续节点围绕这个动作补救”，而不是“先理解用户真正需要哪些 facets，再决定需要哪些证据和工具结果”。

因此，问题不应继续被粗略归因成：

- 模型理解不准
- 检索不准
- 工具没调好

更适合收敛为下面这组工程问题：

- 用户需求没有被稳定解析成 `required_facets`
- `required_action` 过早决定执行路径
- 多能力任务缺少显式 `TaskPlan`
- RAG evidence 和 tool result 缺少实体级对齐
- `compose_answer` 缺少 `AnswerContract / AnswerVerifier`
- `no_answer / weak_answer` 的兜底策略过于保守或模板化
- memory 参与了上下文增强，但还缺少 `MemoryRelevanceGate` 来防止历史上下文污染当前 query

## 2. 当前真实链路里的核心问题

### 2.1 routing 过早收口，后面几乎没有纠错机会

当前链路里，`load_context -> understand_turn -> rag/tool/compose` 的分工看起来清晰，但实际含义是：

- `load_context` 中会通过 `build_initial_routing_decision` 给出初始路由。
- 如果初始结果是 `clarify / reject / direct_answer / memory_update / no_op`，会直接记录 terminal routing 并返回。
- `parse_intent_slots` 对同样的 terminal action 再次早停，不再调用模型理解做复核。

对应代码位置：

- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:376`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:387`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:434`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:441`

这会导致：

- 用户输入稍微口语化、上下文指代稍微隐晦，系统就先猜一个 action。
- 一旦猜错，后面的 RAG、toolcall、答案生成都很难把它拉回来。
- 用户感受到的是“它好像看懂了，但回答总差一点”。

这个问题的重点不是“不要 routing”，而是不要让 initial routing 一次性决定 `direct_answer / clarify / reject / no_op`。对于本地生活场景，尤其要对含有本地生活信号、上下文指代、多约束推荐、券、营业、距离、评价等信号的 query 做二次复核。

### 2.2 `required_action` 表达力不足，组合任务被压扁成单动作

当前 `required_action` 主要表达“下一步该走哪个大分支”：

- `direct_answer`
- `clarify`
- `rag_retrieval`
- `tool_call`
- `rag_plus_tool`

但本地生活用户问题天然是组合型的。例如：

```text
推荐一家适合约会、现在营业、最好有券的火锅店。
```

这个问题至少包含：

- 场景适配：适合约会
- 地点约束：附近或指定商圈
- 品类约束：火锅
- 营业状态：现在营业
- 优惠约束：最好有券
- 推荐理由：为什么推荐

如果只用一个 `required_action=rag_plus_tool` 表示，就会把“用户到底需要哪些方面”隐藏起来。后续 RAG、toolcall、compose 都只能猜测应该补哪些证据。

### 2.3 `rag_plus_tool` 是脆弱串联，不是真正任务计划

当前 `rag_plus_tool` 不是一个完整 `TaskPlan`，而是一个特殊 action，然后靠条件边串联：

- `route_after_understand` 中先进入 `rag_subgraph`
- `route_after_rag` 中只有当 action 仍然是 `rag_plus_tool` 且 `can_enter_tool` 允许时，才继续进入 `tool_subgraph`

对应代码位置：

- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:337`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:349`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:355`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:358`

问题在于：

- `ensure_retrieval_plan` 构造不出 retrieval plan 时，会把 `required_action` 改成 `clarify`。
- `ensure_tool_plan` 构造不出 tool plan 时，也会把 `required_action` 改成 `clarify`。
- 这使得多能力任务不是“按步骤执行”，而是“任一步计划失败就可能退回泛澄清”。

对应代码位置：

- `learning-agent-service/src/learning_agent_service/application/routing.py:1101`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1118`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1122`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1153`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1166`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1167`

这在工程上比较安全，但用户体验会变成：

- 问题明明是“推荐 + 券 + 环境 + 营业状态”的自然组合，系统只做了一半。
- 某个 plan 构造失败后，用户只看到“请补充更多信息”，但不知道缺的是城市、店名、时间、套餐，还是工具槽位。

### 2.4 RAG 证据门控必要，但输出策略需要从硬拒答改为分级响应

当前 `build_evidence_quality` 会检查：

- evidence 数量
- top score
- score gap
- stale evidence
- shop / geo / category 一致性
- required role 覆盖
- coupon / package / pitfall 等场景需要的证据类型

对应代码位置：

- `learning-agent-service/src/learning_agent_service/application/routing.py:898`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1012`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1016`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1020`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1036`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1040`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1053`

这些门控本身是必要的，否则容易产生无依据回答或跨实体拼接。但当前问题是：门控结果会比较快地落到 `no_answer` 或 `weak_answer`，而回答层又倾向输出模板化拒答。

对应代码位置：

- `learning-agent-service/src/learning_agent_service/tools/service.py:884`
- `learning-agent-service/src/learning_agent_service/tools/service.py:915`
- `learning-agent-service/src/learning_agent_service/tools/service.py:920`
- `learning-agent-service/src/learning_agent_service/tools/service.py:1258`

需要修正的不是“降低证据要求”，而是把输出策略从“硬拒答”改成“分级响应”：

- 有强证据但 facet 不全时，允许 `partial_grounded`
- 有部分证据时，先给边界明确的有用回答
- 不确定的部分必须说明，不能编
- 完全没有证据或关键实体无法确定时，再 `ask_clarification` 或 `no_answer`

### 2.5 `compose_answer` 缺少 AnswerContract，容易先兜底再回答

当前 `compose()` 的大致顺序是：

1. `allow_direct_response` 时直接回复或澄清
2. 尝试 `rag_plus_tool`
3. 尝试单独 tool
4. 处理 `no_answer`
5. 处理 `weak_answer`
6. 再尝试 LLM grounded / open answer

对应代码位置：

- `learning-agent-service/src/learning_agent_service/tools/service.py:884`
- `learning-agent-service/src/learning_agent_service/tools/service.py:897`
- `learning-agent-service/src/learning_agent_service/tools/service.py:902`
- `learning-agent-service/src/learning_agent_service/tools/service.py:915`
- `learning-agent-service/src/learning_agent_service/tools/service.py:920`

问题不在于兜底本身，而在于 compose 层没有先拿到一个明确的 `AnswerContract`：

- 用户问了什么？
- 必须回答哪些 `required_facets`？
- 每个 facet 需要什么证据或工具结果？
- 哪些 facet 可以 partial？
- 哪些内容不能无证据生成？

没有这个契约时，compose 很容易变成“根据当前结果类型套模板”，而不是“检查是否回答了原问题”。

### 2.6 memory 应参与路由复核，但必须避免污染当前 query

当前 memory 机制已经包含 `current_topic / recent_entities / history_summary / memory_injection_plan / promotion` 等能力，文档和代码分层也比较细。

对应位置：

- `memory_mechanism.md`
- `learning-agent-service/src/learning_agent_service/memory/orchestrator.py`
- `learning-agent-service/src/learning_agent_service/memory/retrieval.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:399`

但在当前体验里，memory 更多是：

- 前置上下文补充
- 检索增强
- 写回沉淀

而不是一个稳定参与“本轮 query 是否被正确理解”的复核机制。

需要修正原来的表达：memory 不应无条件成为“中心决策的一等公民”。更稳妥的目标是：

- memory 参与 route review，帮助解决“它 / 这家 / 那个套餐”等上下文指代。
- memory 注入必须经过 `MemoryRelevanceGate`。
- 当前 query 的显式约束优先于历史记忆。
- 当新 query 与旧 memory 主题冲突时，宁可降低 memory 权重，也不能把用户带回旧话题。

### 2.7 双 runner 并存是维护风险，但不是第一阶段止血目标

当前有两套执行路径：

- `LangGraphWorkflowRunner`
- `SequentialWorkflowRunner`

对应代码位置：

- `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:61`
- `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:114`
- `learning-agent-service/src/learning_agent_service/application/workflow/runner.py:47`

这确实会带来：

- 行为不一致风险
- 修 LangGraph 漏掉 Sequential 的风险
- trace 对比和问题定位成本上升

但 runner 收敛不应作为 P0。第一阶段更应该减少答非所问和频繁拒答。runner 是否合并，应等 P0/P1 的 trace 和回归测试补齐后再决策。

## 3. 答非所问的根因链路

根因不是单点 bug，而是下面这条链路叠加：

1. 用户需求没有先稳定解析成 `UserNeed / RequiredFacets`
2. initial routing 过早给出 `required_action`
3. terminal action 让 `understand_turn / RAG / toolcall` 失去复核机会
4. 多能力任务被压进单个 `rag_plus_tool`
5. RAG plan 或 tool plan 构造失败时退化成泛澄清
6. evidence quality 只有较粗的 `grounded / weak_answer / no_answer`
7. compose 层缺少 `AnswerContract / AnswerVerifier`
8. memory 可能补不上上下文，也可能污染新 query

所以用户感受到的不是“系统很谨慎”，而是：

- 我问的是 A，它回答了 B
- 明明有部分相关信息，却说信息不足
- 明明只缺一个槽位，却让我“补充更多信息”
- 明明是组合任务，却只查了其中一部分
- 明明换了新问题，却还沿着旧上下文回答

特别容易出问题的场景：

- 口语化追问：`这个呢 / 那家呢 / 它现在有券吗`
- 多约束推荐：`附近 / 适合约会 / 现在营业 / 有券 / 火锅`
- 只差一个 slot：`这个套餐今天还能用吗`
- 证据不完整但可部分回答：`这家店适合带父母吗`
- 需要防跨实体拼接：A 店评价、B 店优惠、C 店营业状态被合成同一家店

## 4. 问题清单与影响面

| 问题 | 直接影响 | 后续应对 |
| --- | --- | --- |
| routing 过早收口 | 本该 RAG/tool 的请求被 direct/clarify/reject 短路 | P0 增加 route_review |
| 缺少 RequiredFacets | 系统不知道用户到底问了哪些方面 | P0 增加 UserNeed / RequiredFacets |
| `rag_plus_tool` 串联脆弱 | RAG 或 tool 任一步失败就泛澄清 | P0 增加失败原因 trace，P1 引入 TaskPlan |
| RAG 输出模式过硬 | 有部分证据也容易拒答 | P0 改成分级响应 |
| compose 缺少 AnswerContract | 容易套模板，不能验证是否回答原问题 | P2 增加 AnswerContract / AnswerVerifier |
| memory 无相关性门控 | 可能补不上指代，也可能污染新问题 | P0/P1 增加 MemoryRelevanceGate |
| 双 runner 并存 | 行为差异和维护成本上升 | P2 基于 trace 决定是否收敛 |

## 5. 诊断结论

当前系统不是“没有能力”，而是能力之间缺少强约束链路：

- routing 过早决定执行路径
- RAG / toolcall 组合靠脆弱串联
- evidence gate 必要，但输出策略过于硬
- compose_answer 缺少 AnswerContract / AnswerVerifier
- memory 能补上下文，但也需要相关性门控
- runner 双轨是维护风险，但不是第一阶段最该改的问题

因此，后续改造不应第一版就合并 runner、重写全部 RAG、重写全部 memory。更稳妥的路线见：[改进实施文档](architecture_improvement_plan.md)。
