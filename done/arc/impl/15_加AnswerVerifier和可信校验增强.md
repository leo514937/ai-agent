# 9. 加 AnswerVerifier 和可信校验增强 (已与代码同步)

## 目标
在 Step 04 的基础校验之上，建设拆解级别的 Claims 校验防线和 LLM as Judge 大模型验厂防线，辅以设限的自修复重试，防范店铺幻觉、未知信息编造与排序错位。

## 当前实现机制与代码结构

### 1. 结构化 Claim 拆解与拦截 (B2MiniVerifier)
- **位置**: [b2_mini_verifier.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py)
- **校验细节**:
  - **店铺幻觉拦截 (hallucinated_shop_name)**: 扫描生成的文本，禁止出现 `DecisionPlan` (即 `selected_targets` 与 `omitted_targets`) 允许范围以外的任何其他已知店铺名称，防止模型无中生有。
  - **未知信息防说谎拦截 (unknown_as_false)**: 当优惠券 (coupon) 或营业状态 (open_status) 信息在 `DecisionPlan` 或者是 selected targets 中为 `unknown` 时，严禁大模型以绝对否定的语气表述为 “没有券”、“已打烊” 等，必须表述为 “暂时无法确认” 或 “暂时没查到”。
  - **虚假属性数据拦截**: 严禁模型在自然语言回复中编造 `DecisionPlan` 事实点中未提及的距离 (`unsupported_distance`)、人均价格 (`unsupported_price`)、商户评分 (`unsupported_rating`) 以及优惠券存在性 (`unsupported_coupon`)。
  - **推荐/对比排序防篡改 (ranking_changed)**: 严格对比大模型回复中商户出现的先后顺序，与 `DecisionPlan` 中的 `overall_ranking` 顺序保持一致，拦截大模型为了文本流畅度或迎合喜好而篡改系统排行推荐的行为。
  - **免责/遗漏申明拦截 (omitted_targets_violation/forbidden_claim_violation)**: 当存在省略/未列入对比的目标店面 (`omitted_targets` 不为空) 时，拦截大模型含有 “对比了所有”、“对比了全部” 的字样，防止虚假夸大；同时拦截 `forbidden_claims` 中的禁止话术。

### 2. 基础启发式 AnswerVerifier 校验防线 (verifier.py)
- **位置**: [verifier.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/verifier.py)
- **校验细节**:
  - 检测大模型推荐回复中是否完整体现了 Top 3 推荐商户 (`recommendation_top_k_mismatch`)。
  - 启发式校验规则：对未查到优惠券、距离、营业时间时的回复话术进行正则与字符串匹配，校验是否提示了“暂时无法确认”等不确定性表达。
  - 拦截错店/串店 (`shop_mismatch`)，限制大模型只能提及 evidence items 或 unknown items 中的店铺。
  - 拦截未在 comparison matrix 中出现的维度胜出声称。

### 3. 安全熔断与自修复重试机制
- **重试上限限制**: 在 [config.py](file:///d:/javacode/hm-dianping/local_life_agent/config.py) 中定义了最大重试次数 `MAX_REWRITE_ATTEMPTS = 2`。在 [graph_builder.py](file:///d:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py) 中，`_GRAPH_REWRITE_LIMIT = 1` 控制重试次数。
- **状态流转**: 
  - 当 `answer_verify` 节点计算校验结果，若未通过则将状态置为 `rewrite_needed`，并流转至 `rewrite` 节点。
  - `rewrite` 处理器使 `rewrite_count` 递增。
  - 若 `rewrite_count < _GRAPH_REWRITE_LIMIT`，状态机回到 `answer_generate` 进行重新生成；若超过重试上限，则直接流转至 `fallback_answer`。
- **降级硬模板回执**: 
  - [generator.py](file:///d:/javacode/hm-dianping/local_life_agent/answer/generator.py) 中定义了兜底的模板回复逻辑，并在 [graph_builder.py](file:///d:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py) 的 `_h_fallback_answer` 中进行接入。例如当状态异常时，返回："优惠券服务暂时不可用，请稍后再试。" 或 "获取优惠券信息失败，建议稍后再试。" 等，确保系统绝不无限循环或卡死。

### 4. 测试验证与 DoD
- **自动化测试文件**: 
  - [test_answer_verifier.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_answer_verifier.py): 验证了 `verify_answer` 的契约（排序篡改拦截、禁止话术拦截、必选属性缺失拦截、unknown 误报为 empty 拦截）。
  - [test_llm_verbalizer.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_llm_verbalizer.py): 验证 `verbalize_decision_plan` 中 verbalizer disabled/success 行为，以及违规（串店、禁止申明、省略目标改变等）导致 fallback 的行为。
  - [test_llm_verbalizer_graph.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_llm_verbalizer_graph.py): 验证在 LangGraph 的端到端运行流程中，Verbalizer 产生违规时可以正确记录 `violation` 指标，并安全降级到 template 文本。
