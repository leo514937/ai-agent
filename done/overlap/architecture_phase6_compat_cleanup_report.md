# Architecture Phase 6 Compat Cleanup Report

## 1. 结论

PARTIAL PASS

Phase 6 已完成最小安全清理：确认 `semantic/top_intent_router.py` 没有生产或测试真实调用方后，将其删除；同时清理了两个明显的调试 `print`，分别来自导入修复脚本和 evidence builder 的临时诊断段。  
但 `core/` 与 `planning/` 顶层兼容壳仍然保留，因为当前测试面仍大量依赖它们，`engine/graph_builder.py` 的公共导出面也尚未大幅收缩，所以本阶段不宜标记为完全 `PASS`。

## 2. 本阶段范围

本阶段只做兼容层与大杂烩拆分的安全收口，不重写 router、不改 workflow 总控、不改 state/DTO 契约，也不为了目录整洁强删仍有真实调用方的旧入口。

已执行的动作：

- 删除已确认零调用方的 `local_life_agent/semantic/top_intent_router.py`
- 清理脚手架脚本中的调试 `print`
- 保持 `core/` 与 `planning/` 兼容壳不动，因为测试依赖仍密集

## 3. 删除前的事实核查

### `semantic/top_intent_router.py`

核查结果：

- 生产 import 扫描：0 个调用方
- 测试 import 扫描：0 个调用方
- 文件内容：仅为 `semantic.intent_parser` 的纯兼容包装

结论：

- 可以安全删除

### `core/` 与 `planning/` 顶层兼容壳

核查结果：

- `core/` 仍有测试依赖，不能在本阶段直接删除
- `planning/` 顶层 re-export 壳仍有大量测试依赖，不能在本阶段直接删除

结论：

- 这两类兼容层进入 `NEEDS_MIGRATION` 状态，但不在本阶段强删

## 4. 调试输出清理

已清理：

- `local_life_agent/engine/subgraphs/_fix_imports.py` 中的命令行 `print`
- `local_life_agent/planning/evidence/evidence_builder.py` 中的调试 `print`

保留：

- `eval/run_eval.py` 的 CLI 输出
- 测试文件中的 `print`

原因：

- CLI 输出和测试输出不是 Phase 6 所要清理的调试噪音
- 本阶段只清理明确属于临时诊断的输出

## 5. 未完成但已确认的残余

以下兼容层仍然保留，原因是还有真实调用方或测试迁移成本过高：

- `local_life_agent/core/`
- `local_life_agent/planning/`
- `local_life_agent/engine/_compat.py`
- `local_life_agent/engine/graph_builder.py`

这些模块不是本阶段删除对象，只是下一轮迁移候选。

## 6. 回归结果

已执行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_top_intent_router.py -q`

说明：

- 删除 `semantic/top_intent_router.py` 后，顶层 intent 路由相关测试仍通过
- canonical path `semantic.intent_parser` 可继续作为唯一入口

## 7. Phase 6 退出判断

可以进入 Phase 7 的最终验收与回归稳定工作，但要带着两个明确前提：

- `core/` 与 `planning/` 顶层兼容壳尚未完全清空
- `engine/graph_builder.py` 的导出表面仍需后续继续收缩

因此 Phase 6 的最终状态是 `PARTIAL PASS`，不是 `PASS`
