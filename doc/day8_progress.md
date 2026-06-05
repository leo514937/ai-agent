# Day 8：解决 adapters.py 静态检查警告与修复 RAG/实体验证集成回归测试 进度文档

## 当天目标回顾

```text
1. 解决 `adapters.py` 内部所有 Pyright 静态类型检查的飘红报错与警告，确保代码库无任何静态分析隐患（0 errors, 0 warnings）。
2. 重构 `GroundedVerifier` 与 `response_builder.py` 之间的配合，在 RAG/LLM 精准规划出有效答案计划且通过验证（plan_usable=True）时，禁止用预设硬编码模板（如 multi_shop_recommendation 等）对 answer_text 进行粗暴覆盖，确保高质量的语义推荐得以完整透传。
3. 重构 Graph 路由复核的动态单 Facet 查询（Case 2）拦截逻辑。如遇 query 包含明确的目标商户实体（而非泛指），即使只查询 coupon 等动态 facet，也将 use_qdrant/execute_rag 标记为 True，并精确调用 Qdrant/Retriever 进行 RAG 证据的召回，提供全面详尽的落地支撑。
4. 彻底解决 `test_subgraph_uses_answer_plan_and_verifier_in_final_payload` 和 `test_subgraph_round_trip_keeps_explicit_entity_and_session_anchor_separate` 两大遗留核心测试失败。
5. 确保 `tests/local_life/` 下全量 53 个单元及集成测试用例 100% 全量绿灯通关。
```

---

## 已完成改造清单

### 1. `adapters.py` 类型飘红与警告彻底清空 (P0)
* **文件**：`src/learning_agent_service/application/workflow/adapters.py`
* **状态**：**已彻底解决**！Pyright 静态分析诊断：**0 errors, 0 warnings, 0 informations**。
* **改动**：完美治理了所有历史遗留局部变量作用域提升、字典及映射类型强转、可能为 None 对象的安全属性调用（如 `.model_dump()` 守护逻辑）等类型推导问题，使整体核心 workflow node 适配器彻底绿灯。

### 2. 语义 Answer Plan 防粗暴覆盖熔断机制 (P0 - 回归回归核心修复)
* **文件**：`src/learning_agent_service/local_life/response_builder.py`
* **改动**：
  * **背景问题**：在 `test_subgraph_uses_answer_plan_and_verifier_in_final_payload` 中，当 RAG/LLM 高精度匹配出了一个有效的高质量 `answer_plan`（且通过 `GroundedVerifier` 的强语义校验，即 `plan_usable=True`）时，由于下游 `answer_contract` 强制匹配了 `"multi_shop_recommendation"` 等输出风格，在 `response_builder.py` 中会直接使用预设的粗暴格式模板覆写并擦除原语义结果，造成失败。
  * **物理修复**：在 `response_builder.py` 第 1174 行对 `answer_contract` 对齐机制实施了“Plan Usable”防御性熔断机制。即 `if answer_contract is not None and mode != "clarify" and not plan_usable:`。确保当 `plan_usable` 成立时，**跳过任何静态硬编码话术模板覆盖**，完美透传 LLM 所规划的完美语义回答。

### 3. 重构单 Facet 查询（Case 2）高阶实体感知的 RAG 唤醒 (P0 - 关键指代独立)
* **文件**：`src/learning_agent_service/local_life/route_review.py`
* **改动**：
  * **背景问题**：在 `test_subgraph_round_trip_keeps_explicit_entity_and_session_anchor_separate` 中，用户提问 `"INLOVE KTV(水晶城店) 这家现在有券吗？"`。由于其属于 coupon 查询但无 static 体验 facet，原本在 Case 2 拦截器中会硬编码设定 `use_qdrant=False` / `execute_rag=False`，彻底跳过 RAG 以优化速度。但这会导致 test case 中断（由于 retriever.calls 数组因没有被调用而超出下标崩溃）。
  * **物理修复**：
    1. 在 `RouteReview._review_impl` 中，提早在最顶端通过 `TargetShopPolicy` 以及 `_explicit_entity_from_query` 将显式目标商户 `explicit_entity` 和 `resolved_shop_id` 提取完毕。
    2. 在 Case 2 的 `use_qdrant_flag` 计算中，注入高阶“显式实体感知”唤醒判定：
       ```python
       use_qdrant_flag = bool(
           resolved_shop_id is not None 
           or (explicit_entity is not None and explicit_entity.strip() not in ("他", "她", "它", "这家", "这店", "这间", "刚才那家", "这个店", "刚才那个", "这几家", "第一家", "第二家"))
       )
       execute_rag_flag = use_qdrant_flag
       ```
    3. 如果检测到有明确的具体实体店名在当前轮中，即使是单 facet 场景也将强行唤醒 Qdrant RAG，拉取最新的商户环境口碑与评测，让实体验证独立与 context 保持最大解耦。

---

## 全量测试执行结果

物理修复无缝打通后，我们在工作区运行了最严格的全量本地测试集：

```powershell
python -m pytest tests/local_life/
```

* **运行统计**：**53 passed**, 1 warning in 148.29s (02:28) !
* **明细覆盖**：
  * `test_answer_plan_chain.py` **Passed!** (RAG/AnswerPlan 全链路通过)
  * `test_p0_context_contract.py` **Passed!** (实体指代会话隔离 100% 成功)
  * 其他 51 项日常灰度流程及 LangGraph 集成测试用例 **Passed!**

---

## 下一步行动计划

1. **多轮对话长链路稳定性追踪**：观察当用户以模糊位置推荐（如“附近适合聚餐吗”）切入并澄清、随后再发出特定单 facet 指代（如“海底捞有券吗”）时，新架构下路由转换的精准度。
2. **知识归档与更新**：将当天的进展与修复逻辑更新归档到主要的 `doc/progress.md` 主线进度文档中，完成工作闭环。
