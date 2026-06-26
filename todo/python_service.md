INFO:     Started server process [6440]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
[DEBUG _build_recommendation_evidence] ranked_snapshot=3, facet_results=9
  [DEBUG] facet=detail result_status=ok
  [DEBUG] facet=open_status result_status=ok
  [DEBUG] facet=coupon result_status=ok
  [DEBUG] facet=distance result_status=ok
  [DEBUG] facet=distance result_status=ok
  [DEBUG] facet=distance result_status=ok
  [DEBUG] facet=rating result_status=ok
  [DEBUG] facet=rating result_status=ok
  [DEBUG] facet=rating result_status=ok
[DEBUG review_evidence] req=['category', 'price', 'distance'] opt=[]
[DEBUG review_evidence] required_evidence count=3
  [DEBUG] required: facet=distance status=ToolStatus.OK tool=
  [DEBUG] required: facet=category status=ToolStatus.UNKNOWN tool=
  [DEBUG] required: facet=price status=ToolStatus.UNKNOWN tool=
[DEBUG review_evidence] optional_evidence count=4
  [DEBUG] optional: facet=detail status=ToolStatus.OK tool=
  [DEBUG] optional: facet=open_status status=ToolStatus.OK tool=
  [DEBUG] optional: facet=coupon status=ToolStatus.OK tool=
  [DEBUG] optional: facet=rating status=ToolStatus.OK tool=
[DEBUG review_evidence] facet_results count=9
[DEBUG answer_verify PASS] task_type=recommendation
INFO:     127.0.0.1:55513 - "POST /internal/v1/chat/stream HTTP/1.1" 200 OK
6-26 17:56:57 INFO local_life_agent.python_service [NODE_EXIT] intake_guard_router status=success duration=3956ms error=none
2026-06-26 17:56:57 INFO local_life_agent.python_service [NODE_ENTER] understanding_subgraph stage=semantic_parse raw_text=推荐北京邮电大学附近的火锅或烧烤，要性价比高的
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'semantic_parse', 'semantic_source': 'real_llm', 'llm_backend': 'openrouter/deepseek/deepseek-v4-flash', 'fallback_reason': '', 'llm_called': True, 'task_type': <TaskType.recommendation: 'recommendation'>, 'primary_task': '推荐附近火锅烧烤', 'need_context': False, 'follow_up': {}, 'facets': ['category', 'price', 'distance']}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'slot_extractor', 'mentions': []}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'frame_validator'}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'context_recovery', 'status': 'unresolved', 'context_recovery_input_text': '推荐北京邮电大学附近的火锅或烧烤，要性价比高的', 'context_recovery_used_semantic_refs': {'ordinal_references': [], 'deictic_references': [], 'comparison_targets': []}, 'context_recovery_result': {'status': 'unresolved', 'reason': 'no_reference_detected', 'resolution_source': 'raw_text'}, 'reference_resolution_source': 'raw_text'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_EXIT] understanding_subgraph status=success duration=12468ms error=none
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_ENTER] planning_subgraph stage=execution_plan raw_text=推荐北京邮电大学附近的火锅或烧烤，要性价比高的
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'goal_planner', 'goal_type': 'recommendation', 'candidate_source': 'discovery', 'unsupported': False}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'goal_review', 'status': 'enough', 'next_action': <NextAction.FINISH: 'FINISH'>, 'reason': 'goal is clear, executable, and supported'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] search_shops call_id= args={'query': "['火锅' '烧烤']"}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] search_shops call_id= success=True status=empty
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] search_shops call_id= args={'query': "['火锅'"}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] search_shops call_id= success=True status=empty
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] search_shops call_id= args={'query': "'烧烤']"}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] search_shops call_id= success=True status=empty
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'target_resolve', 'status': 'NEED_CLARIFICATION', 'target_resolve_mode': 'candidate_set', 'candidate_source': 'discovery', 'candidate_count': 0, 'candidate_review_status': 'ReviewStatus.NEED_CLARIFICATION', 'candidate_review_next_action': 'NextAction.CLARIFY', 'next_action': 'CLARIFY', 'reason': 'CandidateResolver returned NOT_FOUND: no candidates found'}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'evidence_planner', 'evidence_plan_source': 'strict', 'missing_goal': False, 'missing_candidate_set': False, 'tool_calls': 25, 'task_type': 'recommendation', 'candidate_count': 0}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'plan_validator', 'status': 'pass'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_EXIT] planning_subgraph status=success duration=257ms error=none
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_ENTER] execution_review_subgraph stage=evidence_review raw_text=推荐北京邮电大学附近的火锅或烧烤，要性价比高的
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] search_shops call_id= args={'query': '火锅', 'location': {'name': '北京邮电大学', 'lat': 39.9609, 'lng': 116.3581}, 'limit': 20}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] search_shops call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_shop_detail call_id= args={'shop_id': '2'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] check_open_status call_id= args={'shop_id': '2'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_coupon_list call_id= args={'shop_id': '2'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_shop_detail call_id= args={'shop_id': '16'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] check_open_status call_id= args={'shop_id': '16'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_coupon_list call_id= args={'shop_id': '16'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_shop_detail call_id= args={'shop_id': '9'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] check_open_status call_id= args={'shop_id': '9'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_shop_detail call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_coupon_list call_id= args={'shop_id': '9'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_coupon_list call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] check_open_status call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_shop_detail call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] check_open_status call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_shop_detail call_id= args={'shop_id': '15'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] check_open_status call_id= args={'shop_id': '15'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_CALL] get_coupon_list call_id= args={'shop_id': '15'}
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_coupon_list call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_shop_detail call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] check_open_status call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_coupon_list call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] check_open_status call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_shop_detail call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service [TOOL_RESULT] get_coupon_list call_id= success=True status=ok
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'tool_execute', 'tool_call_count': 25, 'tool_failures': [], 'tool_calls': ['call_search_shops', 'call_detail_1', 'call_open_1', 'call_coupon_1', 'call_detail_2', 'call_open_2', 'call_coupon_2', 'call_detail_3', 'call_open_3', 'call_coupon_3', 'call_detail_4', 'call_open_4', 'call_coupon_4', 'call_detail_5', 'call_open_5', 'call_coupon_5', 'call_detail_6', 'call_open_6', 'call_coupon_6', 'call_detail_7']}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'evidence_build', 'candidate_count': 3, 'decision_type': 'recommendation'}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'evidence_review', 'next_action': <NextAction.DEGRADE_ANSWER: 'DEGRADE_ANSWER'>, 'status': 'degraded_with_warnings', 'required_ok': 1, 'required_failed': 0, 'unknown_as_false': True, 'failed_as_empty': False, 'evidence_incomplete': False, 'reason': "required_facets_indeterminate: ['category', 'price'] (unknown_as_false=True, failed_as_empty=False)"}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'decision_planner', 'decision_type': 'recommendation', 'answerable': 5, 'unknown': 0, 'failed': 0, 'has_winner': True}
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'decision_review', 'status': 'insufficient', 'next_action': <NextAction.FALLBACK: 'FALLBACK'>, 'reason': 'unknown_as_false_detected_by_evidence_review', 'is_deterministic': False}
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_EXIT] execution_review_subgraph status=success duration=38ms error=none
2026-06-26 17:57:10 INFO local_life_agent.python_service [NODE_ENTER] response_subgraph stage=answer_generate raw_text=推荐北京邮电大学附近的火锅或烧烤，要性价比高的
2026-06-26 17:57:10 INFO local_life_agent.python_service {'node': 'answer_plan_build', 'answer_plan_source': 'decision_plan', 'has_decision_plan': True}
2026-06-26 17:57:25 INFO local_life_agent.python_service {'node': 'answer_generate', 'answer_source': 'llm_verbalizer', 'rewrite_count': 0, 'fallback_reason': '', 'template_degraded': False, 'fallback_used': False}
2026-06-26 17:57:32 INFO local_life_agent.python_service {'node': 'answer_verify', 'passed': True, 'violations': [], 'final_safety_status': 'safe'}
2026-06-26 17:57:32 INFO local_life_agent.python_service {'node': 'final_response_build', 'answer_source': 'llm_verbalizer', 'final_safety_status': 'safe'}
2026-06-26 17:57:32 INFO local_life_agent.python_service [NODE_EXIT] response_subgraph status=success duration=21881ms error=none
2026-06-26 17:57:32 INFO local_life_agent.python_service [NODE_ENTER] state_update_plan stage=final_response raw_text=推荐北京邮电大学附近的火锅或烧烤，要性价比高的
2026-06-26 17:57:32 INFO local_life_agent.python_service {'node': 'state_update_plan', 'set_fields': [], 'clear_fields': []}
2026-06-26 17:57:32 INFO local_life_agent.python_service {'node': 'persist_session_state'}
2026-06-26 17:57:32 INFO local_life_agent.python_service {'node': 'emit_response'}
2026-06-26 17:57:32 INFO local_life_agent.python_service [NODE_EXIT] state_update_plan status=success duration=1ms error=none
2026-06-26 17:57:32 INFO local_life_agent.python_service turn_end trace_id=trace_2317975604272_session-1782467807029 session_id=session-1782467807029 task_type=recommendation answer_source=llm_verbalizer tool_count=25 final_status=safe
2026-06-26 17:57:32 INFO local_life_agent.python_service chat_stream_final trace_id=trace_2317975604272_session-1782467807029 session_id=session-1782467807029 answer=我帮你查到了几家营业中的火锅店，不过距离信息暂时无法确认。排在第一的是川味观·麻辣火锅，评分 4.0，目前显示有超值代金券、特惠套餐券和VIP尊享券，价格也比较实惠。第二名是小龙坎火锅(春熙路店)，评分 3.4，同样有 3 种券，但人均价格略高一些。第三名是陈麻花·重庆老火锅，评分 3.1，价格适中。综合来看，川味观·麻辣火锅评分和优惠都不错，排在最推荐的位置。 shops=0



推荐北京邮电大学附近的火锅或烧烤，要性价比高的

我帮你查到了几家营业中的火锅店，不过距离信息暂时无法确认。排在第一的是川味观·麻辣火锅，评分 4.0，目前显示有超值代金券、特惠套餐券和VIP尊享券，价格也比较实惠。第二名是小龙坎火锅(春熙路店)，评分 3.4，同样有 3 种券，但人均价格略高一些。第三名是陈麻花·重庆老火锅，评分 3.1，价格适中。综合来看，川味观·麻辣火锅评分和优惠都不错，排在最推荐的位置。