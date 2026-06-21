import json
from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.session.store import reset_session_store, get_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.tests.test_real_llm_acceptance import SHOP_HAIDILAO, SHOP_KAOROU
backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
cases = []
reset_session_store(); cases.append(('1', run_agent_graph('附近有没有适合约会、现在营业、最好有券的火锅？', 'real_q1')))
reset_session_store(); cases.append(('2', run_agent_graph('海底捞和山城一锅哪个好？', 'real_q2')))
reset_session_store(); run_agent_graph('附近推荐火锅', 'real_q3'); cases.append(('3', run_agent_graph('便宜一点的呢', 'real_q3')))
reset_session_store(); store = get_session_store(); store.save('real_q4', SessionState(last_recommendation_list=[SHOP_HAIDILAO, SHOP_KAOROU])); cases.append(('4', run_agent_graph('第一家有券吗', 'real_q4')))
for idx, resp in cases:
    d = resp.debug; sf = d.semantic_frame if d else {}
    print(idx, json.dumps({'semantic_source': sf.get('semantic_source'),'llm_backend': sf.get('llm_backend'),'llm_called': sf.get('llm_called'),'fallback_reason': sf.get('fallback_reason'),'task_type': sf.get('task_type'),'reference_resolution_source': sf.get('reference_resolution_source'),'answer_source': getattr(d, 'answer_source', None),'answer_text': resp.answer_text}, ensure_ascii=False))
