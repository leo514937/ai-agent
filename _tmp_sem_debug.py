from local_life_agent import config
from local_life_agent.llm.client import call_llm, set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.semantic.intent_parser import parse_semantic_frame

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
for text in ['附近有没有适合约会、现在营业、最好有券的火锅？', '附近推荐火锅', '便宜一点的呢']:
    result = parse_semantic_frame(text, 'local_life', llm_call=call_llm)
    sf = result.get('semantic_frame')
    print('TEXT', text)
    print('RESULT', result.get('semantic_source'), result.get('llm_backend'), result.get('llm_called'), result.get('fallback_reason'), result.get('error_code'))
    print('RAW', result.get('raw'))
    print('FRAME', sf.model_dump() if hasattr(sf, 'model_dump') else sf)
    print('---')
