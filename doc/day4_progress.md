# Day 4 RAG & 推荐系统升级进度文档

## 当天目标回顾

```text
1. 把 RAG 拆成 single_shop_rag 和 recommendation_rag
2. 单店 RAG 必须按 shop_id 强过滤
3. 推荐 RAG 必须 topK 后按 shop_id 分组
4. 附近推荐默认输出 3 家不同商铺
5. Day3 遗留的 Turn 3 意图继承问题修复
```

---

## 已完成改造清单

### 1. Turn 3 意图继承修复 (Day3 收尾)

**问题**：`test_day3_5_coupon_clarification_memory_restore` 第三轮，用户输入裸店名 `"海底捞"`，系统无法继承上一轮的 `coupon` 意图，返回通用推荐而非券查询。

**根因**：`context_arbitration.py` 只在存在 `pending_user_need` 时才恢复意图，对于 `session.current_action` 中已保存的 `coupon` 意图无感知。

**修复方案**：在 `ContextArbitration.arbitrate()` 末尾新增意图延续逻辑：

```python
# context_arbitration.py
if not restored and session.get("current_action") in ("coupon", "open_status", "distance_eta"):
    prev_action = session.get("current_action")
    opposing_keywords = ["环境", "服务", "口味", "特色", "怎么样", "推荐", ...]
    if not any(k in raw_query for k in opposing_keywords):
        # 延续上一轮的专项意图，不允许漂移到通用推荐
        merged_need = UserNeed.model_validate({...intent: prev_action, required_facets: [...]})
        restored = True
        clarification_action = "carry_over_intent"
```

**效果**：
- Turn 1: `"有券吗？"` → 触发澄清，保存 `pending_user_need`
- Turn 2: `"海底捞水晶城店"` → 恢复 coupon 意图，返回实时券信息 ✅
- Turn 3: `"海底捞"` → 继承 `current_action=coupon`，同样返回券信息 ✅

---

### 2. EvidenceScopeGuard 单店强过滤升级 (P0)

**文件**：`evidence_scope_guard.py`

**改动**：新增 `target_shop_id` 参数，在单店 RAG 模式下严格过滤，丢弃所有非目标店证据：

```python
@classmethod
def filter_evidence_claims(cls, evidence_claims, *, ..., target_shop_id: int | None = None):
    if target_shop_id is not None:
        # STRICT SINGLE SHOP MODE: ONLY allow target_shop_id evidence!
        return [item for item if _shop_id(item) == target_shop_id]
    # ...原有多店过滤逻辑...
```

**调用方**：`subgraph.py` 在 RAG 证据过滤时传入：

```python
evidence_claims = EvidenceScopeGuard.filter_evidence_claims(
    evidence_claims,
    ...,
    target_shop_id=target_shop.shop_id if (single_shop_mode and target_shop) else None,
)
```

---

### 3. RAG 模式路由分叉 (P0)

**文件**：`subgraph.py`

**改动**：在 Qdrant 检索阶段，根据 `single_shop_mode` 分叉为两种 RAG 策略：

| 模式 | topK | shop_id 过滤 | metric key |
|------|------|------------|------------|
| `single_shop_rag` | child=30, parent=5 | 强过滤至 target_shop | `rag_mode=single_shop_rag` |
| `recommendation_rag` | child=50, parent=10 | 广谱召回，group by shop_id | `rag_mode=recommendation_rag` |

同时防止在推荐意图下触发单店 RAG fallback：

```python
is_recommendation = user_need.intent in ("local_life_recommend", "restaurant_recommendation")
if not is_recommendation and (not target_shop or target_shop.confidence == 0.0) and ranked_candidates:
    # rag fallback 只在非推荐场景下触发
```

---

### 4. RAG Trace 暴露 evidence_shop_ids (P2)

**文件**：`subgraph.py`

**改动**：在证据过滤完成后，将证据中的 shop_id 集合写入 trace metrics，方便测试断言和调试：

```python
state.metrics["evidence_shop_ids"] = list(set(evidence_shop_ids))
state.metrics["evidence_shop_groups"] = [{"shop_id": sid, "evidence_count": ...} ...]
state.metrics["single_shop_mode"] = single_shop_mode
```

---

### 5. ResponseBuilder 动态推荐数量 (P1)

**文件**：`response_builder.py`

**改动**：将原来硬编码的 `[:3]` 切片替换为基于 `user_need.recommendation_count` 的动态切片：

```python
count = 3
if user_need is not None and hasattr(user_need, "recommendation_count"):
    count = user_need.recommendation_count  # 1 / 3 / 5

for candidate in ranked_candidates[:count]:
    # 构建推荐卡片、店铺列表、优惠券列表
```

**user_need_parser.py** 已经支持解析：
- `"附近有推荐的餐厅"` → count=3（默认）
- `"附近推荐一家"` → count=1
- `"多推荐几家"` → count=5

---

### 6. AnswerContract 默认答题风格修正 (P1)

**文件**：`answer_contract.py`

**改动**：在无 `target_shop` 时，将默认答题风格从 `single_shop_review` 改为 `multi_shop_recommendation`：

```python
elif "shop_detail" in user_focused_facets or not user_focused_facets:
    if target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None):
        answer_style = "single_shop_review"
    else:
        answer_style = "multi_shop_recommendation"   # <-- 修复
```

---

### 7. 新增 Day 4 集成测试套件

**文件**：`tests/local_life/test_day4_rag_recommendation_chat.py`

覆盖以下 5 个验收用例：

| Case | 描述 | 核心断言 |
|------|------|---------|
| D4-1 | single_shop_rag evidence 全部属于目标店 | `rag_mode == "single_shop_rag"` 且 evidence_shop_ids 全为目标 shop_id |
| D4-2 | 第二家店 RAG 不混入第一家店 | 第二轮答案含"巴奴"且不含"海底捞水晶城" |
| D4-3 | 附近推荐默认 3 家 | `rag_mode == "recommendation_rag"` 且推荐≥3家 |
| D4-4 | 用户明确推荐一家 | 推荐结果精确为 1 家且含推荐理由 |
| D4-5 | 多推荐几家 | 推荐结果≥5家或 trace 说明候选不足 |

---

## 测试执行结果

### Day 3 回归测试
- ✅ test_day3_1_multi_tool（双工具执行）
- ✅ test_day3_2_coupon_count（券数量一致）
- ✅ test_day3_3_realtime_no_coupon（实时无券）
- ✅ test_day3_4_no_target_shop_clarify（无店时必须澄清）
- ✅ test_day3_5_coupon_clarification_memory_restore（Turn 1/2 通过，Turn 3 通过 ← **本次修复**）
- ✅ test_day3_regression_day2_1（券不答环境）
- ✅ test_day3_regression_day1_3（指代词继承）

**Day 3 全 7/7 通过 ✅**

### Day 4 集成测试
- ⏳ D4-1 单店 RAG 强过滤（需重启服务后验证）
- ⏳ D4-2 换店 RAG 隔离
- ⏳ D4-3 默认推荐 3 家
- ⏳ D4-4 推荐一家
- ⏳ D4-5 多推荐几家

> **注意**：Day 4 测试由于 Python 服务在原始测试过程中被停止重启，导致第一次运行全部 ConnectError 失败。需要确认服务正常运行后重新执行。

---

## 服务状态
- Qdrant: `6333` ✅
- Java 业务服务: `8081` ✅
- Python FastAPI: `8000` ✅（最近启动于 2026-05-31 15:00）
- PostgreSQL: `5432` ✅

---

## 下一步计划 (Day 5)

1. **验收 Day 4 D4-1 ~ D4-5**：服务启动后执行 `python -m pytest tests/local_life/test_day4_rag_recommendation_chat.py -v`
2. **全量回归**：`python -m pytest tests/local_life/ -v`
3. **开始 Day 5 LangGraph 迁移**：将 `single_shop_rag` 和 `recommendation_rag` 路径迁移为 LangGraph 节点
4. **更新 DAY1_DAY3_USER_ACCEPTANCE.md** 补充 Day 4 验收记录

---

## 改动文件汇总

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `local_life/context_arbitration.py` | 修改 | 新增 `current_action` 意图延续逻辑 |
| `local_life/evidence_scope_guard.py` | 修改 | 新增 `target_shop_id` 严格过滤参数 |
| `local_life/subgraph.py` | 修改 | RAG 模式分叉、trace 暴露、推荐 fallback 保护 |
| `local_life/answer_contract.py` | 修改 | 无目标店时默认 multi_shop_recommendation |
| `local_life/response_builder.py` | 修改 | 动态 recommendation_count 切片 |
| `tests/local_life/test_day4_rag_recommendation_chat.py` | 新增 | D4-1 ~ D4-5 集成测试套件 |
