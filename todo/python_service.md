INFO:     Started server process [1308]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
[DEBUG review_evidence] req=['category', 'distance', 'price'] opt=[]
[DEBUG review_evidence] required_evidence count=3
  [DEBUG] required: facet=category status=ToolStatus.UNKNOWN tool=
  [DEBUG] required: facet=distance status=ToolStatus.UNKNOWN tool=
  [DEBUG] required: facet=price status=ToolStatus.UNKNOWN tool=
[DEBUG review_evidence] optional_evidence count=0
[DEBUG review_evidence] facet_results count=0
INFO:     127.0.0.1:56714 - "POST /internal/v1/chat/stream HTTP/1.1" 200 OK
26-06-26 14:25:59 INFO local_life_agent.python_service {'node': 'receive_input'}
2026-06-26 14:25:59 INFO local_life_agent.python_service {'node': 'load_session_state'}
2026-06-26 14:25:59 INFO local_life_agent.python_service {'node': 'basic_input_validate', 'valid': True}
2026-06-26 14:25:59 INFO local_life_agent.python_service {'node': 'normalize_text'}
2026-06-26 14:25:59 INFO local_life_agent.python_service {'node': 'hard_guard'}
2026-06-26 14:26:04 INFO local_life_agent.python_service {'node': 'top_intent_router', 'intent': 'local_life'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'semantic_parse', 'semantic_source': 'real_llm', 'llm_backend': 'openrouter/deepseek/deepseek-v4-flash', 'fallback_reason': '', 'llm_called': True, 'task_type': <TaskType.recommendation: 'recommendation'>, 'primary_task': '推荐火锅烧烤', 'need_context': False, 'follow_up': {}, 'facets': ['category', 'distance', 'price']}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'slot_extractor', 'mentions': []}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'frame_validator'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'context_recovery', 'status': 'unresolved', 'context_recovery_input_text': '推荐北京邮电大学附近的火锅或烧烤，要性价比高的', 'context_recovery_used_semantic_refs': {'ordinal_references': [], 'deictic_references': [], 'comparison_targets': []}, 'context_recovery_result': {'status': 'unresolved', 'reason': 'no_reference_detected', 'resolution_source': 'raw_text'}, 'reference_resolution_source': 'raw_text'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'goal_planner', 'goal_type': 'recommendation', 'candidate_source': 'discovery', 'unsupported': False}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'goal_review', 'status': 'enough', 'next_action': <NextAction.FINISH: 'FINISH'>, 'reason': 'goal is clear, executable, and supported'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'target_resolve', 'status': 'NEED_CLARIFICATION', 'target_resolve_mode': 'candidate_set', 'candidate_source': 'discovery', 'candidate_count': 0, 'candidate_review_status': 'ReviewStatus.NEED_CLARIFICATION', 'candidate_review_next_action': 'NextAction.CLARIFY', 'next_action': 'CLARIFY', 'reason': 'CandidateResolver returned NOT_FOUND: no candidates found'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'tool_execute', 'tool_call_count': 0, 'tool_failures': [], 'tool_calls': []}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'clarify_response'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'evidence_build', 'candidate_count': 0, 'decision_type': 'recommendation'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'evidence_review', 'next_action': <NextAction.FALLBACK: 'FALLBACK'>, 'status': 'insufficient', 'required_ok': 0, 'required_failed': 0, 'unknown_as_false': True, 'failed_as_empty': False, 'evidence_incomplete': True, 'reason': "all_required_facets_indeterminate: ['category', 'distance', 'price']"}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'decision_planner', 'decision_type': 'recommendation', 'answerable': 0, 'unknown': 0, 'failed': 0, 'has_winner': False}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'decision_review', 'status': 'insufficient', 'next_action': <NextAction.FALLBACK: 'FALLBACK'>, 'reason': 'unknown_as_false_detected_by_evidence_review', 'is_deterministic': False}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'state_update_plan', 'set_fields': [], 'clear_fields': []}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'persist_session_state'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'emit_response'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'state_update_plan', 'set_fields': [], 'clear_fields': []}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'persist_session_state'}
2026-06-26 14:26:21 INFO local_life_agent.python_service {'node': 'emit_response'}
2026-06-26 14:26:21 INFO local_life_agent.python_service turn_end trace_id=trace_1673901688880_session-1782455154003 session_id=session-1782455154003 task_type=None answer_source=clarify_message tool_count=0 final_status=safe
2026-06-26 14:26:21 INFO local_life_agent.python_service chat_stream_final trace_id=trace_1673901688880_session-1782455154003 session_id=session-1782455154003 answer=店名有点模糊，请提供完整店名。 shops=0
