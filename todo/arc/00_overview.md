# Python Query Flow 总览

> 目标：说明 `python` 服务接到一个 `query` 之后，如何流转到 LangGraph 的各个模块，如何得到最终输出，以及哪些 case 会走到哪些分支。

> 说明：本版优先回填 `ChatStreamTestClient` 通过 `/internal/v1/chat/stream` 实测得到的端到端结果。对当前环境里暂时没能稳定命中的分支，会明确标成“源码/单测推导”。

## 实测标记

- `✅`：chat 接口实测命中
- `🧪`：源码或单测已验证
- `⚠️`：当前 chat 实测未自然命中

## 入口

Python 服务的主入口不是单个节点，而是这一条调用链：

```text
ChatWorkflowService.run
  -> create_workflow_runner
  -> LangGraphWorkflowRunner.run_stream / run_state
  -> build_initial_state
  -> compiled LangGraph
```

核心文件：

- `learning-agent-service/src/learning_agent_service/application/use_cases/chat_workflow.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/builder.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/graphs.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py`

## 总体流程图

下面是一个压缩版 ASCII 流程图，先看主干，再看各 case 详解：

```text
query
  -> ChatWorkflowService.run
  -> build_initial_state
  -> LangGraphWorkflowRunner
  -> load_context
  -> request_legality
       -> illegal_request_response ---------> final_answer
       -> hard_guard
            -> clarification_or_reject -----> final_answer
            -> query_safety
                 -> safety_reject_response -> final_answer
                 -> understand_turn
                      -> top_level_intent_router
                           -> identity_answer ---------> final_answer
                           -> capability_answer -------> final_answer
                           -> direct_chat_answer ------> final_answer
                           -> out_of_scope_response ---> final_answer
                           -> safety_reject_response --> final_answer
                           -> final_answer
                           -> query_merge_for_local_life
                                -> merged_query_safety
                                     -> safety_reject_response -> final_answer
                                     -> build_answer_contract
                                          -> target_requirement_router
                                               -> resolve_target_shop
                                               -> resolve_comparison_targets
                                               -> prepare_recommendation_context
                                               -> clarification_node
                                          -> build_source_contract
                                          -> complexity_router
                                               -> clarification_node
                                               -> direct_executor
                                               -> workflow_executor
                                               -> planner_node

direct_executor
  -> rule_review
  -> final_answer

workflow_executor
  -> select_required_sources
  -> source_dispatch
       -> tool_executor ---------+-> merge_or_rank -> contract_review
       -> recommendation_executor/
  -> contract_review
       -> prepare_retry ---------> workflow_executor
       -> final_answer

planner_node
  -> plan_validator
  -> plan_executor
  -> execute_plan_step
       -> tool_executor / recommendation_executor / rank_executor / merge_executor / compose_draft
  -> collect_step_result
  -> all_steps_done?
       -> execute_plan_step
       -> complex_review
            -> final_answer
            -> repair_answer -----> final_answer
            -> final_with_limitations -> final_answer
            -> execute_plan_step
            -> planner_node

final_answer
  -> final_answer_safety
       -> final_safety_fallback
       -> response_builder
  -> persist_session
  -> emit_final
  -> END
```

## 子图

主图里有 4 个真正的子图：

- `understand_turn`
- `rag`
- `tool`
- `recommendation`
- 还有一个复杂路径的 `plan_execute`

它们在 `learning-agent-service/src/learning_agent_service/application/workflow/graphs.py` 中单独定义，但最终都会被主图串起来。

## 实测样本速览

下面这些 case 都是通过 chat 接口实际跑出来的：

| Case | 输入 | 观察到的分支 | 结果摘要 |
|---|---|---|---|
| `D1-1` | `海底捞水晶城店怎么样？` | `历史：rag（当前主图不再直达）` | `single_shop_review`，`ack -> final` |
| `D5-1` | `附近有没有推荐的餐厅？` | `recommendation` | `multi_shop_recommendation`，`ack -> final` |
| `D8-1` | `海底捞水晶城店现在营业吗？` | `tool` | `open_status_only`，`ack -> final` |
| `D9-1` | `海底捞水晶城店离我多远？` | `历史：rag（当前主图不再直达）` | `distance_only`，`ack -> final` |
| `D10-1` | `海底捞和巴奴哪个更适合约会？` | `recommendation` | `comparison`，`ack -> final` |
| `D14-1` | `海底捞水晶城店环境怎么样，有券吗，离我多远？` | `rag_plus_tool` | `facet_multi`，`ack -> final` |
| `D13-1` | `海底捞水晶城店怎么样？` -> `有券吗？` | `session_context` | 后续券问题继承到了同一家店 |

`plan_execute` 在当前 chat 实测里还没有自然命中，见 `05_complex_plan_execute.md`。

## 最终输出怎么来

最终输出不是某一个节点“直接返回字符串”这么简单，而是这条链的结果：

1. `final_answer` 负责确保 `turn.final_answer` 有值。
2. `final_answer_safety` 负责做最终安全审查，必要时替换或修复答案。
3. `response_builder` 负责把答案和对话状态写回 `persistent`、`turn.extra` 等运行态。
4. `persist_session` 负责把会话状态落盘。
5. `emit_final` 把最后事件发出去，SSE 流里看到的最终消息就是它。

如果你走的是非流式接口，那么最终结果会落到 `run_state` 返回的 state 里，答案通常在 `turn.final_answer`。

## 建议阅读顺序

1. 先看 `01_frontdoor_and_intent.md`
2. 再看 `02_understand_turn.md`
3. 然后看 `03_local_life_standard_workflow.md`
4. 再看 `04_local_life_simple_path.md`
5. 接着看 `05_complex_plan_execute.md`
6. 最后看 `06_final_output_and_safety.md`
7. 最后用 `07_node_coverage_matrix.md` 对照节点覆盖
