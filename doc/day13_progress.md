# Day13 进展 - 编排图过渡规划与新架构设计落地 (P1.5)

> 日期：2026-06-06

## 完成事项

### 1. 核心架构设计评估（凌晨 00:15）
- 对比了 [arc.md](file:///d:/javacode/hm-dianping/todo/arc.md) 定义的新架构与 [architecture.md](file:///d:/javacode/hm-dianping/architecture/architecture.md) 描述的现网建议架构。
- 梳理出新架构的 5 大关键转变：基于复杂度的多路由分流、多级执行引擎、闭环自我修复（自愈环）、极前置的 `hard_guard` 防御、以及强契约驱动的校验流。
- 分析并回答了新架构在降低延迟、控制 LLM 算力成本、解决 RAG 空召回/API 异常下的鲁棒性、以及跨域多步推理任务支撑等方面的核心优势。

### 2. 编写 P1.5 编排图过渡规划方案（凌晨 00:24）
- 按照用户提出的 10 项核心设计准则，在 `todo/` 目录下成功创建并深度扩写了规划文件 [P1.5_orchestration_transition_plan.md](file:///d:/javacode/hm-dianping/todo/P1.5_orchestration_transition_plan.md)。
- 详细映射并细化了 10 大准则的具体设计，包括：
  1. `complexity_router` 仅输出执行模式，不耦合底层能力判定。
  2. RAG / Tool / Recommendation 降级为纯粹的原子能力组件，提供无路由控制的统一算子函数签名。
  3. 彻底移除顶层的 `rag_plus_toolcall` 分流，将其内聚到标准分支的 `select_required_sources` 并行分发中。
  4. Contract 节点构建强前置于各执行算子，细化 `SourceContract` 字段。
  5. 任何回答生成（`compose_answer`）前强制引入三分支对应的 Review 校验网关。
  6. Planner 规划器仅为 `COMPLEX` 复杂任务启用，制定硬性判定规则。
  7. 设计 L1 本地规则/缓存校验与 L2 大模型反思校验的分级 Review 机制，控制 90% 以上的标准查询免于 LLM 自我反思的延迟。
  8. 设计严格的死循环防护与计数器上限（重试/重规划上限为 1），超时或失败强制流向 `final_with_limitations` 降级节点。
  9. `TargetShopPolicy` 统一产出 `target_shop` 并锁定下游所有能力算子与 Review 节点的作用域隔离，实现数据强一致性。
  10. 重构强类型的 `GraphState` 状态树结构，并制定了**节点读写权限矩阵**以对职责域进行物理隔离。
- 制定了四阶段渐进式落地执行计划（从状态重构到 Planner 循环集成的完整步骤）。

---

## 下一步建议

1. **执行 Phase 1：重构 `GraphState` 声明并前置 `hard_guard` 节点**：
   - 在 [state.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/state.py) 中更新并扩展为新定义的强类型状态树结构。
   - 在 [builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py) 中将 `load_context` $\rightarrow$ `understand_turn` 中间插入 `hard_guard` 防御节点并解耦 Stage 1-4 逻辑。
2. **执行 Phase 2：引入 `complexity_router` 网关与契约节点**：
   - 建立 `build_source_contract` 与 `build_answer_contract` 节点。
   - 实现路由分类，让原子能力节点仅基于契约条件运行。
