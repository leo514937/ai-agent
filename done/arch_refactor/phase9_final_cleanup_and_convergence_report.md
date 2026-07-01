# Phase 9 Final Cleanup / Architecture Convergence 报告

## 1. 结论
PASS

## 2. 前置检查
已通过。

- `phase0_to_phase8_stabilization_p0_p3_report.md` 存在且为 PASS。
- Phase 0–8 最新全量回归保持绿色。
- 五条 workflow 均可稳定回归。
- 三个真实缺口仍保持通过。

## 3. 本轮范围
本轮只做最小化架构收口，不新增能力，不新增 workflow，不新增 tool，不引入 RAG、交易或 mutation。

## 4. 代码改动
- 修改 `local_life_agent/engine/workflow_registry.py`
- 移除当前无真实读者的 placeholder 兼容分支与相关冗余常量

## 5. 删除 / 清理项
- 删除项：`WORKFLOW_STATUS_PLACEHOLDER`、`WORKFLOW_STATUS_UNSUPPORTED`、`_unsupported_workflow(...)`
- 为什么可以删除：仓库中没有任何真实 workflow 注册会走到该分支，源码也没有直接读者
- 当前替代路径：registry 只保留当前合法五条 workflow，未知 / 未注册 workflow 仍由 registry / runner 安全 fallback
- 测试覆盖：`test_workflow_registry.py`、`test_workflow_runner.py`、全量回归
- 是否影响兼容：不影响当前主链路兼容；仅收掉未使用的 placeholder 兼容代码

## 6. Registry / Runner 收敛
- registry 只做白名单注册与查找，不做业务判断
- runner 只读 `orchestration_decision.workflow_name`，只查 registry，随后调用 workflow callable
- runner 的 fallback 仍保持 `WORKFLOW_NAME_MISSING`、`WORKFLOW_NOT_REGISTERED`、`WORKFLOW_RUN_FAILED` 等清晰错误码

## 7. Router 收敛
- 本轮未改 router 行为
- 一级 top_intent 与二级 orchestration 继续分层
- 单店事实查询仍需 verified target anchor 才能进入 deterministic_tool，无 anchor 则走 clarification_fallback

## 8. Workflow 收敛
- `direct_response` 继续只处理轻量直答
- `deterministic_tool` 继续只处理明确单店事实查询
- `discovery_decision` 继续负责搜索 / 推荐 / 对比 / 条件筛选
- `clarification_fallback` 继续处理 ambiguous / reference_failed / missing slot / low confidence / no result / tool failure
- `exploration_planning` 继续只处理多子目标规划

## 9. State Contract 收敛
- 本轮未新增或重写 state/schema contract
- 当前状态字段仍以既有 owner / writer / reader 约束为准
- `workflow_name`、`response_mode`、`task_type` 仍保持分层，不互相替代

## 10. ToolCall-only 收敛
- 本轮未新增 tool
- current tools 仍保持既有白名单
- forbidden capability 继续不进入 current ToolPlan

## 11. Verifier / Response 收敛
- verifier 未放宽
- Response 仍只基于 EvidencePack / DecisionPlan 事实输出
- reordered ranking 与证据外事实的拦截策略保持不变

## 12. Trace / Observability 收敛
- `fallback_reason` 继续可追踪
- workflow_runner 日志字段保持完整
- 本轮未引入新的日志路径分叉

## 13. 测试结果
- `python -m compileall local_life_agent` -> 通过
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q` -> `5 passed`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q` -> `3 passed`

## 14. 全量回归
- `python -m pytest local_life_agent/tests -q`
- 结果：`1013 passed, 12 skipped, 2 xfailed, 1 warning in 42.52s`
- 无 Phase 9 新增 regression

## 15. 文档回写
- `todo/0000_execution_order_and_progress.md`
- `todo/phase0_to_phase8_stabilization_p0_p3_report.md`
- `todo/phase5_workflow_runner_registry_report.md`

## 16. 未处理项
- 真实 E2E / 真实 DB / 真实 LLM 验收仍是后续工作
- Java backend integration 与更广义系统级验收仍未在本轮展开

## 17. 下一步建议
可以进入真实 E2E / 真实 DB / 真实 LLM 验收，但不建议再扩大 Phase 9 范围。

## 18. Post-Phase 9 验收补充
本轮已补做真实运行态检查，结果如下：

- `python -m compileall local_life_agent` -> 通过
- `python -m pytest local_life_agent/tests/test_trace_observability.py -q` -> `5 passed`
- `python -m pytest local_life_agent/tests/test_real_llm_acceptance.py -q` -> `4 passed, 1 skipped`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` -> `7 passed, 1 skipped`
- 真实 LLM 直连调用已验证通过，返回 `ok=True`，实际 transport 为 `httpx`
- `python -m pytest local_life_agent/tests/test_real_llm_contract.py -q` -> `11 passed, 2 failed`，失败原因是当前环境 `localhost:3306` 无法连接 MySQL，触发的是真实 DB 不可达，不是本轮代码编译错误
- `python -m pytest local_life_agent/tests/integration/test_java_backend_live.py -q` -> 全部 skipped，原因是当前环境未启用 `LOCAL_LIFE_RUN_JAVA_INTEGRATION=1` / `LOCAL_LIFE_TOOL_BACKEND=java_api`

### 环境状态
- Python: `3.11.9`
- Git branch: `toolcall`
- Git HEAD: `ef5443aa9edbd04d9fde5dba44faabdb9604046d`
- 当前工作区仍有一批历史脏文件，未回滚
- MySQL: `127.0.0.1:3306` 当前不可达
- Java backend: `127.0.0.1:8081` 当前不可达
- 真实 LLM 配置已可读取，`.env` 中 `LLM_MODEL=deepseek/deepseek-v4-flash`、`LLM_ENDPOINT=https://openrouter.ai/api/v1`

### 观测结论
- 新增 LLM 日志已改为 hash / metadata 形态，不再输出明文 prompt 预览
- 真实 LLM 调用会记录 `temperature` 与 `temperature_source`
- 文件日志落点仍是 `var/python_service.log`
