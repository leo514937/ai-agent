# 9. 加 AnswerVerifier 和可信校验增强

## 目标
在 Step 04 的基础校验之上，建设拆解级别的 Claims 校验防线和 LLM as Judge 大模型验厂防线，辅以设限的自修复重试。

## 实现细节要求

### 1. 结构化 Claim 拆解与拦截
- 将 AnswerGenerator 的长段回复文本借助抽取工具切片为 `claims`。
- 交叉校验 `EvidencePack`。重点打击 `shop_id_mismatch`（张冠李戴，如把A的评分写给B）和 `unknown_as_false`（如将“未查到”写为“没有”）。

### 2. 大模型验收 (LLM as Judge)
- 检测 `intent_drift` (答非所问)。
- 检测 `ranking_changed_by_llm`（大模型为了迎合或文本渲染，强行改变了系统预设排行的第一名）。

### 3. 设置最高重试上限 (max_rewrite_attempts)
- 引入 `max_rewrite_attempts = 2` 的机制。
- 当 `AnswerVerifier` 抛出 `Rewrite` 异常两次后，若依然不合规，**不要无限循环卡死请求**。
- 直接触发保底模版降级回答，例如：“我查到的信息如下：……（直接列出结构化数据）。其中 XX 暂时无法确认。”

## 本阶段完成标准 (Definition of Done)
1. 建立 Claims 抽取逻辑，实现 `shop_id` 级别的精确挂钩比对验证。
2. 成功加入安全熔断机制，在 LLM 反复生成不合规答案触及 `max_rewrite_attempts` 后，顺利触发降级硬模板回执。
3. **完成测试**：`tests/test_answer_verifier.py` 编写并 Pass。制造 LLM as Judge 识别出 ranking_changed_by_llm 的场景，并验证重试及降级逻辑准确执行无抛错。

## 阶段完成后的收尾

- 跑幻觉拦截测试。
- 重点看 `unknown_as_false / ranking_changed_by_llm / shop_id_mismatch` 是否能被拦住。
- 确认 rewrite 上限生效。
