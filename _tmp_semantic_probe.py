import json
from local_life_agent import config
from local_life_agent.llm.client import call_llm, set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.semantic.intent_parser import parse_semantic_frame
backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
for text in ['附近推荐火锅', '海底捞(牡丹园店)和川味轩(知春路店)哪个好？', '第一家有券吗', '附近有没有适合约会、现在营业、最好有券的火锅？']:
    result = parse_semantic_frame(text, 'local_life', llm_call=call_llm)
    sf = result.get('semantic_frame')
    if hasattr(sf, 'model_dump'):
        sf = sf.model_dump()
    print(text, json.dumps({'semantic_source': result.get('semantic_source'), 'llm_backend': result.get('llm_backend'), 'llm_called': result.get('llm_called'), 'fallback_reason': result.get('fallback_reason'), 'error_code': result.get('error_code'), 'task_type': sf.get('task_type') if isinstance(sf, dict) else None, 'comparison_focus': sf.get('comparison_focus') if isinstance(sf, dict) else None, 'primary_task': sf.get('primary_task') if isinstance(sf, dict) else None}, ensure_ascii=False))
