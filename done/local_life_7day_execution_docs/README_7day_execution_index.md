# 本地生活 Agent 7 天执行文档索引

> 本目录将原始 7 天改造总计划拆分为 7 份每日执行 Markdown。
>
> 划分原则：
>
> - 原计划 Day0 基线测试并入 Day1，因此最终形成 Day1-Day7 共 7 个文档。
> - Day1-Day4：先修业务不变量，确保当前 5 个真实问题全部解决。
> - Day5-Day7：再迁移到 LangGraph StateGraph 控制。
> - 每天都有参考架构、修改优先级、Chat/stream 验收用例和预期结果。

## 文档列表

1. `Day1_baseline_target_shop.md`  
   基线测试 + TargetShopPolicy + 多轮实体覆盖。

2. `Day2_answer_contract_response_builder.md`  
   AnswerContract + ResponseBuilder 强约束。

3. `Day3_facet_tools_coupon.md`  
   FacetExecutionPlan + 多工具执行 + CouponResult 标准化。

4. `Day4_rag_recommendation.md`  
   single_shop_rag + recommendation_rag + 多商铺推荐。

5. `Day5_langgraph_state_nodes.md`  
   LangGraph State / Node 化，不改变业务行为。

6. `Day6_langgraph_edges_chat_gray.md`  
   LangGraph conditional edges + 子图接入 + Chat 灰度切换。

7. `Day7_langgraph_default_cutover.md`  
   默认切换 LangGraph compiled graph + 完整验收。

## 最终完成标准

```text
业务正确：
  不错店、不串上下文、不乱召回、不数错券、不只推荐一家。

架构正确：
  主流程由 LangGraph StateGraph 控制。

测试正确：
  每天都有真实 /api/ai/chat/stream 验收测试和预期结果。
```
