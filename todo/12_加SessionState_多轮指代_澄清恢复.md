# 7. 加 SessionState、多轮指代、澄清恢复

## 目标
利用 `InMemorySessionStore` 管理多轮上下文，支持指代消解，处理异常澄清逻辑及其各类边界情况。

## 实现细节要求

### 1. InMemorySessionStore 存储设计
- 采用内存字典暂存 Session，满足 MVP 与本地开发测试需求。
- 接口包含：`load(session_id) -> SessionState`, `save(session_id, state) -> None`, `clear(session_id) -> None`。

### 2. ContextRecovery 与上下文优先级决策表
为防止多店推荐完成后用户询问“这家有券吗”被错误索引，明确状态匹配的绝对优先级：
1. **当前轮显式店名** > 
2. **pending_clarification (若命中)** > 
3. **序号指代 (第一家)** > 
4. **current_shop (“这家/它”)** > 
5. **last_recommendation_list** > 
6. **active_constraints**。

注：若上一轮给出了列表，本轮用户提问“这家”，由于存在多个候选且 `current_shop` 可能为空/陈旧，系统应拦截判定指代不明发起澄清，而绝不默认取列表第一个。

### 3. AMBIGUOUS 澄清与恢复完整版 (解决歧义)
- `resolve_shop` 遭遇 `AMBIGUOUS`，写入 `pending_clarification` 并中断。
- 总控流程首要节点 `check_pending_clarification` 截获用户回应。
- **异常澄清边界处理规范**：
  - **能匹配候选** (回复数字对得上)：恢复原语义帧和任务，清空 pending，继续去执行目标工具。
  - **明显换问题** (如“给我讲个笑话”或“算了”)：清空 pending，走新问题通道处理。
  - **无效选择 / 越界** (比如只给了 2 个候选用户却回复“3”、或者非数字如“我不懂”)：保留 pending，提示用户可选编号不对。
  - **过期** (受限于 config `clarification_ttl_seconds`)：清空 pending，提示重新说明店名。
  - **语义模糊恢复** (用户回复“第二个”或“学院路那个”)：由 ReferenceResolver 或辅助规则判定匹配候选。

## 本阶段完成标准 (Definition of Done)
1. `InMemorySessionStore` 的 API 开发与接入完成，主流程中成功实现了状态 Load/Save。
2. 触发 AMBIGUOUS 后，各种边界条件如超时、越界数字、直接转移话题皆有按约定逻辑安全返回，无程序崩溃。
3. **完成测试**：`tests/test_context_recovery_clarification.py` 编写并 Pass。模拟发起歧义澄清，接着仅输入有效序号“1”，断言系统成功调起上轮挂起的原始工具需求（查券等）。

## 阶段完成后的收尾

- 跑多轮指代和澄清恢复测试。
- 重点检查 `pending_clarification` 优先级、序号回复恢复、换话题清空挂起状态。
