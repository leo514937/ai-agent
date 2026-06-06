# P0-Day1：路由底座与信号层

源文档：[./P0_intent-routing-4-stage-architecture.md](./P0_intent-routing-4-stage-architecture.md)

## 本日目标

- 完成 Hard Guard
- 完成 Signal Policy
- 完成 LLM Semantic Parser
- 完成 Target Resolution

## 改造边界

- 只处理“这轮输入是什么、目标店是谁、需要什么 facet”
- 不进入答案拼装
- 不进入执行节点

## 必须避免的架构冗余

- 不要把规则识别和 LLM 语义理解写成两套互相覆盖的逻辑
- 不要把店名解析散落在多个节点里重复实现
- 不要在这个阶段提前做答案生成或验证

## 完成标准

- 路由候选可以稳定输出
- 指代词与商家名解析有明确来源
- 缺失信息能被识别出来
