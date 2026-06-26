# 问小团类本地生活 Agent 规格文档

本目录用于描述“问小团”类本地生活助手 Agent 的产品目标、统一架构、工具约束、可信回答与端到端验收标准。

重要架构原则：**不要把单店查询、附近推荐、多店对比、多轮追问分别实现成多个独立 workflow。**

正确理解方式是：

- 顶层路由只做粗粒度入口判断：Direct Answer / Safety / Local Life Agent。
- 进入 Local Life Agent 后，所有本地生活 query 都走统一的 Plan → Execute → Review 主循环。
- 单店、推荐、对比、多轮、澄清不是不同 workflow，而是同一个 GoalPlan / CandidateSet / EvidencePlan / ReviewResult 在不同场景下的不同取值。
- 场景覆盖文档用于说明“能力边界和验收用例”，不是要求新增平行路由。

## 文档列表

- `00_项目目标与产品边界.md`：产品目标、能力边界、用户价值。
- `01_场景能力地图与Query覆盖.md`：需要覆盖的 query 类型和场景矩阵；注意这里是能力覆盖，不是 workflow 拆分。
- `02_产品体验与回答策略.md`：最终回答体验、推荐语气、可信表达策略。
- `03_总体架构与LangGraph编排.md`：统一 LangGraph 主链路，明确不是多 workflow。
- `04_Plan_Execute_Review设计.md`：统一 Plan → Execute → Review 机制。
- `05_工具调用与可信数据约束.md`：真实 ToolCall、ToolRegistry、Gateway、禁止 mock。
- `06_多轮上下文与状态管理.md`：SessionState、多轮指代、候选恢复。
- `07_工程实现约束与反模式.md`：禁止规则堆叠、禁止 legacy fallback 变主路径。
- `08_验收标准与测试矩阵.md`：基础验收矩阵。
- `09_端到端验收标准_RealLLM_RealTool.md`：真实 LLM + 真实 ToolCall 的端到端验收。
- `10_统一PlanExecuteReview架构修正版.md`：对“多场景统一 Agent 主循环”的专门说明。
