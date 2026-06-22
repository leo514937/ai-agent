from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store
from local_life_agent.engine import graph_builder
from local_life_agent.domain.enums import TaskType

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
orig = graph_builder._h_target_resolve

def debug_target_resolve(state):
    sf = state.get('semantic_frame')
    print('TARGET_RESOLVE_ENTER', {
        'task_type': getattr(sf, 'task_type', None),
        'merchant_mentions': getattr(sf, 'merchant_mentions', None),
        'comparison_targets': getattr(sf, 'comparison_targets', None),
        'resolved_target': state.get('resolved_target'),
        'comparison_targets_state': state.get('comparison_targets'),
        'comparison_target_resolution': state.get('comparison_target_resolution'),
    })
    out = orig(state)
    print('TARGET_RESOLVE_OUT', out.get('resolve_shop_result'), out.get('final_response'))
    return out

graph_builder._h_target_resolve = debug_target_resolve
try:
    graph_builder._GRAPH_CACHE = None
    reset_session_store()
    resp = run_agent_graph('海底捞(牡丹园店)和川味轩(知春路店)哪个好？', 'probe_comp3')
    print('FINAL', resp.debug.answer_source, resp.debug.execution_trace)
finally:
    graph_builder._h_target_resolve = orig
    graph_builder._GRAPH_CACHE = None
    clear_llm_backend()
