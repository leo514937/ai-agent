# AGENTS.md

## 项目目标

本项目是一个本地生活助手 Agent，目标是全面处理用户围绕商家、优惠券、团购、营业状态、距离、评价、附近推荐、多店对比、多轮追问等本地生活 query。

系统以 LangGraph 作为主编排框架，采用“顶层路由 + Plan → Execute → Review”的设计模式。

核心原则：LLM 负责理解、规划辅助和自然语言表达；ToolCall 负责获取真实事实；Review / Validator / Verifier 负责可信校验。

## 仓库结构

* `local_life_agent/`：Python 本地生活 Agent 主体，包括 LangGraph 编排、语义理解、规划、工具调用、证据构建、回答生成与测试。
* `src/`：Java 后端服务代码，负责业务接口、商家、优惠券、订单等后端能力。
* `frontend/`：前端页面与交互入口。
* `db/`：数据库初始化、迁移或种子数据相关内容。
* `eval/local_life/`：本地生活场景评测、回归用例和端到端验证。
* `scripts/`：启动、导入、验证、调试等脚本。
* `doc/`：设计文档、阶段计划、验收报告和架构说明。
* `todo/`、`done/`、`scratch/`：临时计划、归档记录和实验内容，不应作为主链路事实来源。

## 架构约束

* 必须以 LangGraph 作为主流程控制，不允许绕开主图新增平行执行链路。
* 顶层路由必须区分：Direct Answer、Safety / Reject、Local Life Agent。
* 本地生活任务必须走 Plan → Execute → Review → Answer 的主路径。
* Plan 只产出结构化 ToolPlan / DecisionPlan，不直接编造答案。
* Execute 只能执行经过 Validator 通过的工具计划。
* Review 必须判断信息是否足够，不足时进入澄清、补工具、重规划或可信失败。
* 最终回答必须基于 EvidencePack / ToolResult，不允许脱离证据自由发挥。

## 工具调用约束

* 所有工具必须通过 ToolRegistry 注册。
* 所有工具调用必须经过 ToolCallGateway。
* 工具输入输出必须有明确 schema / DTO。
* 工具失败、空结果、超时、参数错误必须显式返回，不得伪装成功。
* 不允许 LLM 直接调用未注册工具。
* 不允许绕过 Gateway 直接读取数据库、静态文件或临时数据。
* 不允许工具层决定最终自然语言回答。

## 禁止 Mock

* 正常运行链路禁止使用 mock 数据、mock 工具、静态商家列表、静态券列表。
* 禁止用 hardcoded 店名、关键词 if/else、模板兜底来修业务 bug。
* 禁止工具查不到时编造商家、优惠券、评分、距离、营业状态或团购。
* 测试可以使用 fake / stub，但必须只存在于测试目录或测试配置中，并显式标记。

## 本地生活能力要求

系统应覆盖：单店查询、优惠券查询、营业状态、距离 ETA、评价摘要、附近推荐、条件筛选、场景化推荐、多店对比、多轮指代、候选澄清。

多候选商家不能默认选第一家；指代不清必须澄清；对比对象过多必须裁剪或追问；推荐结果不足必须说明原因。

回答可以自然、有推荐感，但所有事实必须来自工具结果。没有证据时只能表达不确定，不能补充不存在的信息。

## 开发要求

修改代码前先理解现有链路，不要重复造路由、重复造 planner、重复造 fallback。

优先修协议、状态、schema、validator、review 和 evidence，而不是堆规则。

每次改动后至少运行相关单测；涉及主链路时运行本地生活端到端回归。

推荐命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests -q
```
