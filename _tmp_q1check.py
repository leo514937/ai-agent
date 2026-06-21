from local_life_agent import config, agent
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store
import json

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
try:
    agent._GRAPH_CACHE = None
    reset_session_store()
    resp = run_agent_graph('附近有没有适合约会、现在营业、最好有券的火锅？', 'q1check')
    print(json.dumps(resp.debug.execution_trace, ensure_ascii=False, default=str))
    print('ANSWER', resp.debug.answer_source, resp.debug.answer_fallback_reason, resp.answer_text)
    print('META', resp.debug.generated_llm_answer_before_fallback, resp.debug.llm_verbalizer_error, resp.debug.llm_verbalizer_violation)
finally:
    clear_llm_backend()
