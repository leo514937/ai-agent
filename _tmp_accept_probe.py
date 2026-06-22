"""Acceptance probe for 3 D-pre issues with real OpenRouter."""

import json
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store

backend = OpenAICompatibleBackend()
set_llm_backend(backend)
try:
    reset_session_store()

    # Turn 1 - 推荐 query (Issue 1: recommendation stability)
    r1 = run_agent_graph('\u9644\u8fd1\u63a8\u8350\u706b\u9505', 'accept_t1')
    d1 = r1.debug
    print('=== TURN 1: 附近推荐火锅 ===')
    sf1 = d1.semantic_frame if d1 else {}
    print(f'  semantic_source: {sf1.get("semantic_source")}')
    print(f'  task_type: {sf1.get("task_type")}')
    print(f'  answer_source: {d1.answer_source if d1 else None}')
    print(f'  answer_fallback_reason: {repr(d1.answer_fallback_reason) if d1 else None}')
    print(f'  llm_verbalizer_error: {repr(d1.llm_verbalizer_error) if d1 else None}')
    print(f'  generated_llm: {repr(d1.generated_llm_answer_before_fallback) if d1 else None}')
    print(f'  answer_text: {r1.answer_text[:200]}')

    # Turn 2 - follow-up (Issue 2: recommendation_refine)
    r2 = run_agent_graph('\u4fbf\u5b9c\u4e00\u70b9\u7684\u5462', 'accept_t2')
    d2 = r2.debug
    print()
    print('=== TURN 2: 便宜一点的呢 ===')
    sf2 = d2.semantic_frame if d2 else {}
    print(f'  semantic_source: {sf2.get("semantic_source")}')
    print(f'  task_type: {sf2.get("task_type")}')
    print(f'  answer_source: {d2.answer_source if d2 else None}')
    print(f'  answer_fallback_reason: {repr(d2.answer_fallback_reason) if d2 else None}')
    print(f'  llm_verbalizer_error: {repr(d2.llm_verbalizer_error) if d2 else None}')
    print(f'  generated_llm: {repr(d2.generated_llm_answer_before_fallback) if d2 else None}')
    print(f'  answer_text: {r2.answer_text[:300]}')

finally:
    clear_llm_backend()
