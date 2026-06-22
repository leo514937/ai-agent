from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, call_llm as real_call_llm, clear_llm_backend
from local_life_agent.session.store import reset_session_store
import local_life_agent.llm.client as llm_client_mod

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)

calls = []

def wrapped_call_llm(*args, **kwargs):
    res = real_call_llm(*args, **kwargs)
    prompt = kwargs.get('prompt', args[0] if args else '')
    sys = kwargs.get('system_prompt', args[1] if len(args) > 1 else '')
    kind = 'verbalizer' if 'DecisionPlan' in prompt or 'DecisionPlan' in sys else ('semantic' if 'semantic' in prompt.lower() or 'top_intent' in prompt.lower() else 'other')
    calls.append((kind, res))
    print('CALL_KIND', kind)
    print('OK', res.get('ok'), 'ERR', res.get('error_code'), 'BACKEND', res.get('llm_backend'), 'MODEL', res.get('model'), 'TRANS', res.get('transport'))
    print('RAW', res.get('raw'))
    print('CONTENT', res.get('content'))
    return res

llm_client_mod.call_llm = wrapped_call_llm
try:
    reset_session_store()
    resp = run_agent_graph('海底捞(牡丹园店)和川味轩(知春路店)哪个好？', 'probe_comp2')
    print('FINAL', resp.debug.answer_source, resp.answer_text)
finally:
    llm_client_mod.call_llm = real_call_llm
    clear_llm_backend()
