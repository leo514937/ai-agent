# 5. 扩展单店多 facet：券 + 营业 + 距离

## 目标
处理用户针对同一家店抛出多个属性查询的需求（如“这家有券吗，顺便看现在营业吗，远不远？”）。在 Planner 层将 Facets 展开并利用 BatchToolExecutor 并行执行。

## 实现细节要求

### 1. 多 Facet 语义识别与提取
- `SemanticFrame.facets` 数组内各维度需携带 `required` 属性：主动问（“营业吗”）-> true；顺带提（“最好有券”）-> false。

### 2. 工具规划与并行执行
- 映射 `coupon`, `open_status`, `distance` 等 facet 至具体工具调用。
- 生成 `parallel` 模式的 `ExecutionPlan`，交给 Gateway 内部的 `BatchToolExecutor` 进行并行异步处理，共享同一个 `shop_id`。

### 3. 容错处理与 AnswerVerifier 校验
- Optional 工具超时不报错，记录为 `unknown`；Required 工具报错按约定上报错误。
- 基础 AnswerVerifier 追加检查：回答中必须涵盖所有用户要求的必答 facet。超时未知的维度，回答必须明确使用“暂时无法确认”、“获取失败”等定界话术。

## 本阶段完成标准 (Definition of Done)
1. 输入多维要求问题，能提取出多个 facet 并在执行计划中挂载多个并发工具。
2. `BatchToolExecutor` 根据 `config.py` 中的 `deadline_ms` 执行并发控制，未发生串店（shop_id 隔离）。
3. **完成测试**：`tests/test_single_shop_multifacet.py` 编写并 Pass。模拟 `get_distance_eta` Mock 工具超时，最终返回结果正确提示距离暂无法确认，且有券/营业等成功数据不受影响正常展示。

## 阶段完成后的收尾

- 跑并行 facet 测试。
- 确认多个 facet 共享同一个 `shop_id`，并发不会串店，optional 失败会降级而不是中断整单。
