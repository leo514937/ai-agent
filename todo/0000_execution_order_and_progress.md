# 0000 文档改造总控顺序

## 目标

明确 `todo/` 下 13 份改造文档的全部修改顺序、执行顺序和进度更新要求，便于后续按“达成目标命令”逐步推进，并在每一步完成后及时更新文档完成进度，方便排查。

## 适用范围

本文件只约束以下 13 份文档：

1. `todo/00_current_architecture_review.md`
2. `todo/01_target_architecture.md`
3. `todo/02_core_module_abstraction.md`
4. `todo/03_workflow_design.md`
5. `todo/04_migration_phases.md`
6. `todo/05_state_and_schema_design.md`
7. `todo/06_toolcall_only_scope.md`
8. `todo/07_testing_and_acceptance.md`
9. `todo/08_risks_and_non_goals.md`
10. `todo/09_implementation_todo.md`
11. `todo/10_orchestration_router_design.md`
12. `todo/11_workflow_pattern_mapping.md`
13. `todo/12_prompt_policy_and_logging_guidelines.md`

> 注：如果后续继续新增文档，应在本总控文档末尾追加索引，不得绕过总控顺序直接修改局部文档。

## 总体修改原则

### 1. 先总后分

- 先修 `0000` 总控文档
- 再修架构总览文档
- 再修 Core / Workflow / State / ToolCall / Test / Risk / Todo / Router / Mapping / Prompt 规范文档

### 2. 先事实后目标

- 先写清当前代码事实
- 再写近期改造
- 再写最终目标
- 最后写 future work

### 3. 先约束后实现

- 先明确禁止项
- 再明确推荐方式
- 再进入具体 phase / todo

### 4. 每次改完都要回写进度

- 每修改完一份文档，必须更新本文件的“进度记录”
- 每完成一个阶段，必须在对应文档中同步阶段完成状态
- 这样后续排查时可以快速定位“改到哪一步、哪份文档还没收口”

## 全部改动顺序

下面顺序是后续执行时的推荐硬顺序，不建议跳步。

### 第一批：总纲与当前事实

1. `0000_execution_order_and_progress.md`
2. `00_current_architecture_review.md`
3. `01_target_architecture.md`

目的：

- 先统一当前事实和最终目标
- 先把 Phase 1 / Phase 4 的边界写清楚
- 先避免把 future workflow 写成当前事实

### 第二批：核心抽象与工作流基础

4. `02_core_module_abstraction.md`
5. `03_workflow_design.md`

目的：

- 先统一 Core 模块命名和职责
- 再统一 workflow 设计和 prompt / policy 方向
- 先把“不写大 if/else”写进设计约束

### 第三批：迁移阶段与状态设计

6. `04_migration_phases.md`
7. `05_state_and_schema_design.md`

目的：

- 先把 Phase 0-8 的顺序固定
- 再把 state / schema 字段统一
- 先保证状态字段能支撑 workflow 和日志

### 第四批：ToolCall 范围与测试验收

8. `06_toolcall_only_scope.md`
9. `07_testing_and_acceptance.md`

目的：

- 先固定 ToolCall-only 的边界
- 再按 workflow 重组测试和验收
- 先确保 current / future / forbidden 工具分层清晰

### 第五批：风险、实施、路由、映射

10. `08_risks_and_non_goals.md`
11. `09_implementation_todo.md`
12. `10_orchestration_router_design.md`
13. `11_workflow_pattern_mapping.md`

目的：

- 先把风险和非目标压住
- 再把实施任务排好
- 再定义二级路由
- 最后固定 workflow 映射表

### 第六批：Prompt / Policy / Logging 总规范

14. `12_prompt_policy_and_logging_guidelines.md`

目的：

- 把 prompt engineering、policy table、日志规范、response 多样性、模块边界约束集中收口
- 作为后续代码执行和排障的统一规范

## 推荐执行命令顺序

如果后续要按命令执行改造，建议按下面顺序推进：

1. 先执行 `0000` 总控文档更新
2. 再执行 `00` 和 `01`
3. 再执行 `02` 和 `03`
4. 再执行 `04` 和 `05`
5. 再执行 `06` 和 `07`
6. 再执行 `08`、`09`、`10`、`11`
7. 最后执行 `12`

如果中途某一步还没完成，不要跳到下一步，避免文档状态和实际进度脱节。

## 进度更新规则

每完成一份文档的修改后，必须立刻更新本文件中的进度记录。

建议记录格式如下：

```text
YYYY-MM-DD HH:mm
- 已完成：todo/01_target_architecture.md
- 已完成内容：补齐两级路由、workflow 目标、Phase 边界
- 待处理：todo/02_core_module_abstraction.md
```

## 当前进度记录

2026-07-01
- 已完成：Phase 0–8 全量检查、专项测试、全量回归分类与审计报告
- 已完成内容：对齐 Phase 0–8 文档与阶段报告，跑完结构检查、Phase 0–8 专项测试、主链路回归与契约测试，输出全量检查报告与 P0–P3 稳定化报告
- 结论：Phase 0 PASS、Phase 1 PARTIAL PASS、Phase 2 PASS、Phase 3 PASS、Phase 4 PASS、Phase 5 PASS、Phase 6 PASS、Phase 7 PASS、Phase 8 PASS
- 全量回归：13 failed, 1000 passed, 12 skipped, 2 xfailed
- 待处理：继续观察全量回归中的 13 个历史断言 / 口径漂移失败，避免把历史测试口径当成新阻塞

2026-06-30
- 已完成：Phase 4 shadow-mode `OrchestrationRouter` 影子接入
- 已完成内容：`GraphState.orchestration_decision`、`planning_subgraph` 影子写入、`SessionState` 隔离、相关测试与文档同步
- 已完成：Phase 5 `workflow_runner`、workflow registry、`discovery_decision` 薄适配接入
- 待处理：Phase 6 起的独立 workflow 拆分

### 已完成

- `0000_execution_order_and_progress.md`
- `00_current_architecture_review.md`
- `01_target_architecture.md`
- `02_core_module_abstraction.md`
- `03_workflow_design.md`
- `04_migration_phases.md`
- `05_state_and_schema_design.md`
- `06_toolcall_only_scope.md`
- `07_testing_and_acceptance.md`
- `08_risks_and_non_goals.md`
- `09_implementation_todo.md`
- `10_orchestration_router_design.md`
- `11_workflow_pattern_mapping.md`
- `12_prompt_policy_and_logging_guidelines.md`

### 最终收口结论

- 已完成 13 份 `todo/` 改造文档的统一修订
- 已完成 `phase0_to_phase8_stabilization_p0_p3_report.md` 新增
- 已对齐当前事实、Phase 边界、Core 抽象、workflow 设计、状态 schema、ToolCall-only 范围、测试验收、风险非目标、实施 TODO、二级路由设计、workflow 映射、Prompt / Policy / Logging 规范
- 已明确当前仍是单主链路，未引入真实 `orchestration_router` / `workflow_runner` / 多 workflow 分流事实
- 已将 `future workflow`、`future tool`、`forbidden` 范围与当前事实彻底分层
- 已把各文档的“当前事实 / 近期改造 / 最终目标 / future work”口径统一
- 已把 Phase 0 / Phase 1 作为近期可开工边界，Phase 4 / 5 及以后作为后续目标
- 目前已补充 Phase 0–8 稳定化专项报告，用于承接 P0 / P1 / P2 / P3 处置结果

## 文档更新完成后的动作

每改完一个文档，必须做三件事：

1. 更新该文档内部的阶段或完成状态
2. 更新本总控文档的进度记录
3. 如果有新增风险或约束，立刻补入对应文档

## 最终收口说明

本轮已完成以下文档的统一修订与收口：

- `00_current_architecture_review.md`
- `01_target_architecture.md`
- `02_core_module_abstraction.md`
- `03_workflow_design.md`
- `04_migration_phases.md`
- `05_state_and_schema_design.md`
- `06_toolcall_only_scope.md`
- `07_testing_and_acceptance.md`
- `08_risks_and_non_goals.md`
- `09_implementation_todo.md`
- `10_orchestration_router_design.md`
- `11_workflow_pattern_mapping.md`
- `12_prompt_policy_and_logging_guidelines.md`

这些文档现在已形成一套连续、同口径、可执行的规范链路。
后续若需要继续改造，应以本文件和 `00/01/04/09/12` 为总纲复核点。

## 禁止事项

1. 不允许跳过总控文档直接改局部文档。
2. 不允许先写未来目标再回头修当前事实。
3. 不允许文档写成“看起来像已经实现”。
4. 不允许改完文档后不回写进度。

## 可执行建议

1. 后续所有 `todo/` 改造，都以本文件作为执行入口。
2. 如果需要继续扩展新文档或新阶段，先更新本文件的索引和进度口径。
3. 如果发现文档间冲突，优先回修本文件和 `00/01/04/09/12` 这几份总纲文档。

## Phase 9 事实补记

- Phase 9 前置闸门已重新核验通过。
- 已完成一次最小化架构收口：移除 `workflow_registry.py` 中当前无读者的 placeholder 兼容分支。
- 最新全量回归结果仍为 `1013 passed, 12 skipped, 2 xfailed`。
- Phase 9 的正式收口报告见 `phase9_final_cleanup_and_convergence_report.md`。

## 进度补记：剩余 10 个旧断言 / fixture / 口径漂移收敛

- 已完成 10 项旧断言 / fixture / 口径漂移问题的收口，均以更新测试断言或测试名为主，没有回退 Phase 0–8 的正式 contract。
- 相关 8 个测试文件已全部通过，`python -m pytest local_life_agent/tests -q` 最终结果为 `1013 passed, 12 skipped, 2 xfailed`。
- 当前不进入 Phase 9，但 Phase 0–8 的审计与验收状态已经显著收敛，可据此重新评估后续阶段推进。
