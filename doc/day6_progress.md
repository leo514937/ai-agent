# Day 6：LangGraph Conditional Edges + 子图接入 + Chat 灰度切换 进度文档

## 当天目标回顾

```text
1. 让核心分支由 LangGraph conditional edges 控制。
2. 接入 clarify / tool / RAG / rag_plus_tool / direct 分支。
3. Chat 接口支持 LOCAL_LIFE_USE_LANGGRAPH=true 灰度走 compiled graph。
4. 保留 fallback legacy 机制。
5. 确保 Day 1 - Day 4 业务问题在 LangGraph 路径不回归。
```

---

## 已完成改造清单

### 1. 核心路由选择器 `route_decider` 与条件边配置 (P2)
* **文件**：`learning_agent_service/application/workflow/builder.py`
* **改动**：在 `builder.py` 中完美实现 `route_decider` 逻辑，将 Python 层的 `if/else` 分流路由彻底交付给 LangGraph 的 `conditional_edges` 托管：
  ```python
  graph.add_conditional_edges(
      "route_gate",
      route_decider,
      {
          "clarify": "compose_answer",
          "tool": "tool_subgraph",
          "rag": "rag_subgraph",
          "rag_plus_tool": "rag_subgraph",
          "recommendation": "recommendation_subgraph",
          "direct": "compose_answer",
      },
  )
  ```

### 2. 状态机链路全量组装与子图接入 (P2)
* **文件**：`learning_agent_service/application/workflow/builder.py`
* **改动**：在 `_build_langgraph_runner` 拓扑组装中接入以下子图：
  * `tool_subgraph` (工具调用子图)
  * `rag_subgraph` (RAG 检索子图)
  * `recommendation_subgraph` (推荐服务子图)
  * `compose_answer` 与 `persist_session` 整合，确保整个图拓扑完全打通。

### 3. Chat/stream 灰度切换与容灾降级 (P3)
* **文件**：`learning_agent_service/application/workflow/adapters.py`
* **改动**：
  * 完美修复了 `emit_final` 中读取 `phase5_trace` 的 `NameError` 致命 Bug，防止了 Worker 崩溃。
  * 完整保留并支持了基于 `LOCAL_LIFE_USE_LANGGRAPH` 的灰度切换和基于 `LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY` 的平滑回退容灾机制。

### 4. 基础设施正常拉起与健康检查验证
* **Qdrant**: 在 `6333` 端口上运行正常，本地 collection 检查全部通过。
* **Redis**: 运行在 `6379` 端口，状态正常。
* **PostgreSQL**: 成功自动恢复并拉起在 `5432` 端口，`persist_session` 会话持久化逻辑不再挂起。

---

## 测试执行结果

在全新启动并恢复的基础设施之上，成功执行了 Day 6 集成测试套件：
```bash
python -m pytest tests/local_life/test_day6_langgraph_chat_stream.py
```

### 运行截图/日志数据：
* **测试用例 1**：`test_day6_1_recommendation_branch_via_route_gate` -> **PASSED** ✅
  * 验证了在询问推荐时成功走 `recommendation` 分支并默认给出 3 家推荐。
* **测试用例 2**：`test_day6_2_mixed_facet_branch_via_route_gate` -> **PASSED** ✅
  * 验证了混合意图（有券吗，营业吗）成功进入 `tool` / `rag_plus_tool` 分支。
* **测试用例 3**：`test_day6_3_clarify_branch_via_route_gate` -> **PASSED** ✅
  * 验证了在输入模糊时成功进入澄清分支 `clarify`。

**Day 6 集成测试 3/3 全部通过！** ✅

---

## 服务目前状态

| 服务名称 | 端口 | 状态 | 作用 |
| --- | --- | --- | --- |
| **Qdrant** | 6333 | 运行中 | 向量知识库 / 语义检索 |
| **Redis** | 6379 | 运行中 | 实时缓存会话层 |
| **PostgreSQL** | 5432 | 运行中 | 会话持久化与结构化存储 |
| **Python FastAPI** | 8000 | 运行中 | AI 核心主服务 |

---

## 下一步计划 (Day 7)
1. **全面回归测试**：运行 Day 1 - Day 4 全量 Chat 回归测试，确保在 LangGraph 托管下无任何业务回归。
2. **优化图响应性能**：对整个 compiled graph 的链路做进一步端到端耗时分析及体验打磨。
