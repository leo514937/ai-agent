# LangGraph Active-State / Comparison Second Acceptance Report

## 1. 结论

**PARTIAL PASS**

本轮目标已经收敛到两条主链路：

- 工具失败时不误写 `current_shop`
- `single_coupon_flow` 明确店名 + 优惠券链路稳定

这两项主链路专项已通过；但全量 `pytest` 仍存在与本轮范围外相关的存量失败，因此整体只能判定为 **PARTIAL PASS**，不是全仓 PASS。

## 2. 本轮已确认通过的内容

### 2.1 current_shop 写回门禁

- 工具失败 / timeout / error / missing required tool 时，不会把 resolved shop 静默落成 `current_shop`
- `state_update_planner` 仍然是写回闸门，不是工具层直接落盘

### 2.2 single_coupon_flow

- 明确店名 + 优惠券链路已按当前真实行为对齐
- 旧断言已不再要求过时的 fake backend / 伪造字段行为

### 2.3 comparison / target resolve

- comparison 链路仍以 `target_resolve` 作为正式对象解析出口
- 未解析目标不会绕过门禁直接进入 planning / execution
- comparison 候选解析已收紧，避免推荐/发现流污染比较目标

## 3. 当前真实路由图

```text
START
→ intake_guard_router
→ active_turn_resolver
→ conditional route
```

主要分支仍是：

```text
normal_query/topic_switch → top_intent_router
pending_restored → merge_clarification / planning
pending_invalid/out_of_range/cancelled/expired → clarification 或清 pending
```

相关实现位置：

- [graph_builder](../local_life_agent/engine/graph_builder.py)
- [intake_guard_router](../local_life_agent/engine/subgraphs/intake_guard_router.py)
- [active_turn_resolver](../local_life_agent/engine/subgraphs/active_turn_resolver.py)
- [state_update_planner](../local_life_agent/planning/plans/state_update_planner.py)

## 4. 结果分桶

### A. 主链路验收

**PASS**

- current_shop 写回门禁正确
- single_coupon_flow 当前链路稳定
- comparison / target_resolve 门禁仍有效

### B. 字段契约

**PASS**

- 未恢复 `{data,total}` envelope
- 未恢复 coupon 伪造字段
- 未恢复 `AgentShopDTO.tags` 推断
- `unsupported` 没有被偷偷降级为 `unknown`

### C. 全量测试

**FAIL（存量失败）**

全量 `pytest` 仍有失败，主要不是本轮主链路回退，而是旧测试/环境/资源问题：

- 缺失 mock 数据资源
- 旧 fake backend 断言仍在
- streaming / wrapper / top-intent 的旧语义断言仍在
- 部分测试依赖真实 LLM / DB / fixture

## 5. 全量失败分桶结论

### 5.1 mock 数据缺失

**FAIL**

- 例如缺失 `local_life_agent/mock_data/shops.json`
- 属于测试资源补齐问题，不是主链路逻辑回退

### 5.2 旧 fake backend 断言

**FAIL**

- `TOOL_BACKEND='fake'` 在 runtime 已不再是支持面
- 相关旧测试需要迁移到当前 backend contract

### 5.3 streaming / wrapper / top-intent 旧断言

**FAIL**

- 仍有测试盯旧 fallback / stream / wrapper 语义
- 这类失败与本轮 active-state/comparison 修复不直接相关

### 5.4 real LLM / real DB 依赖

**FAIL**

- 部分测试依赖真实 LLM 或 DB
- 需要单独隔离或补 fixture，不应倒逼主链路回退

## 6. 关键判断

1. 主链路验收通过，但不是全仓通过。
2. 当前失败主要是存量测试迁移问题，不是这轮改动把主链路弄坏。
3. 不应为了追求全绿而回退 current_shop / coupon / comparison 的契约收敛。

## 7. 后续建议

- 继续补齐或迁移缺失 mock 数据
- 清理仍依赖 fake backend 的旧测试
- 统一 marker / fixture 语义
- 保持当前主链路门禁，不回退为旧行为
