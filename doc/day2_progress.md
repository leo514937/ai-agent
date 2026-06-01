# Day 2 进展文档：引入 AnswerContract 及 Facet 防泄露控制

在 Day 2 优化中，我们专注于从 **Context Engineering (上下文工程)** 与 **Harness Engineering (测试套件/评估工程)** 的角度，为本地生活 Agent 引入了 `AnswerContract` 刚性约束控制，成功实现了面向意图切片 (Facet) 的输出控制，并保障了 E2E 多轮会话的稳定性与零回归。

---

## 1. 核心改进内容

### 1.1 Context Engineering (上下文工程) 优化
*   **首创 `AnswerContract` 刚性契约机制**：
    *   在 `learning_agent_service/local_life/answer_contract.py` 中定义了 `AnswerContract` 契约模型。根据用户的 `user_need.required_facets`（如只查询优惠券、只查询营业状态）自动构建对应的 Facet 许可白名单 (`allowed_facets`)、拦截黑名单 (`forbidden_facets`) 以及刚性渲染样式 (`answer_style`)。
*   **多维度模块化模板渲染**：
    *   在 `response_builder.py` 中实现了子模板的刚性渲染，当触发黑名单 Facet 时，自动 fallback 到对应的轻量局部模板（如 `build_coupon_only_answer`、`build_open_status_only_answer`、`build_single_shop_review_answer` 等）。
*   **多轮 Facet 污染强力隔离**：
    *   在 `subgraph.py` 中重构了多轮会话 Session 上下文生命周期管理。在多轮分析时，仅继承当前的实体 shop_id 及其基本属性，**强行剔除历史轮的 Facet 级检索偏好**（如 `scene`, `local_life_preferences`, `local_life_avoid` 等），实现会话实体级完美继承与偏好隔离。
*   **实体解析边界纠错与指代消解优化**：
    *   **解决后缀过早截断 bug**：在 `entity_resolver.py` 中重构了 `_EXPLICIT_SUFFIXES` 的匹配优先级，通过**长后缀匹配优先**策略（例如优先匹配 `"现在营业吗"`，再匹配 `"营业吗"`），彻底解决了 `"海底捞现在营业吗"` 被截断成商户名 `"海底捞现在"` 并导致候选数据库 502/空匹配的问题。
    *   **Facet 词尾深度剥离**：在 `entity_resolver.py` 中为显式实体新增了 `_strip_facet_suffixes` 控制。提问 `"海底捞水晶城店环境怎么样？"` 时，自动剥离词尾的 Facet 词汇 `"环境"`，精准提取 `"海底捞水晶城店"`，彻底解决多轮会话继承 `"海底捞水晶城店环境"` 导致在其他 Facet（如券）中泄露 `"环境"` 词汇的隐蔽 bug。

### 1.2 Harness Engineering (测试工程) 优化
*   **构建了刚性拦截校验器 `validate_answer_against_contract`**：
    *   对大模型或 RAG 返回的最终 Answer 进行刚性逐行扫描，阻断属于 `forbidden_facets` 的所有非法关键字。
    *   实现了防 `None` 和防 `AttributeError` 空值鲁棒保护，规避了 RAG 候选列表为空时由于 `NoneType` 导致的抛错和空应答漏洞。
*   **Day 2 自动化测试套件验收**：
    *   编写了 `tests/local_life/test_day2_answer_contract_chat.py` 自动化测试套件，全面覆盖 4 项 Day 2 本次核心契约拦截用例与 3 项 Day 1 零回归测试：
        *   **D2-1**: Coupon-only 不得答环境用例通过。
        *   **D2-2**: Open-status-only 不得答推荐用例通过。
        *   **D2-3**: General-review 综合回答正常输出。
        *   **D2-4**: 多轮上下文仅继承实体、不继承 Facet 且防 Facet 污染泄露用例通过。
        *   **D1 Regression**: 显式单店、多轮覆盖、指代继承用例全部完美零回归通过！

---

## 2. 自动化测试结果验证

在确保后台依赖服务 (Spring Boot Java Business API on port 8081, FastAPI Python Server on port 8000, MySQL, Redis, Postgres, Qdrant) 稳定拉起就绪的情况下，运行全量测试，结果为 **100% 完美通过 (Green)**！

### 2.1 Day 2 契约与多轮拦截测试 (test_day2_answer_contract_chat.py)
```bash
python -m pytest tests/local_life/test_day2_answer_contract_chat.py
```
**运行结果截图/日志概要**：
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0
rootdir: D:\javacode\hm-dianping\learning-agent-service
configfile: pyproject.toml
plugins: anyio-4.13.0, langsmith-0.7.23, logfire-4.31.0, cov-7.1.0
collected 7 items

tests\local_life\test_day2_answer_contract_chat.py .......               [100%]

================== 7 passed, 1 warning in 169.91s (0:02:49) ===================
```

### 2.2 Day 1 单店与多轮指代继承测试 (test_day1_target_shop_chat.py)
```bash
python -m pytest tests/local_life/test_day1_target_shop_chat.py
```
**运行结果截图/日志概要**：
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0
rootdir: D:\javacode\hm-dianping\learning-agent-service
configfile: pyproject.toml
plugins: anyio-4.13.0, langsmith-0.7.23, logfire-4.31.0, cov-7.1.0
collected 4 items

tests\local_life\test_day1_target_shop_chat.py ....                      [100%]

================== 4 passed, 1 warning in 148.23s (0:02:28) ===================
```

---

## 3. 下阶段工作建议 (Day 3 / 后续规划)
1.  **大模型推理时延迟进一步降低**：对大模型 Assistant 部分的 `compose_answer_plan` 提示词进行结构化剪裁，利用 `AnswerContract` 给出的显式指令进行 Prompt 裁剪，降低 Input Tokens 并提升大模型首字响应速度 (TTFT)。
2.  **增强极端异常容错**：对候选 RAG 在冷启动或物理数据全空时的 fallback 提示语进行更细粒度的意图对齐，确保大语言模型始终可以输出高度符合人类语言直觉的兜底回答。
