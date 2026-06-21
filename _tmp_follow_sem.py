from local_life_agent import config
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.semantic.intent_parser import parse_semantic_frame
from local_life_agent.llm.client import call_llm

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
for text in ['便宜一点的呢', '附近推荐火锅']:
    result = parse_semantic_frame(text, 'local_life', llm_call=call_llm)
    print(text, result)
clear_llm_backend()
