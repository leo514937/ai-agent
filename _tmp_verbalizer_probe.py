from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.answer import llm_verbalizer
from local_life_agent.answer.b2_mini_verifier import B2MiniVerifier
from local_life_agent.session.store import reset_session_store, get_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.tests.test_real_llm_acceptance import SHOP_HAIDILAO, SHOP_KAOROU

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)

orig_verify = B2MiniVerifier.verify

def pass_verify(self, plan, response_text):
    print('VERIFIER_TEXT_START')
    print(response_text)
    print('VERIFIER_TEXT_END')
    return {'passed': True, 'violations': [], 'violation': None}

B2MiniVerifier.verify = pass_verify
try:
    reset_session_store()
    resp = run_agent_graph('海底捞和山城一锅哪个好？', 'probe_comp')
    print('ANSWER_SOURCE', resp.debug.answer_source)
    print('ANSWER_TEXT', resp.answer_text)
    print('LLM_VIOLATION', resp.debug.llm_verbalizer_violation)
finally:
    B2MiniVerifier.verify = orig_verify
