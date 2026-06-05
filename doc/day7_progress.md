# Day 7：物理修复缺失位置模糊附近推荐（Case 5 槽位澄清拦截）与 TargetShopPolicy 误识别、RAG 空包熔断缺陷 进度文档

## 当天目标回顾

```text
1. 修复无位置上下文时的模糊附近推荐（如“附近有没有推荐的餐厅？”）未保留槽位澄清，而是误进入 RAG 检索返回空数据产生 fallback 牛头不对马嘴回复的缺陷。
2. 修复 `TargetShopPolicy` 剥离后缀后没有过滤泛指词，把整个 raw_query 误识别成特定商家 shop_name，从而导致 RAG 检索空召回的缺陷。
3. 解决 LangGraph 节点决策器 `route_decider` 中由于 recommendation_mode 判断优先级过高，导致即使没有位置需要澄清，也强行进入 recommendation_subgraph 而产生 fallback 的端到端缺陷。
4. 物理修复在位置澄清卡片中输入位置（如“北京”）流程恢复到推荐主线后，由于无匹配商户数据导致 RAG 空召回并错误抛出 `RAG_REFUSED_SHIELD` 熔断崩溃的缺陷。
5. 确保 `tests/local_life/test_p0_routing_review.py` 中 12 个测试用例 100% 完美绿灯通过。
6. 确保 LangGraph 日常 integrated 灰度测试 `tests/local_life/test_day6_langgraph_chat_stream.py` 和 Day 7 集成测试 `tests/local_life/test_day7_langgraph_default_chat.py` 100% 回归通过。
```

---

## 已完成改造清单

### 1. 物理修复 Case 5 槽位澄清缺陷与路由对齐 (P0)
* **文件**：`src/learning_agent_service/local_life/route_review.py`
* **改动**：
  * 在 `RouteReview._review_impl` 中，完美修复了 Case 5 分支。原逻辑硬编码将 `need_clarification` 改写为 `False` 并强制路由到空 RAG。
  * 纠正为真实的 `need_clarification=True`，对齐其路由为 `clarify`（检索策略为 `clarification_only`），拦截了后续无效的 RAG 和工具调用。
  * 规范设定了卡片提示问句 `“你现在在哪个城市或位置附近？”` 以及 SuggestedReply 选项，以支持位置选择卡片的物理渲染。

### 2. 重构 TargetShopPolicy 泛指词识别逻辑与防御性过滤 (P0)
* **文件**：`src/learning_agent_service/local_life/target_shop_policy.py`
* **改动**：
  * 扩展了 `_GENERIC_ENTITY_TOKENS` 词表，全面覆盖了品类词（`"火锅"`, `"火锅店"`, `"烤肉"`, `"烤肉店"`, `"饭店"`, `"小吃"`, `"约会"`, `"营业"` 等）以及体验偏好词（`"适合约会"`, `"情侣约会"`, `"现在营业"`, `"最好有券"`, `"适合带娃"`, `"带娃"`, `"不踩雷"` 等）。
  * 在 `_looks_like_generic_query_entity` 中扩展了 stop-words 列表（增加 `"适合"`, `"最好"`, `"现在"`, `"吗"`, `"？"`, `"?"` 等），使得类似 `"附近有没有适合约会、现在营业、最好有券的火锅？"` 这种模糊附近推荐查询能被完美、精准地识别为**泛指模糊查询**，使得 `TargetShopPolicy` 能够返回 `shop_name=None`，不再误识别绑定虚假的店铺名。
  * 移除了 `target_shop_policy.py` 中未使用到的 `List` 与 `Optional` 导入以彻底消除 IDE 飘红警告。

### 3. 重构 LangGraph 条件边决策器 `route_decider` 优先级 (P0 - 关键缺陷)
* **文件**：`src/learning_agent_service/application/workflow/subgraphs.py`
* **改动**：
  * **根因分析**：由于 `route_decider` 节点中 `recommendation_mode` 的判断顺序位于最前（高优先级），当用户发起 `"附近有没有推荐的餐厅？"`（无位置信息）时，虽然 `load_context` 中的 `adapters` 已经正确算出了 `effective_action = "clarify"`，但决策器依然因符合 `recommendation_mode` 强行路由至了 `"recommendation"` 子图分支，导致本该触发澄清卡片的流程跑向了空检索 fallback。
  * **修复方案**：调整分支排序。将 `if effective_action == "clarify": return "clarify"` 的校验提升到 `if recommendation_mode` 之前，使得缺失位置时的“槽位澄清”动作能以最高优优先判定并精确进入 `clarify` 分支，拦截空检索。

### 4. 修复位置澄清继承恢复后空 RAG 熔断 `RAG_REFUSED_SHIELD` 崩溃 (P0 - 端到端最简拦截)
* **文件**：`src/learning_agent_service/application/workflow/subgraphs.py`, `src/learning_agent_service/tools/service.py`
* **改动**：
  * **根因分析**：在 `_ensure_rag_result` 逻辑中，由于空 Qdrant 召回并不返回 None 而是返回包含空列表 `items` 的 `EvidencePack`。导致 `status` 被误标识为 `RagStatus.OK`。接着，在 `AnswerComposer.compose` 走向落地回答分支时，由于 `items` 实际为空且无真实依据，熔断保护器抛出了 `RAG_REFUSED_SHIELD` 崩溃。同时在 `_compose_partial_grounded_answer` 中会被包裹多余的部分判断语。
  * **物理修复**：
    1. 在 `subgraphs.py` 中，重构了 `_ensure_rag_result` 的状态判定逻辑。若 `items` 列表为空，将其状态准确评估为 `RagStatus.EMPTY`，彻底打通空召回的推导链路。
    2. 在 `service.py` 中，重构了 `_grounded_fallback` 兜底引擎。当 `items` 列表为空时，不再抛出系统熔断异常，而是极其优雅地重定向至 `self._compose_no_answer(request, request.evidence_quality)`，自动输出最温柔、最友好的 `RAG_NO_ANSWER` 未找到商户的话术提示。
    3. 在 `service.py` 中，优化了部分落地回答逻辑。当捕获到 `RAG_NO_ANSWER` 的降级空提示时，直接透传，跳过冗余的 `"部分判断"` 包装引导，从而实现极致流畅的端到端体验。

### 5. 精细化 Coupon 澄清拦截策略 (P1)
* **文件**：`src/learning_agent_service/local_life/route_review.py`
* **改动**：
  * 引入了 `is_generic_search` 判断，将含有品类、场景或者包含 `["附近", "推荐", "找个", "搜", "查附近", "有什么"]` 关键字的查询定义为泛指搜索推荐。
  * 避免了由于 target_shop.shop_name 为 None 导致模糊推荐搜索被 coupon clarification 无商家拦截器（Case 1）错误拦截的缺陷，实现了精确的澄清与检索解耦。

### 6. 移除临时调试输出 (Clean Code)
* **文件**：`src/learning_agent_service/local_life/route_review.py`
* **改动**：
  * 彻底清除了开发与数据抓取期间临时插入的高频 `[DEBUG _review_impl]` 与 `[DEBUG RouteReview]` 终端打印日志，确保代码生产级极简优雅。

### 7. 拦截并清除 'assistant' 等系统特殊角色字符对 slots 的污染与 TargetShopPolicy 误识别 (P0)
* **文件**：`src/learning_agent_service/application/dependencies.py`, `src/learning_agent_service/local_life/target_shop_policy.py`
* **改动**：
  * **背景原因**：当页面处于助手状态端时，前端传入的 `topic_hint` 为 `"assistant"`。由于 `dependencies.py` 内部 `_looks_like_local_life_context(command)` 判断成立，使得系统误将 `"assistant"` 作为具体商铺 `shop_name` 强行写入 `slots`，最终向下游传递并发送出脏 HTTP 请求 `GET /shop/of/name?name=assistant&current=1`。
  * **物理修复 1 (中枢依赖过滤)**：在 `dependencies.py` 的 `_enrich_local_life_slots` 中，添加对 `command.topic_hint` 合法性的严格过滤：仅在 `topic_hint` 不属于系统保留特殊角色字样（`"assistant"`, `"ai"`, `"general"`, `"none"`, `""`）时才允许向 `shop_name` 进行 `setdefault` 填充，从根源上截断脏槽位输入。
  * **物理修复 2 (策略器防御性置空)**：在 `target_shop_policy.py` 的 `resolve_target` Precedence 1 中，对提取的 `eff_explicit_name` 进行双重防御校验，如果属于上述保留系统词汇，则强制重置为 `None`。
  * **类型红线修复 (Clean Type Hinting)**：将 `target_shop_policy.py` 中 `_normalize_alias` 的入参类型注解优化为更宽容的 `str | None`，完美消除了 Pylance/IDE 在 140 行推导 `cand_name` 空值可能时抛出的类型警告红线，保证了代码整体在类型静态检查时的 100% 绿灯。

---

## 测试执行结果

在全新物理修复部署后，本地自动化测试套件运行结果如下：

### 1. 路由复核 P0 专属测试集
```powershell
python -m unittest tests/local_life/test_p0_routing_review.py
# 或使用 pytest
pytest tests/local_life/test_p0_routing_review.py
```
* **运行结果**：**12 passed** 100% 全量绿灯通关！

### 2. LangGraph 灰度流程集成测试集
```powershell
pytest tests/local_life/test_day6_langgraph_chat_stream.py
```
* **运行结果**：**3 passed** 100% 完美通过！

### 3. Day 7 LangGraph 默认推荐集成测试集
```powershell
pytest tests/local_life/test_day7_langgraph_default_chat.py
```
* **运行结果**：**2 passed** 100% 完美通过！

### 4. 合并全量回归测试集
```powershell
pytest tests/local_life/test_p0_routing_review.py tests/local_life/test_day6_langgraph_chat_stream.py tests/local_life/test_day7_langgraph_default_chat.py
```
* **运行结果**：**17 passed** 100% 完美绿灯通过！

---

## 下一步行动计划

1. **全面回归灰度与线上链路验证**：将 Compiled Graph 部署到灰度中，观察实际用户查询在多轮对话下卡片弹出与位置继承的体验。
2. **端到端体验监控**：持续监控 RAG 数据质量，确保对各种未知/无匹配位置均能稳健吐出最温柔的 `RAG_NO_ANSWER` 优雅兜底文案。
