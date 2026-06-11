# P1: LangGraph 编排图拓扑结构重构与瘦身规划

> 设计日期：2026-06-05  
> 目标：优化 LangGraph 编排图结构，解决 route_gate 业务过载、compose_answer God Node 臃肿、子图逻辑重叠等核心痛点，实现图结构的职责最小化。

---

## 一、 重构背景

经过对现存 `graph.png` 的诊断，编排层暴露出“能跑但偏重、职责交叉”的问题。为了让系统在重构意图路由前具备更干净的拓扑大骨架，我们将图拓扑瘦身列为 P1 阶段任务。

---

## 二、 核心重构任务

### 1. 废弃并移除 `plan_execute_subgraph`
- **说明**：本地生活问答多为单轮或强目的查询，复杂的 Plan-Execute 规划机制在实际业务中极低频，且增加了调用开销。
- **行动**：
  - 在 `builder.py` 的 `StateGraph` 中删除 `plan_execute_subgraph` 节点及相关连线。
  - 安全清理/废弃 `subgraphs.py` 中对应的 `run_plan_execute_subgraph` 包装函数，保持拓扑纯粹。

### 2. 瘦身上帝节点 `compose_answer` (提取独立校验节点)
- **说明**：现有的 `compose_answer` 同时承担了答案生成、文案拼装、兜底降级、以及答案合法性校验（Verifier）等多重职责，维护成本极高。
- **行动**：
  - 将 `AnswerQualityGate` 和 `AnswerLinter` 等校验行为从 `compose_answer` 节点剥离。
  - 在图的最下游、保存会话前，新增独立的 **`verify_answer`** 节点。
  - 连线关系调整：`compose_answer` -> `verify_answer` -> `persist_session`。

### 3. 纯化 `route_gate` 路由节点
- **说明**：`route_gate` 在选路的同时携带了过多的业务修正和临时判断，变成了半个业务编排层。
- **行动**：
  - 重构 `route_gate` 的条件路由逻辑，使其仅负责基于 parser 结果输出路由目标（例如仅返回 `rag` / `tool` / `clarify`）。
  - 将具体的业务修补、规则兜底和数据过滤下沉到具体的子图执行节点内部。

### 4. 消除 `rag_subgraph` 与 `recommendation_subgraph` 重复逻辑
- **说明**：推荐本质上是“广谱检索 + 聚合排序”，与 RAG 单店检索底层共享大量的检索与 Rerank 机制，顶层分立两个子图导致大量重复代码。
- **行动**：
  - 将 RAG 检索和推荐检索底层的 Dense/Sparse/Metadata 检索融合，统一收拢到共享的检索层中。
  - 仅在数据装配面（Evidence / Candidates）根据 RAG 模式（`single_shop_rag` 与 `recommendation_rag`）做轻量策略分流。

### 5. 显式化澄清回路与记忆更新层
- **说明**：澄清分支不应是单向短路，长期记忆与短期 session 应该隔离。
- **行动**：
  - 显式构建 `clarify -> understand_turn` 的循环回路（或在 state 中标志澄清挂起状态）。
  - 新增独立的 **`memory_arbitration`** 记忆更新节点，与被动保存会话的 `persist_session` 解耦。

---

## 三、 涉及文件范围

- **`application/workflow/builder.py`**：修改拓扑结构、节点注册与连线逻辑。
- **`application/workflow/subgraphs.py`**：重构并简化各子图 Lambda 执行包装。
- **`local_life/subgraph/...`**：重构具体的子图核心流程。

---

## 四、 验证方法

1. **拓扑可视化校验**：重构后自动生成的 `graph.png` 中，必须能够清晰地体现出：
   - 无 `plan_execute_subgraph`；
   - 存在独立的 `verify_answer` 或 `quality_gate` 节点；
   - 结构更扁平。
2. **集成测试回归**：运行 `pytest tests/local_life/`，确保拓扑重构不改变正常的 RAG/Tool 合同组装和答案产出。
