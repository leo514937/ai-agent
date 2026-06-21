import json
from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store, get_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.tests.test_real_llm_acceptance import SHOP_HAIDILAO, SHOP_KAOROU

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
try:
    for text, sid, setup in [
        ('附近有没有适合约会、现在营业、最好有券的火锅？', 'trace_rec1', None),
        ('便宜一点的呢', 'trace_rec2', lambda: run_agent_graph('附近推荐火锅', 'trace_rec2')),
        ('第一家有券吗', 'trace_rec4', lambda: get_session_store().save('trace_rec4', SessionState(last_recommendation_list=[SHOP_HAIDILAO, SHOP_KAOROU]))),
    ]:
        reset_session_store()
        if setup:
            setup()
        resp = run_agent_graph(text, sid)
        print('TEXT', text)
        print(json.dumps(resp.debug.execution_trace, ensure_ascii=False, default=str))
finally:
    clear_llm_backend()
