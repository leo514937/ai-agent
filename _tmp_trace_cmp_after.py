import json
from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
try:
    reset_session_store()
    resp = run_agent_graph('海底捞和山城一锅哪个好？', 'trace_cmp_after')
    print(json.dumps(resp.debug.execution_trace, ensure_ascii=False, default=str))
    print('SF', json.dumps(resp.debug.semantic_frame, ensure_ascii=False, default=str))
    print('ANSWER', resp.debug.answer_source, resp.debug.answer_fallback_reason, resp.answer_text)
finally:
    clear_llm_backend()
