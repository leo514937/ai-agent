# 本地生活 Intent 成功标准定义

> 版本: 1.0
> 更新日期: 2026-06-11

---

## 概述

本文档定义了本地生活服务中每个 Intent 的成功标准，用于指导开发、测试和评估。

---

## Intent 成功标准

### 1. merchant_detail (商家详情)

**触发条件**: 用户询问某家店的具体信息（如"海底捞怎么样"、"这家店好吃吗"）

**成功标准**:
- ✅ 必须命中目标店（不能串店）
- ✅ 必须围绕用户关心点输出（环境/口味/服务等）
- ✅ 禁止推荐其他店
- ✅ 不能输出用户未询问的维度

**失败模式**:
- `cross_shop`: 输出了其他店的信息
- `wrong_entity`: 命中了错误的店
- `forbidden_facet_violated`: 输出了禁止的维度

**评估指标**:
- 串店率 < 5%
- 错店率 < 3%

---

### 2. coupon_query (优惠券查询)

**触发条件**: 用户询问优惠券/团购信息（如"有券吗"、"有什么优惠"）

**成功标准**:
- ✅ 必须调用 `get_coupon_list` 工具
- ✅ 必须说明券是否可用
- ✅ 不能答环境/口味/服务
- ✅ 不能推荐其他店

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称有券
- `forbidden_facet_violated`: 输出了环境/口味/服务

**评估指标**:
- 工具调用命中率 > 95%
- 禁止维度泄露率 < 2%

---

### 3. open_status (营业状态)

**触发条件**: 用户询问是否营业（如"还在开门吗"、"几点关门"）

**成功标准**:
- ✅ 必须调用 `check_open_status` 工具
- ✅ 必须给出当前营业判断
- ✅ 无法确认时要说明不确定
- ✅ 不能猜测营业状态

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称营业状态
- `realtime_error`: 工具调用失败但未降级

**评估指标**:
- 工具调用命中率 > 95%
- 实时信息错误率 < 3%

---

### 4. nearby_recommendation (附近推荐)

**触发条件**: 用户请求推荐附近商家（如"附近有什么好吃的"、"推荐几家火锅店"）

**成功标准**:
- ✅ 必须绑定位置信息
- ✅ 必须能解释推荐理由
- ✅ 不能随机推荐
- ✅ 位置缺失时必须追问

**失败模式**:
- `location_missing`: 无位置却直接推荐
- `no_recommendation_reason`: 推荐无理由

**评估指标**:
- 过度追问率 < 10%
- 兜底率 < 5%

---

### 5. comparison (比较选择)

**触发条件**: 用户请求比较两家或多家店（如"A和B哪个好"、"哪家更适合约会"）

**成功标准**:
- ✅ 必须识别比较对象（至少2家）
- ✅ 必须确定比较维度
- ✅ 必须分别检索两家证据
- ✅ 必须按维度组织差异
- ✅ 必须有最终建议

**失败模式**:
- `comparison_no_template`: 无结构化对比模板
- `single_shop_in_comparison`: 只输出一家店

**评估指标**:
- 比较模板使用率 100%
- 最终建议输出率 > 90%

---

### 6. address/distance (地址/距离)

**触发条件**: 用户询问地址或距离（如"在哪"、"有多远"）

**成功标准**:
- ✅ 必须调用 `get_distance_eta` 工具
- ✅ 不能猜测距离
- ✅ 无法获取时要说明

**失败模式**:
- `unsupported_realtime_claim`: 未调用工具但声称距离
- `realtime_error`: 工具调用失败但未降级

**评估指标**:
- 工具调用命中率 > 95%
- 实时信息错误率 < 3%

---

### 7. clarification (澄清追问)

**触发条件**: 用户输入信息不足（如空输入、纯标点、"啊"、"嗯"）

**成功标准**:
- ✅ 必须识别缺失信息
- ✅ 不能直接回答
- ✅ 追问要具体明确
- ✅ 连续追问不超过2次

**失败模式**:
- `over_clarification`: 不该追问时追问
- `clarification_too_vague`: 追问不够具体

**评估指标**:
- 过度追问率 < 10%
- 追问成功率 > 60%

---

### 8. out_of_scope (非本地生活)

**触发条件**: 用户询问非本地生活内容（如"今天天气怎么样"、"帮我写代码"）

**成功标准**:
- ✅ 不能进入 resolve_target_shop
- ✅ 不能进入 RAG/tool
- ✅ 必须给出明确的超出范围提示

**失败模式**:
- `scope_violation`: 进入了本地生活流程

**评估指标**:
- 兜底率 < 5%（对非本地生活查询）

---

## 综合评估指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 串店率 | < 5% | 单店模式下输出了其他店的信息 |
| 错店率 | < 3% | 命中了错误的店 |
| 过度追问率 | < 10% | 不该追问时追问 |
| 兜底率 | < 5% | 无法回答时给出兜底 |
| 工具调用命中率 | > 95% | 需要工具时成功调用 |
| 空召回率 | < 10% | RAG检索无结果 |
| 实时信息错误率 | < 3% | 实时信息与实际不符 |
| 禁止维度泄露率 | < 2% | 输出了禁止的维度 |
| 降级率 | < 15% | 降级回答的比例 |

---

## 失败类型映射

| 问题类型 | 典型失败 | 可能原因 | 归属模块 |
|----------|---------|---------|----------|
| 问券却答环境 | answer包含"环境" | forbidden_facet未生效 | answer_contract + answer_linter |
| 问当前营业却用了历史信息 | 无tool调用 | realtime_facet未触发tool | route_gate + tool_planner |
| 问附近却没追问位置 | 直接回答推荐 | location slot缺失未检测 | user_need_parser + clarification |
| 问比较却只答单店 | 只输出一家店 | comparison无模板 | answer_structure_composer |
| 问单店却答成推荐 | 输出推荐列表 | target_shop解析失败 | target_shop_policy |
| 问A店答B店 | 串店 | cross_shop过滤失败 | evidence_scope_guard |
| 无证据硬答 | 编造信息 | evidence不足未检测 | grounded_verifier |
| RAG召回不相关 | 证据不匹配 | 检索质量差 | query_router + rag |
| 工具结果被忽略 | 有tool结果但未使用 | compose_answer忽略 | compose_answer |
| 上下文错误继承 | 继承了错误的current_shop | 代词消解失败 | target_shop_policy |

---

## 附录: 相关代码文件

| 模块 | 文件路径 |
|------|---------|
| Intent路由 | `top_level_intent_router.py` |
| 目标店解析 | `target_shop_policy.py` |
| 答案契约 | `answer_contract.py` |
| 答案结构 | `answer_structure_composer.py` |
| RAG护栏 | `rag_guardrail.py` |
| 工具执行 | `tool_executor` |
| 业务指标 | `business_metrics.py` |
| 冲突解决 | `realtime_conflict_resolver.py` |
