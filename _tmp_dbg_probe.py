import json
from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.session.store import reset_session_store

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
reset_session_store()
resp = run_agent_graph('附近有没有适合约会、现在营业、最好有券的火锅？', 'dbg1')
d = resp.debug
print(json.dumps({
    'answer_source': d.answer_source,
    'llm_verbalizer_violation': d.llm_verbalizer_violation,
    'final_response': resp.answer_text,
    'draft_response': getattr(d, 'draft_response', None),
    'semantic_frame': d.semantic_frame,
    'execution_trace_tail': d.execution_trace[-8:],
}, ensure_ascii=False, default=str))
