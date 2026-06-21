from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.answer.generator import generate_answer
from local_life_agent.session.store import reset_session_store

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
try:
    reset_session_store()
    resp = run_agent_graph('附近有没有适合约会、现在营业、最好有券的火锅？', 'probe_answer')
    print('GRAPH', resp.debug.answer_source, resp.answer_text)
    metadata = {}
    out = generate_answer(resp.debug.answer_plan, resp.debug.evidence_pack, metadata_out=metadata)
    print('DIRECT', out)
    print('META', metadata)
finally:
    clear_llm_backend()
