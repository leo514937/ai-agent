# 模块功能重叠与架构混乱分析（验收版）

> 适用分支: `toolcall`
> 当前结论: `PARTIAL PASS`

## 总体结论

Phase 1-3 已完成冻结与收敛，Phase 4-7 保留了明确的兼容残余或环境依赖，因此本轮最终验收不能写成完全 `PASS`。

## 阶段状态

| Phase | 状态 | 备注 |
|---|---|---|
| Phase 0 | PASS | 事实基线已补齐 |
| Phase 1 | PASS | canonical path 已冻结 |
| Phase 2 | PASS | 路由权威层已收敛 |
| Phase 3 | PASS | LangGraph 外层编排唯一 |
| Phase 4 | PARTIAL PASS | 历史 DTO 兼容窗口仍在 |
| Phase 5 | PARTIAL PASS | `db_tools.resolve_shop` 与历史 DTO 仍保留兼容残余 |
| Phase 6 | PARTIAL PASS | `core/` 与 `planning/` 兼容壳仍有真实调用方 |
| Phase 7 | PARTIAL PASS | 全量回归仍存在已知失败面 / 环境依赖项 |

## 关键报告链接

- [Phase 0 事实基线报告](../done/overlap/architecture_overlap_phase0_fact_baseline_report.md)
- [Phase 1 canonical import paths](../done/overlap/architecture_phase1_canonical_import_paths.md)
- [Phase 1 冻结报告](../done/overlap/architecture_phase1_canonical_path_freeze_report.md)
- [Phase 2 路由权威层收敛报告](../done/overlap/architecture_phase2_routing_authority_convergence_report.md)
- [Phase 3 编排模型收敛报告](../done/overlap/architecture_phase3_orchestration_model_convergence_report.md)
- [Phase 4 状态与 DTO 契约收敛报告](../done/overlap/architecture_phase4_state_dto_contract_convergence_report.md)
- [Phase 5 工具 / DB / fake 边界收敛报告](../done/overlap/architecture_phase5_tools_db_boundary_convergence_report.md)
- [Phase 6 兼容层清理报告](../done/overlap/architecture_phase6_compat_cleanup_report.md)
- [Phase 7 最终回归报告](../done/overlap/architecture_phase7_final_regression_report.md)
- [最终总验收报告](./architecture_phase1_to_phase7_final_acceptance_report.md)

## 最终残余风险

- `core/` 与 `planning/` 顶层兼容壳仍有真实调用方
- `domain/schemas.py` 仍保留历史 DTO 兼容窗口
- `slot_extractor` 仍保留 `task_type` / `workflow_hint` 兼容输出
- `db_tools.resolve_shop` 仍是 resolution-shaped 兼容 helper
- `RUN_E2E_TESTS` / `RUN_INTEGRATION_TESTS` 相关测试仍需要真实环境

## 下一步建议

1. 继续清理仅剩的真实调用方兼容壳，但不要扩大架构面。
2. 将 Phase 7 的失败面按业务链路单独拆分修复。
3. 保持当前 canonical path、router、workflow、tool gateway 的边界不再扩散。
