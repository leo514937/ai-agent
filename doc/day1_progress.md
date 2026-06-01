# Day1 进展文档：基线测试 + TargetShopPolicy + 多轮实体覆盖

## 当前状态：✅ **全部完成**

完成时间：2026-05-29

---

## 完成情况总览

- [x] Phase 1: 规划与调研
  - [x] 阅读 `Day1_baseline_target_shop.md` 执行文档
  - [x] 分析代码库结构（`UserNeedParser`、`EntityResolver`、`ResponseBuilder`、`subgraph.py`）
  - [x] 分析流式端点实现 (`/api/ai/chat/stream`)
- [x] Phase 2: 核心策略实现
  - [x] 新增 `target_shop_policy.py`（TargetShop 模型 + TargetShopPolicy.resolve_target）
  - [x] 修复 `user_need_parser.py`（shop_query 误触发 shop_detail 的问题）
  - [x] 修复 `entity_resolver.py`（集成 TargetShopPolicy，输出 target_shop 至 ExecutionContract）
  - [x] 修复 `subgraph.py`（从 ExecutionContract 读取 target_shop，写入 metrics）
  - [x] 修复 `route_review.py`（指代词判定加入 TargetShopPolicy session 继承，避免误触发 clarification）
- [x] Phase 3: 测试套件实现
  - [x] 新增 `chat_test_client.py`（支持 SSE 解析 + ChatStreamResult 返回）
  - [x] 新增 `golden_cases/local_life_chat_cases.yaml`
  - [x] 新增 `test_day1_target_shop_chat.py`（4 个集成测试）
- [x] Phase 4: 验证 & 快照生成
  - [x] D1-1、D1-2、D1-3 全部通过
  - [x] D1-4 Baseline 快照已生成（保存于 `scratch/day1_baseline_snapshots.yaml`）

---

## 测试结果

```
4 passed, 1 warning in 283.30s (0:04:43)
```

| 测试用例 | 描述 | 结果 |
|---|---|---|
| `test_day1_1_explicit_single_shop` | Case D1-1：显式单店评价，target_shop.source = current_query | ✅ PASSED |
| `test_day1_2_multi_turn_override` | Case D1-2：多轮显式新商铺覆盖旧商铺 | ✅ PASSED |
| `test_day1_3_pronoun_inheritance` | Case D1-3：指代词继承旧商铺，target_shop.source = pronoun_session | ✅ PASSED |
| `test_day1_4_baseline_snapshot` | Case D1-4：Baseline 4个问题快照生成 | ✅ PASSED |

---

## 核心文件变更

### 新增文件

| 文件 | 说明 |
|---|---|
| `learning-agent-service/src/learning_agent_service/local_life/target_shop_policy.py` | TargetShop 数据模型 + TargetShopPolicy 核心策略（5 级优先级链） |
| `learning-agent-service/tests/local_life/chat_test_client.py` | SSE 流式响应测试客户端 |
| `learning-agent-service/tests/local_life/test_day1_target_shop_chat.py` | Day1 集成测试（4 个验收用例） |
| `learning-agent-service/tests/local_life/golden_cases/local_life_chat_cases.yaml` | 黄金用例定义文件 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `entity_resolver.py` | 集成 TargetShopPolicy，优先从 policy 获取 target_shop，输出至 ExecutionContract |
| `subgraph.py` | 从 ExecutionContract 取 target_shop，写入 metrics（target_shop.source / shop_id / shop_name / single_shop_mode） |
| `route_review.py` | 指代词澄清前先用 TargetShopPolicy 检查 session 继承，只有真正找不到才触发 clarification |
| `application/use_cases/chat_workflow.py` | 扩充本地生活分流关键词，将 `"券"/"它"/"这家"/"这店"` 加入分流名单 |

---

## 关键技术发现与解决

### 问题 1：指代词导致误触发 clarification（D1-3 核心问题）
**根因**：`route_review.py` 中仅检查 `user_need.context_refs`（LLM 解析的结构化引用），但 session 中的 `current_shop` 并不会自动填充 `context_refs`。  
**修复**：在 `RouteReview._review_impl` 中，有指代词时先调用 `TargetShopPolicy().resolve_target()`，若能从 session 找到 `selected_shop_name` / `current_shop`，则跳过 clarification 分支，让正常流程继续处理并正确继承店名。

### 问题 2：环境代理拦截（所有 E2E 测试的通用坑）
**根因**：本地系统代理会拦截 127.0.0.1 的 SSE 流，导致 `RemoteProtocolError`。  
**修复**：测试运行时必须清除代理环境变量 `HTTP_PROXY=''`、`HTTPS_PROXY=''`、`NO_PROXY='*'`。

---

## 槽位冲突解决优先级（已落实）

```
当前轮显式商铺 > 用户选择序号 > 指代词 + session.current_shop > session.current_shop > RAG top1 fallback
```

严禁（已有断言保障）：
- `session.current_shop` 覆盖当前轮显式商铺
- `RAG top1` 覆盖当前轮显式商铺
- `ranked_candidates[0]` 覆盖 `target_shop`

---

## Day2 准备事项

Day1 的基础设施已完备，Day2 可直接复用 `ChatStreamTestClient` 进行验收：
- AnswerContract 与 ResponseBuilder 的约束落实
- 多 facet 组合回答结构
- 回答锁死 target_shop 而非 ranked_candidates[0]

---

## Post-Day1 Bug 修复记录（2026-05-29）

### Bug 1：山城一锅 / 巴奴查询不到
**结论**：不是代码 Bug，是**数据 Bug**。Java 数据库中没有这两家店。
- `GET /shop/of/name?name=山城一锅` → `data: []`（Java真实数据库返空）
- Fallback 走 catalog mock 数据，返回了错误的店铺
- **解决方案**：在 MySQL 中插入山城一锅、巴奴等真实店铺数据

### Bug 2：海底捞有100张券，AI说只有1张
**根因**：`stock=100` 是库存张数，`count=1` 是券的种类数（只有1种券）。此前判定为 `total_stock != count` 时才显示库存，如果正好 1 种券 1 张库存（数值相等）就被漏掉了，且逻辑判断稍显局限。  
**修复**（`subgraph.py`）：简化逻辑，只要 `total_stock > 0`，就一律输出 "X种券，共Y张库存"，确保库存信息任何时候都不被吞。

### Bug 3：多轮问"附近有吗" → 回答城市名 → 500错误
**根因**：`_should_use_local_life_subgraph` 用关键词匹配判断分流，"北京"等单字城市名不在匹配列表里，导致落入旧版 `SequentialWorkflowRunner`，该路径无法处理 LocalLifeSubgraph 的 pending_clarification，报500。  
**修复**（`chat_workflow.py`）：  
1. 在关键词列表中增加主要城市名和商圈词
2. 更关键的是：检查 session 的 `pending_clarification`，若非空（表示上轮 LocalLifeSubgraph 提过问题），无论用户回答什么，都强制进入 LocalLifeSubgraph 处理

### Bug 4：代词 "他" / "她" / "第一家" / "这几家" 鲁棒性问题
**根因**：用户问 “他评价怎么样” 或 “她怎么样” 时，`route_review.py` 中的 `has_pronoun` 检测仅覆盖了 "它" 等基础代词，且后端的 `TargetShopPolicy` 以及 `EntityResolver` 中的 `_PRONOUNS` 也局限于 "它/这家" 等基础词，遗漏了拼写或指代的多样性（比如 "他"、"她"、“第一家”），导致未能正确识别指代并进入 session 商铺继承流程。  
**修复**（`route_review.py` + `target_shop_policy.py` + `entity_resolver.py`）：将 `"他"`、`"她"`、`"这几家"`、`"第一家"`、`"第二家"` 等常用指代词全面补全进这三处核心文件的判定集合中，极大提升了多轮指代路由的健壮性。

### 修改文件
| 文件 | 变更 |
|---|---|
| `chat_workflow.py` | 分流函数加城市名关键词 + pending_clarification 检查 + 接收 persistent 参数 |
| `subgraph.py` | 券摘要文本区分"种类数"和"库存总量"，并优化库存存在时的展示逻辑 |
| `route_review.py` | 扩充指代词集合，支持“他”、“她”、“第一家”等多轮继承指代词 |
| `target_shop_policy.py` | 补全 `_PRONOUNS` 支持，确保 session 实体的正确继承与消解 |
| `entity_resolver.py` | 补全 `_PRONOUNS` 支持，确保指代消解过滤器的正常运行 |




