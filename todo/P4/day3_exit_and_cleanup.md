# P4-Day3：最终出口与兼容清理

源文档： [../P4_graph_alignment_finalization_plan.md](../P4_graph_alignment_finalization_plan.md)

## 本日目标

- 把最终出口拆成清晰的收口节点
- 对齐 `final_answer_safety`、`final_safety_fallback`、`final_with_limitations`、`response_builder`、`persist_session`、`emit_final`
- 清理完成后仍然保留的兼容别名和旧路径
- 让收口链只做收口，不再承载前置业务逻辑

## 当前对应实现

- `compose_answer` 里目前仍然混有最终答案生成、审查、修补和持久化相关逻辑
- `persist_session` 和 `emit_final` 已经具备收口能力，但需要和前置安全节点完全分离
- `final_answer_safety` / `final_safety_fallback` / `final_with_limitations` 需要被整理成显式出口，而不是留在隐式 helper 里
- 历史兼容别名需要在这一日统一清理或明确标注为短期过渡

## 本日要对齐的节点

- `final_answer_safety`
- `final_safety_fallback`
- `final_with_limitations`
- `repair_answer`
- `response_builder`
- `persist_session`
- `emit_final`

## 必须避免的架构冗余

- 不要让最终安全校验继续藏在生成节点里
- 不要让兜底输出和正式输出共享一条不透明路径
- 不要在收口阶段再创建新的业务分支
- 不要保留长期存在的“双写 / 双路径 / 双语义”兼容层
- 不要把最终收口和历史兼容互相污染

## 完成标准

- 最终出口链条与 `arc_detail.md` 一致
- 图拓扑导出和 Mermaid 视图能直接说明能力流向
- 旧的兼容别名清理完毕，或已明确标注为临时过渡
- 简单、标准、复杂三类黄金集都能稳定覆盖
- 最终安全、最终兜底、会话持久化三段职责清楚分离
- `clarification_or_reject` 仍保留在前置路径，不与最终出口混淆
- 如果 `final_answer_safety`、`final_safety_fallback`、`response_builder`、`persist_session`、`emit_final` 任何一个仍未显式分层，Day3 不算完成
